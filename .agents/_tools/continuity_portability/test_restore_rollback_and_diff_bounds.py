#!/usr/bin/env python3
"""AOS-15 W5 focused shard: restore rollback and bounded-diff guards."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import receipt_hash
from continuity_portability.test_support import (
    export_bundle,
    prepare_fixture,
)

SHARD_ID = "restore-rollback-and-diff-bounds"
GROUPS = ("restore",)
TIMEOUT_SECONDS = 120


def scenario_restore_rollback_and_failure_injection(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-rollback-") as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        targets = [
            root.parent / "docs/roadmap.md",
            root.parent / "docs/context/current-status.md",
        ]
        for target in targets:
            target.write_bytes(b"password=hunter2\n")
        privacy_backup_plan = service.plan_restore(destination)
        privacy_before = [target.read_bytes() for target in targets]
        privacy_backup_result = service.apply_restore(
            privacy_backup_plan["plan"]["plan_id"],
            True,
        )
        cases.append(
            (
                "restore-backup-rejects-supported-sensitive-before-image",
                privacy_backup_result.get("reason_codes")
                == ["PORTABILITY_RESTORE_BACKUP_FAILED"]
                and [target.read_bytes() for target in targets] == privacy_before,
            )
        )

        for target in targets:
            target.write_bytes(b"drift before restore\n")
        before = [target.read_bytes() for target in targets]
        planned = service.plan_restore(destination)
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            failed = service.apply_restore(
                planned["plan"]["plan_id"],
                True,
                test_fail_after=1,
            )
        cases.append(
            (
                "partial-restore-rolls-back-byte-for-byte",
                failed.get("reason_codes") == ["PORTABILITY_RESTORE_FAILED_ROLLED_BACK"]
                and failed.get("rollback_verified") is True
                and [target.read_bytes() for target in targets] == before,
            )
        )

        retry_plan = service.plan_restore(destination)
        retry = service.apply_restore(
            retry_plan["plan"]["plan_id"],
            True,
        )
        cases.append(
            (
                "successful-rollback-allows-identical-restore-retry",
                retry_plan.get("ok") is True
                and retry_plan["plan"]["backup_id"] != planned["plan"]["backup_id"]
                and retry.get("ok") is True
                and service.validate_restore_receipt(retry["receipt"]) == [],
            )
        )

        for target in targets:
            target.write_bytes(b"drift before post-receipt restore\n")
        before_after_receipt = [target.read_bytes() for target in targets]
        planned_after_receipt = service.plan_restore(destination)
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            after_receipt = service.apply_restore(
                planned_after_receipt["plan"]["plan_id"],
                True,
                test_fail_stage="after-receipt",
            )
        cases.append(
            (
                "post-receipt-failure-removes-false-receipt-and-rolls-back",
                after_receipt.get("reason_codes")
                == ["PORTABILITY_RESTORE_FAILED_ROLLED_BACK"]
                and after_receipt.get("rollback_verified") is True
                and after_receipt.get("false_receipt_removed") is True
                and [target.read_bytes() for target in targets] == before_after_receipt,
            )
        )

        for target in targets:
            target.write_bytes(b"drift before receipt cleanup failure\n")
        before_cleanup_failure = [target.read_bytes() for target in targets]
        cleanup_plan = service.plan_restore(destination)
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            cleanup_failure = service.apply_restore(
                cleanup_plan["plan"]["plan_id"],
                True,
                test_fail_stage="after-receipt",
                test_fail_receipt_cleanup=True,
            )
        restore_orphan = next(
            (
                json.loads(path.read_text(encoding="utf-8"))
                for path in (
                    root / "project/context/continuity-portability-receipts"
                ).glob("*.json")
                if json.loads(path.read_text(encoding="utf-8")).get("plan_id")
                == cleanup_plan["plan"]["plan_id"]
            ),
            None,
        )
        restore_cleanup_listing = service.list_receipts()
        restore_failed_plan = json.loads(
            (service.plans / f"{cleanup_plan['plan']['plan_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        cases.append(
            (
                "restore-receipt-cleanup-failure-leaves-only-invalid-provisional-receipt",
                cleanup_failure.get("reason_codes")
                == ["PORTABILITY_RESTORE_ROLLBACK_INCOMPLETE"]
                and cleanup_failure.get("rollback_verified") is False
                and cleanup_failure.get("false_receipt_removed") is False
                and [target.read_bytes() for target in targets]
                == before_cleanup_failure
                and restore_orphan is not None
                and restore_orphan.get("status") == "prepared"
                and restore_orphan.get("content_sha256") == receipt_hash(restore_orphan)
                and service.validate_restore_receipt(restore_orphan)
                == ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
                and not any(
                    receipt.get("plan_id") == cleanup_plan["plan"]["plan_id"]
                    for receipt in restore_cleanup_listing.get("receipts", [])
                )
                and any(
                    error.get("code") == "PORTABILITY_RESTORE_RECEIPT_INVALID"
                    for error in restore_cleanup_listing.get("errors", [])
                )
                and restore_failed_plan.get("status") == "failed"
                and restore_failed_plan.get("content_sha256")
                == receipt_hash(restore_failed_plan),
            )
        )

        for target in targets:
            target.write_bytes(b"drift before incomplete rollback\n")
        incomplete_plan = service.plan_restore(destination)
        with (
            patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False),
            patch.object(service, "restore_backup", return_value=False),
        ):
            incomplete = service.apply_restore(
                incomplete_plan["plan"]["plan_id"],
                True,
                test_fail_after=1,
            )
        cases.append(
            (
                "incomplete-rollback-has-distinct-fail-closed-reason",
                incomplete.get("reason_codes")
                == ["PORTABILITY_RESTORE_ROLLBACK_INCOMPLETE"]
                and incomplete.get("rollback_verified") is False
                and incomplete.get("writes_started") is True,
            )
        )


def scenario_restore_diff_output_bound(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-bounded-diff-") as temporary:
        root = prepare_fixture(Path(temporary), payload_mode="portable-bytes")
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        binary_target = root.parent / "docs/context/current-status.md"
        binary_target.write_bytes(b"\x00" + b"x" * 70000)
        bounded_plan = service.plan_restore(destination)
        cases.append(
            (
                "binary-and-large-restore-diff-is-hash-summary-bounded",
                bounded_plan.get("ok") is True
                and "Binary/large payload:" in bounded_plan["plan"]["exact_diff"]
                and len(bounded_plan["plan"]["exact_diff"].encode("utf-8"))
                <= 1024 * 1024,
            )
        )


SCENARIOS = (
    (
        "restore-rollback-and-failure-injection",
        (
            "restore-backup-rejects-supported-sensitive-before-image",
            "partial-restore-rolls-back-byte-for-byte",
            "successful-rollback-allows-identical-restore-retry",
            "post-receipt-failure-removes-false-receipt-and-rolls-back",
            "restore-receipt-cleanup-failure-leaves-only-invalid-provisional-receipt",
            "incomplete-rollback-has-distinct-fail-closed-reason",
        ),
        scenario_restore_rollback_and_failure_injection,
    ),
    (
        "restore-diff-output-bound",
        ("binary-and-large-restore-diff-is-hash-summary-bounded",),
        scenario_restore_diff_output_bound,
    ),
)


if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                str(TOOLS_DIR / "test-continuity-portability.py"),
                "--shard",
                SHARD_ID,
                *sys.argv[1:],
            ]
        )
    )
