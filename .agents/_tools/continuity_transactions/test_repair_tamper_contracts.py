#!/usr/bin/env python3
"""Repair, backup/receipt tamper, schema boundaries and aggregate runner."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_context_memory import receipt_hash, sha256_bytes
from agent_os_continuity_transactions import (
    BACKUP_DIR_REL,
    BACKUP_INDEX_FIELDS,
    TRANSACTION_DIR_REL,
    TRANSACTION_RECEIPT_FIELDS,
)
from continuity_transactions.test_initialize_rollback_contracts import (
    evaluate_initialize_rollback_contracts,
)
from continuity_transactions.test_migration_failure_contracts import (
    evaluate_migration_failure_contracts,
)
from continuity_transactions.test_support import (
    SOURCE_ROOT,
    W3,
    initialize,
    make_fixture,
    write_json,
)

RECEIPT_MIGRATION_FIELDS = {"migration_path", "migration_path_sha256"}
MIGRATION_PATH_REQUIRED = {
    "migration_id",
    "provider",
    "source_generation",
    "target_generation",
    "unknown_fields_sha256",
}


def evaluate_repair_tamper_contracts() -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory(prefix="aos15-w4-repair-") as temporary:
        root = make_fixture(Path(temporary), configured=False)
        service, initialized = initialize(root)
        source_before = {
            relative: (root.parent / relative).read_bytes()
            for relative in (
                ".agents/project/project-binding.json",
                ".agents/project/context/active-tasks.json",
            )
        }
        roadmap = root.parent / "docs/roadmap.md"
        roadmap.write_text("# Updated roadmap\n", encoding="utf-8")
        W3.commit_all(root.parent, "update canonical roadmap")
        repair_plan = service.plan_repair()
        repaired = (
            service.apply(repair_plan["plan"]["plan_id"], True)
            if repair_plan.get("ok")
            else repair_plan
        )
        source_after = {
            relative: (root.parent / relative).read_bytes()
            for relative in source_before
        }
        cases.append(
            (
                "repair-refreshes-metadata-without-mutating-canonical-sources",
                repaired.get("ok") is True
                and repaired.get("receipt", {}).get("operation") == "repair"
                and source_before == source_after,
            )
        )
        backup_id = initialized["backup"]["backup_id"]
        index_path = root / BACKUP_DIR_REL / backup_id / "index.json"
        original_index = json.loads(index_path.read_text(encoding="utf-8"))
        index = deepcopy(original_index)
        index["project_id"] = "wrong-project"
        index["content_sha256"] = receipt_hash(index)
        write_json(index_path, index)
        wrong_project = service.backup_contents(backup_id)
        cases.append(
            (
                "wrong-project-backup-is-rejected",
                wrong_project[0] is None
                and wrong_project[1] == ["CONTINUITY_BACKUP_INDEX_INVALID"],
            )
        )
        populated_backup_id = repaired["backup"]["backup_id"]
        populated_index_path = (
            root / BACKUP_DIR_REL / populated_backup_id / "index.json"
        )
        populated_index = json.loads(populated_index_path.read_text(encoding="utf-8"))
        redirected = deepcopy(populated_index)
        redirected_file = next(item for item in redirected["files"] if item["present"])
        redirect_target = root / "project/context/active-tasks.json"
        redirect_content = redirect_target.read_bytes()
        redirected_file["storage_path"] = "project/context/active-tasks.json"
        redirected_file["sha256"] = sha256_bytes(redirect_content)
        redirected_file["bytes"] = len(redirect_content)
        redirected["content_sha256"] = receipt_hash(redirected)
        write_json(populated_index_path, redirected)
        redirected_result = service.backup_contents(populated_backup_id)
        cases.append(
            (
                "rehashed-backup-cannot-redirect-storage-path",
                redirected_result[0] is None
                and redirected_result[1] == ["CONTINUITY_BACKUP_INDEX_INVALID"],
            )
        )
        write_json(populated_index_path, populated_index)
        write_json(index_path, original_index)
        transaction_id = initialized["receipt"]["transaction_id"]
        receipt_path = root / TRANSACTION_DIR_REL / f"{transaction_id}.json"
        tampered_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        tampered_receipt["unexpected_authority"] = "must-fail-closed"
        tampered_receipt["content_sha256"] = receipt_hash(tampered_receipt)
        write_json(receipt_path, tampered_receipt)
        invalid_receipt = service.transaction_receipt(transaction_id)
        cases.append(
            (
                "rehashed-receipt-with-extra-field-fails-closed",
                invalid_receipt[0] is None
                and invalid_receipt[1] == ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"],
            )
        )

    receipt_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-transaction-receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    backup_schema = json.loads(
        (SOURCE_ROOT / "core/contracts/continuity-backup-index.schema.json").read_text(
            encoding="utf-8"
        )
    )
    cases.append(
        (
            "transaction-contracts-pin-privacy-and-non-mutation-boundaries",
            all(
                receipt_schema["properties"][field]["const"] is False
                for field in (
                    "source_deleted",
                    "owner_confirmation_performed",
                    "raw_conversation_stored",
                    "commit_created",
                    "push_performed",
                )
            )
            and set(receipt_schema["required"]) == TRANSACTION_RECEIPT_FIELDS
            and set(receipt_schema["properties"])
            == TRANSACTION_RECEIPT_FIELDS | RECEIPT_MIGRATION_FIELDS
            and backup_schema["properties"]["raw_conversation_stored"]["const"] is False
            and set(backup_schema["required"]) == BACKUP_INDEX_FIELDS
            and set(backup_schema["properties"]) == BACKUP_INDEX_FIELDS,
        )
    )
    return cases


def evaluate_receipt_schema_contracts() -> list[tuple[str, bool]]:
    schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-transaction-receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    properties = schema["properties"]
    migration_path = properties["migration_path"]
    conditional = schema["allOf"]
    return [
        (
            "legacy-required-fields-remain-stable-with-additive-properties",
            set(schema["required"]) == TRANSACTION_RECEIPT_FIELDS
            and set(properties)
            == TRANSACTION_RECEIPT_FIELDS | RECEIPT_MIGRATION_FIELDS
            and all(
                properties[field]["const"] is False
                for field in (
                    "source_deleted",
                    "owner_confirmation_performed",
                    "raw_conversation_stored",
                    "commit_created",
                    "push_performed",
                )
            ),
        ),
        (
            "migration-path-shape-is-bounded-and-fail-closed",
            migration_path["type"] == "array"
            and migration_path["minItems"] == 1
            and migration_path["maxItems"] == 8
            and migration_path["items"]["additionalProperties"] is False
            and set(migration_path["items"]["required"]) == MIGRATION_PATH_REQUIRED
            and set(migration_path["items"]["properties"])
            == MIGRATION_PATH_REQUIRED,
        ),
        (
            "generation-two-migrate-requires-both-additive-fields",
            conditional
            == [
                {
                    "if": {
                        "properties": {
                            "operation": {"const": "migrate"},
                            "target_generation": {"const": 2},
                        }
                    },
                    "then": {
                        "required": ["migration_path", "migration_path_sha256"]
                    },
                    "else": {
                        "not": {
                            "anyOf": [
                                {"required": ["migration_path"]},
                                {"required": ["migration_path_sha256"]},
                            ]
                        }
                    },
                }
            ],
        ),
        (
            "migration-hashes-retain-lowercase-sha256-contract",
            properties["migration_path_sha256"]["pattern"] == "^[0-9a-f]{64}$"
            and migration_path["items"]["properties"]["unknown_fields_sha256"][
                "pattern"
            ]
            == "^[0-9a-f]{64}$",
        ),
    ]


def evaluate_all_contracts() -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []
    cases.extend(evaluate_initialize_rollback_contracts())
    cases.extend(evaluate_migration_failure_contracts())
    cases.extend(evaluate_repair_tamper_contracts())
    cases.extend(evaluate_receipt_schema_contracts())
    return cases


def run_focused() -> None:
    cases = evaluate_repair_tamper_contracts()
    failed = [case_id for case_id, passed in cases if not passed]
    output = {
        "ok": not failed,
        "passed": len(cases) - len(failed),
        "total": len(cases),
        "cases": [{"id": case_id, "passed": passed} for case_id, passed in cases],
        "failed": failed,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


def run_schema_focused() -> None:
    cases = evaluate_receipt_schema_contracts()
    failed = [case_id for case_id, passed in cases if not passed]
    output = {
        "ok": not failed,
        "passed": len(cases) - len(failed),
        "total": len(cases),
        "cases": [{"id": case_id, "passed": passed} for case_id, passed in cases],
        "failed": failed,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


def run_aggregate() -> None:
    cases = evaluate_all_contracts()
    failed_cases = [case_id for case_id, passed in cases if not passed]
    result = {
        "ok": not failed_cases,
        "executable_cases": len(cases),
        "non_executable_cases": 2,
        "deferred_cases": [
            {
                "id": "C23",
                "target": "AOS15-W5",
                "reason": "offline export/restore bundle",
            },
            {
                "id": "C26",
                "target": "AOS15-W6",
                "reason": "clean-clone release recovery",
            },
        ],
        "cases": [{"id": case_id, "passed": passed} for case_id, passed in cases],
        "failed": failed_cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focused", action="store_true")
    parser.add_argument("--schema-focused", action="store_true")
    arguments = parser.parse_args()
    if arguments.schema_focused:
        run_schema_focused()
    if arguments.focused:
        run_focused()
    run_aggregate()


if __name__ == "__main__":
    main()
