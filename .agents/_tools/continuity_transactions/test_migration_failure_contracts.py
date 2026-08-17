#!/usr/bin/env python3
"""Migration rejection, rollback and failure-window acceptance contracts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_continuity_transactions import (
    BACKUP_DIR_REL,
    CATALOG_REL,
    PROJECTION_REL,
    TRANSACTION_DIR_REL,
    ContinuityTransactionService,
)
from continuity_transactions.test_support import make_fixture, make_v0, write_json


def evaluate_migration_failure_contracts() -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory(prefix="aos15-w4-c20-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        before = make_v0(root, unknown=True)
        service = ContinuityTransactionService(root)
        rejected = service.plan_migrate()
        cases.append(
            (
                "C20-unknown-field-migration-fails-before-write",
                rejected.get("reason_codes")
                == ["CONTINUITY_MIGRATION_UNKNOWN_FIELDS_UNSUPPORTED"]
                and (root / CATALOG_REL).read_bytes() == before
                and not (root / BACKUP_DIR_REL).exists(),
            )
        )

    with tempfile.TemporaryDirectory(prefix="aos15-w4-migrate-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        source_bytes = make_v0(root, unknown=False)
        source_catalog = json.loads(source_bytes)
        source_catalog.pop("migration_extensions", None)
        write_json(root / CATALOG_REL, source_catalog)
        source_bytes = (root / CATALOG_REL).read_bytes()
        service = ContinuityTransactionService(root)
        plan = service.plan_migrate()
        applied = (
            service.apply(plan["plan"]["plan_id"], True) if plan.get("ok") else plan
        )
        target_catalog = json.loads((root / CATALOG_REL).read_text(encoding="utf-8"))
        receipt = applied.get("receipt", {})
        metadata = plan.get("plan", {}).get("metadata", {})
        cases.append(
            (
                "known-v0-to-v2-migration-preserves-evidence",
                plan.get("ok") is True
                and applied.get("ok") is True
                and target_catalog.get("schema_version") == 2
                and target_catalog.get("catalog_revision") == 1
                and receipt.get("source_generation") == 0
                and receipt.get("target_generation") == 2
                and len(metadata.get("migration_path", [])) == 2
                and receipt.get("migration_path") == metadata.get("migration_path")
                and receipt.get("migration_path_sha256")
                == metadata.get("migration_path_sha256")
                and receipt.get("critical_set_before")
                == receipt.get("critical_set_after")
                and source_catalog["references"] == target_catalog["references"],
            )
        )

    with tempfile.TemporaryDirectory(prefix="aos15-w6-multihop-failure-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        source_catalog = json.loads(make_v0(root, unknown=False))
        source_catalog.pop("migration_extensions", None)
        write_json(root / CATALOG_REL, source_catalog)
        source_bytes = (root / CATALOG_REL).read_bytes()
        service = ContinuityTransactionService(root)
        plan = service.plan_migrate()
        transaction_id = plan.get("plan", {}).get("metadata", {}).get("transaction_id", "")
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            failed = service.apply(plan["plan"]["plan_id"], True, test_fail_after=1)
        cases.append(
            (
                "multi-hop-failure-rolls-back-source-and-removes-receipt",
                plan.get("ok") is True
                and failed.get("reason_codes")
                == ["CONTINUITY_APPLY_FAILED_ROLLED_BACK"]
                and failed.get("rollback_verified") is True
                and failed.get("receipt_cleanup_verified") is True
                and (root / CATALOG_REL).read_bytes() == source_bytes
                and not (
                    root / TRANSACTION_DIR_REL / f"{transaction_id}.json"
                ).exists(),
            )
        )

    with tempfile.TemporaryDirectory(prefix="aos15-w4-c21-") as temporary:
        root = make_fixture(Path(temporary), configured=False)
        service = ContinuityTransactionService(root)
        plan = service.plan_initialize()
        before_catalog = (
            (root / CATALOG_REL).read_bytes() if (root / CATALOG_REL).exists() else None
        )
        before_projection = (
            (root / PROJECTION_REL).read_bytes()
            if (root / PROJECTION_REL).exists()
            else None
        )
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            failed = service.apply(plan["plan"]["plan_id"], True, test_fail_after=1)
        after_catalog = (
            (root / CATALOG_REL).read_bytes() if (root / CATALOG_REL).exists() else None
        )
        after_projection = (
            (root / PROJECTION_REL).read_bytes()
            if (root / PROJECTION_REL).exists()
            else None
        )
        cases.append(
            (
                "C21-partial-write-rolls-back-byte-for-byte",
                failed.get("reason_codes") == ["CONTINUITY_APPLY_FAILED_ROLLED_BACK"]
                and failed.get("rollback_verified") is True
                and before_catalog == after_catalog
                and before_projection == after_projection,
            )
        )

    with tempfile.TemporaryDirectory(prefix="aos15-w4-c22-") as temporary:
        root = make_fixture(Path(temporary), configured=False)
        service = ContinuityTransactionService(root)
        plan = service.plan_initialize()
        roadmap = root.parent / "docs/roadmap.md"
        roadmap.write_text("# Drift after plan\n", encoding="utf-8")
        rejected = service.apply(plan["plan"]["plan_id"], True)
        cases.append(
            (
                "C22-source-drift-rejects-stale-plan",
                rejected.get("reason_codes") == ["CONTINUITY_PLAN_SOURCE_DRIFT"]
                and not (root / CATALOG_REL).exists()
                and not (root / BACKUP_DIR_REL).exists(),
            )
        )

    with tempfile.TemporaryDirectory(prefix="aos15-w4-receipt-window-") as temporary:
        root = make_fixture(Path(temporary), configured=False)
        service = ContinuityTransactionService(root)
        plan = service.plan_initialize()
        transaction_id = plan["plan"]["metadata"]["transaction_id"]
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            failed = service.apply(plan["plan"]["plan_id"], True, test_fail_after=3)
        cases.append(
            (
                "post-receipt-failure-rolls-back-and-removes-false-receipt",
                failed.get("reason_codes") == ["CONTINUITY_APPLY_FAILED_ROLLED_BACK"]
                and failed.get("rollback_verified") is True
                and failed.get("receipt_cleanup_verified") is True
                and failed.get("plan_failure_recorded") is True
                and not (root / CATALOG_REL).exists()
                and not (root / PROJECTION_REL).exists()
                and not (
                    root / TRANSACTION_DIR_REL / f"{transaction_id}.json"
                ).exists(),
            )
        )
    return cases


def main() -> None:
    cases = evaluate_migration_failure_contracts()
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
