#!/usr/bin/env python3
"""Focused P1b3 checks for dependency-ordered apply, receipt and rollback."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import json_bytes, receipt_hash
from agent_os_continuity_portability import (
    RESTORE_RECEIPT_FIELDS,
    ContinuityPortabilityService,
    artifact_id,
)
from continuity_portability.test_support import (
    export_bundle,
    initialize_w4,
    prepare_fixture,
    rehash_restore_plan,
    write_json,
)

SOURCE_ROOT = Path(__file__).resolve().parents[2]
TARGET_PATHS = ("docs/roadmap.md", "docs/context/current-status.md")


def dependency_fixture(base: Path) -> Path:
    root = prepare_fixture(base)
    catalog_path = root / "project/context/continuity.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    next(
        item
        for item in catalog["references"]
        if item["reference_id"] == "current-status"
    )["dependencies"] = [
        {"relation": "generated-from", "target_reference_id": "roadmap"}
    ]
    catalog_path.write_bytes(json_bytes(catalog))
    initialize_w4().W3.commit_all(root.parent, "bind dependency apply fixture")
    return root


def rehash_receipt(receipt: dict[str, Any]) -> None:
    receipt["receipt_id"] = artifact_id(
        receipt,
        "continuity-restore-",
        "receipt_id",
    )
    receipt["content_sha256"] = receipt_hash(receipt)


def write_forged_plan(
    service: ContinuityPortabilityService,
    plan: dict[str, Any],
    order: list[str],
) -> dict[str, Any]:
    forged = deepcopy(plan)
    forged["target_execution_order"] = order
    rehash_restore_plan(forged)
    write_json(service.plans / f"{forged['plan_id']}.json", forged)
    return forged


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": passed, **details})

    with tempfile.TemporaryDirectory(prefix="aos15-w6-p1b3-") as temporary:
        base = Path(temporary)
        root = dependency_fixture(base / "fixture")
        destination = base / "bundle"
        service, _applied = export_bundle(root, destination)
        roadmap = root.parent / TARGET_PATHS[0]
        current = root.parent / TARGET_PATHS[1]
        roadmap.write_bytes(b"drifted roadmap before ordered apply\n")
        current.write_bytes(b"drifted current before ordered apply\n")
        planned = service.plan_restore(destination)
        plan = planned["plan"]
        path_by_id = {item["entry_id"]: item["path"] for item in plan["targets"]}
        target_paths = [item["path"] for item in plan["targets"]]
        execution_paths = [path_by_id[item] for item in plan["target_execution_order"]]
        check(
            "plan-keeps-canonical-inventory-and-dependency-execution-order",
            target_paths == sorted(target_paths)
            and execution_paths == list(TARGET_PATHS),
        )

        forged_results = []
        orders = [
            list(reversed(plan["target_execution_order"])),
            [plan["target_execution_order"][0]] * 2,
            [plan["target_execution_order"][0], f"continuity-entry-{'f' * 24}"],
        ]
        for order in orders:
            forged = write_forged_plan(service, plan, order)
            with patch.object(
                service,
                "create_restore_backup",
                wraps=service.create_restore_backup,
            ) as backup:
                result = service.apply_restore(forged["plan_id"], True)
            forged_results.append((result.get("reason_codes"), backup.call_count))
        check(
            "forged-reversed-duplicate-or-unknown-order-fails-before-backup",
            forged_results
            == [(["PORTABILITY_RESTORE_DEPENDENCY_ORDER_INVALID"], 0)] * 3,
            results=forged_results,
        )

        successful_writes: list[str] = []
        original_atomic = service._atomic_scoped_bytes

        def record_success(
            scoped_root: Path,
            relative: str,
            content: bytes,
            **kwargs: Any,
        ) -> Path:
            if scoped_root == service.project_root and relative in TARGET_PATHS:
                successful_writes.append(relative)
            return original_atomic(scoped_root, relative, content, **kwargs)

        with patch.object(
            service,
            "_atomic_scoped_bytes",
            side_effect=record_success,
        ):
            applied = service.apply_restore(plan["plan_id"], True)
        receipt = applied["receipt"]
        check(
            "apply-writes-dependency-first",
            applied.get("ok") is True and successful_writes == list(TARGET_PATHS),
            writes=successful_writes,
        )

        backup_index = json.loads(
            (root.parent / receipt["backup"]["index_path"]).read_text(encoding="utf-8")
        )
        check(
            "backup-inventory-remains-canonical-path-sorted",
            [item["path"] for item in backup_index["files"]] == sorted(TARGET_PATHS),
        )
        receipt_paths = [item["path"] for item in receipt["targets"]]
        receipt_order = [path_by_id[item] for item in receipt["target_execution_order"]]
        check(
            "receipt-binds-execution-order-and-canonical-inventory",
            receipt_paths == sorted(TARGET_PATHS)
            and receipt_order == list(TARGET_PATHS)
            and service.validate_restore_receipt(receipt) == [],
        )

        schema = json.loads(
            (
                SOURCE_ROOT / "core/contracts/continuity-restore-receipt.schema.json"
            ).read_text(encoding="utf-8")
        )
        check(
            "receipt-schema-runtime-required-field-parity",
            set(schema["required"]) == RESTORE_RECEIPT_FIELDS
            and schema["properties"]["target_execution_order"]["uniqueItems"] is True,
        )

        invalid_receipts = []
        for order in (
            [],
            [receipt["target_execution_order"][0]] * 2,
            [receipt["target_execution_order"][0], f"continuity-entry-{'f' * 24}"],
            [{}, receipt["target_execution_order"][0]],
        ):
            forged = deepcopy(receipt)
            forged["target_execution_order"] = order
            rehash_receipt(forged)
            invalid_receipts.append(service.validate_restore_receipt(forged))
        check(
            "receipt-rejects-missing-duplicate-unknown-or-malformed-order-entry",
            invalid_receipts == [["PORTABILITY_RESTORE_RECEIPT_INVALID"]] * 4,
        )

        roadmap.write_bytes(b"rollback roadmap bytes\n")
        current.write_bytes(b"rollback current bytes\n")
        before = {roadmap: roadmap.read_bytes(), current: current.read_bytes()}
        failure_plan = service.plan_restore(destination)["plan"]
        failure_writes: list[str] = []
        original_atomic = service._atomic_scoped_bytes

        def record_failure(
            scoped_root: Path,
            relative: str,
            content: bytes,
            **kwargs: Any,
        ) -> Path:
            if scoped_root == service.project_root and relative in TARGET_PATHS:
                failure_writes.append(relative)
            return original_atomic(scoped_root, relative, content, **kwargs)

        with (
            patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False),
            patch.object(
                service,
                "_atomic_scoped_bytes",
                side_effect=record_failure,
            ),
        ):
            failed = service.apply_restore(
                failure_plan["plan_id"],
                True,
                test_fail_after=2,
            )
        check(
            "mid-order-failure-rolls-back-in-reverse-execution-order",
            failed.get("reason_codes") == ["PORTABILITY_RESTORE_FAILED_ROLLED_BACK"]
            and failed.get("rollback_verified") is True
            and failure_writes == [*TARGET_PATHS, *reversed(TARGET_PATHS)]
            and all(path.read_bytes() == content for path, content in before.items()),
            writes=failure_writes,
        )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
