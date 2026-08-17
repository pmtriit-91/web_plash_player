#!/usr/bin/env python3
"""Initialize, confirmation, containment, listing and rollback contracts."""

from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_context_memory import canonical_hash, encoded, receipt_hash, sha256_bytes
from agent_os_continuity_transactions import (
    CATALOG_REL,
    PROJECTION_REL,
    TRANSACTION_DIR_REL,
    ContinuityTransactionService,
)
from continuity_transactions.test_support import make_fixture, write_json


def evaluate_initialize_rollback_contracts() -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory(prefix="aos15-w4-init-") as temporary:
        root = make_fixture(Path(temporary), configured=False)
        service = ContinuityTransactionService(root)
        plan = service.plan_initialize()
        cases.append(
            (
                "initialize-plan-is-reviewable-and-non-applying",
                plan.get("ok") is True
                and plan["plan"]["operation"] == "initialize"
                and plan["plan"]["metadata"]["target_generation"] == 2
                and (root / CATALOG_REL).exists() is False
                and plan["plan"]["commit_created"] is False
                and plan["plan"]["push_performed"] is False,
            )
        )
        denied = service.apply(plan["plan"]["plan_id"], False)
        cases.append(
            (
                "initialize-requires-explicit-confirmation",
                denied.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"]
                and not (root / CATALOG_REL).exists(),
            )
        )
        malicious = deepcopy(plan["plan"])
        active_tasks = root / "project/context/active-tasks.json"
        active_before = active_tasks.read_bytes()
        malicious_change = malicious["changes"][0]
        malicious_change["path"] = "project/context/active-tasks.json"
        malicious_change["before_base64"] = encoded(active_before)
        malicious_change["before_sha256"] = sha256_bytes(active_before)
        malicious_change["after_base64"] = encoded(b"{}\n")
        malicious_change["after_sha256"] = sha256_bytes(b"{}\n")
        malicious["exact_diff"] = service.render_exact_diff(malicious["changes"])
        malicious["plan_id"] = canonical_hash(
            {
                key: value
                for key, value in malicious.items()
                if key not in {"plan_id", "content_sha256"}
            }
        )[:24]
        malicious["content_sha256"] = receipt_hash(malicious)
        write_json(service.plans / f"{malicious['plan_id']}.json", malicious)
        escaped = service.apply(malicious["plan_id"], True)
        cases.append(
            (
                "rehashed-plan-cannot-write-outside-continuity-targets",
                escaped.get("reason_codes") == ["CONTINUITY_PLAN_CHANGES_INVALID"]
                and active_tasks.read_bytes() == active_before,
            )
        )
        applied = service.apply(plan["plan"]["plan_id"], True)
        receipt = applied.get("receipt", {})
        target_catalog = json.loads((root / CATALOG_REL).read_text(encoding="utf-8"))
        cases.append(
            (
                "initialize-materializes-catalog-backup-projection-and-receipt",
                applied.get("ok") is True
                and applied.get("health", {}).get("topology_state") == "complete"
                and (root / CATALOG_REL).is_file()
                and (root / PROJECTION_REL).is_file()
                and target_catalog.get("schema_version") == 2
                and (
                    root / TRANSACTION_DIR_REL / f"{receipt.get('transaction_id')}.json"
                ).is_file()
                and receipt.get("operation") == "initialize"
                and receipt.get("source_generation") is None
                and receipt.get("target_generation") == 2
                and "migration_path" not in receipt
                and "migration_path_sha256" not in receipt
                and receipt.get("source_deleted") is False
                and receipt.get("owner_confirmation_performed") is False
                and receipt.get("raw_conversation_stored") is False,
            )
        )
        transaction_list = service.list_transactions()
        cases.append(
            (
                "transaction-list-validates-durable-receipts",
                transaction_list.get("ok") is True
                and len(transaction_list.get("transactions", [])) == 1,
            )
        )
        rollback_plan = service.plan_rollback(receipt["transaction_id"])
        rollback = service.apply(rollback_plan["plan"]["plan_id"], True)
        cases.append(
            (
                "rollback-restores-unconfigured-by-exact-backup",
                rollback.get("ok") is True
                and rollback.get("health", {}).get("state") == "UNCONFIGURED"
                and not (root / CATALOG_REL).exists()
                and not (root / PROJECTION_REL).exists()
                and rollback.get("receipt", {}).get("rollback_verified") is True,
            )
        )
    return cases


def main() -> None:
    cases = evaluate_initialize_rollback_contracts()
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


if __name__ == "__main__":
    main()
