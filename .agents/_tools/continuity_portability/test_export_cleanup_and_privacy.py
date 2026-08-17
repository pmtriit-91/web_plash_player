#!/usr/bin/env python3
"""AOS-15 W5 focused shard: export cleanup and privacy guards."""

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
from agent_os_continuity_portability import ContinuityPortabilityService
from continuity_portability.test_support import (
    prepare_fixture,
)

SHARD_ID = "export-cleanup-and-privacy"
GROUPS = ("export",)
TIMEOUT_SECONDS = 120


def scenario_export_missing_context_source_guard(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-missing-source-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        (root / "project/context/hot.json").unlink()
        missing = service.build_export_manifest()
        cases.append(
            (
                "missing-context-transitive-source-blocks-export",
                not missing.get("ok")
                and "PORTABILITY_CONTEXT_NOT_FRESH" in missing.get("reason_codes", []),
            )
        )


def scenario_export_and_archive_cleanup_recovery(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-portability-cleanup-"
    ) as temporary:
        root = prepare_fixture(Path(temporary), historical=True)
        service = ContinuityPortabilityService(root)
        export_destination = Path(temporary) / "failed-export"
        export_plan = service.plan_export(export_destination)
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            export_failure = service.apply_portability(
                export_plan["plan"]["plan_id"],
                True,
                expected_operation="export",
                test_fail_stage="after-receipt",
            )
        cleanup_failure_destination = Path(temporary) / "cleanup-failed-export"
        cleanup_failure_plan = service.plan_export(cleanup_failure_destination)
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            export_cleanup_failure = service.apply_portability(
                cleanup_failure_plan["plan"]["plan_id"],
                True,
                expected_operation="export",
                test_fail_stage="after-receipt",
                test_fail_receipt_cleanup=True,
            )
        receipt_root = root / "project/context/continuity-portability-receipts"
        orphan_receipts = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in receipt_root.glob("*.json")
        ]
        export_orphan = next(
            (
                receipt
                for receipt in orphan_receipts
                if receipt.get("plan_id") == cleanup_failure_plan["plan"]["plan_id"]
            ),
            None,
        )
        export_cleanup_listing = service.list_receipts()
        export_failed_plan = json.loads(
            (
                service.plans / f"{cleanup_failure_plan['plan']['plan_id']}.json"
            ).read_text(encoding="utf-8")
        )
        archive_plan = service.plan_archive(["roadmap-history"])
        with patch.dict(os.environ, {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            archive_failure = service.apply_portability(
                archive_plan["plan"]["plan_id"],
                True,
                expected_operation="archive",
                test_fail_stage="after-receipt",
                test_fail_artifact_cleanup=True,
            )
        archive_destination = root / archive_plan["plan"]["destination"]
        cases.extend(
            [
                (
                    "post-publish-failure-removes-false-receipt-and-artifact",
                    export_failure.get("reason_codes")
                    == ["PORTABILITY_APPLY_FAILED_ROLLED_BACK"]
                    and export_failure.get("rollback_verified") is True
                    and export_failure.get("false_receipt_removed") is True
                    and export_failure.get("artifact_removed") is True
                    and not export_destination.exists(),
                ),
                (
                    "export-receipt-cleanup-failure-leaves-only-invalid-provisional-receipt",
                    export_cleanup_failure.get("reason_codes")
                    == ["PORTABILITY_APPLY_ROLLBACK_INCOMPLETE"]
                    and export_cleanup_failure.get("rollback_verified") is False
                    and export_cleanup_failure.get("false_receipt_removed") is False
                    and export_cleanup_failure.get("artifact_removed") is True
                    and not cleanup_failure_destination.exists()
                    and export_orphan is not None
                    and export_orphan.get("status") == "prepared"
                    and export_orphan.get("content_sha256")
                    == receipt_hash(export_orphan)
                    and service.validate_portability_receipt(export_orphan)
                    == ["PORTABILITY_RECEIPT_INVALID"]
                    and not any(
                        receipt.get("plan_id")
                        == cleanup_failure_plan["plan"]["plan_id"]
                        for receipt in export_cleanup_listing.get("receipts", [])
                    )
                    and any(
                        error.get("code") == "PORTABILITY_RECEIPT_INVALID"
                        for error in export_cleanup_listing.get("errors", [])
                    )
                    and export_failed_plan.get("status") == "failed"
                    and export_failed_plan.get("content_sha256")
                    == receipt_hash(export_failed_plan),
                ),
                (
                    "artifact-cleanup-failure-is-distinct-and-not-overclaimed",
                    archive_failure.get("reason_codes")
                    == ["PORTABILITY_APPLY_ROLLBACK_INCOMPLETE"]
                    and archive_failure.get("rollback_verified") is False
                    and archive_failure.get("false_receipt_removed") is True
                    and archive_failure.get("artifact_removed") is False
                    and archive_destination.is_dir(),
                ),
            ]
        )


def scenario_privacy_payload_fixtures(cases: list[tuple[str, bool]]) -> None:
    for mode, expected_code in (
        ("secret", "PORTABILITY_SECRET_DETECTED"),
        ("reasoning", "PORTABILITY_FORBIDDEN_TEXT_PAYLOAD"),
        ("raw-field", "PORTABILITY_FORBIDDEN_TEXT_PAYLOAD"),
    ):
        with tempfile.TemporaryDirectory(
            prefix=f"aos15-w5-privacy-{mode}-"
        ) as temporary:
            root = prepare_fixture(Path(temporary), payload_mode=mode)
            built = ContinuityPortabilityService(root).build_export_manifest()
            cases.append(
                (
                    f"{mode}-payload-is-blocked-before-export-plan",
                    not built.get("ok")
                    and expected_code in built.get("reason_codes", []),
                )
            )


def scenario_privacy_signature_matrix(cases: list[tuple[str, bool]]) -> None:
    privacy_matrix = (
        (b"password=hunter2\n", "notes.md", "PORTABILITY_SECRET_DETECTED"),
        (b"api_key: supersecret\n", "notes.yaml", "PORTABILITY_SECRET_DETECTED"),
        (
            b"access_token=abcdef0123456789\n",
            "notes.txt",
            "PORTABILITY_SECRET_DETECTED",
        ),
        (
            b'{"prompt":"private prompt"}\n',
            "record.json",
            "PORTABILITY_FORBIDDEN_STRUCTURED_PAYLOAD",
        ),
        (
            b'{"reasoning":"private trace"}\n',
            "record.json",
            "PORTABILITY_FORBIDDEN_STRUCTURED_PAYLOAD",
        ),
        (
            b"prompt: private prompt\n",
            "notes.md",
            "PORTABILITY_FORBIDDEN_TEXT_PAYLOAD",
        ),
        (
            b"reasoning: private trace\n",
            "notes.md",
            "PORTABILITY_FORBIDDEN_TEXT_PAYLOAD",
        ),
        (
            b"\x00password=hunter2\xff",
            "opaque.bin",
            "PORTABILITY_SECRET_DETECTED",
        ),
        (
            b"\x00prompt: private prompt\xff",
            "opaque.bin",
            "PORTABILITY_FORBIDDEN_TEXT_PAYLOAD",
        ),
    )

    cases.append(
        (
            "privacy-scanner-blocks-supported-secret-prompt-and-reasoning-signatures",
            all(
                ContinuityPortabilityService.privacy_error(payload, path) == expected
                for payload, path, expected in privacy_matrix
            ),
        )
    )


SCENARIOS = (
    (
        "export-missing-context-source-guard",
        ("missing-context-transitive-source-blocks-export",),
        scenario_export_missing_context_source_guard,
    ),
    (
        "export-and-archive-cleanup-recovery",
        (
            "post-publish-failure-removes-false-receipt-and-artifact",
            "export-receipt-cleanup-failure-leaves-only-invalid-provisional-receipt",
            "artifact-cleanup-failure-is-distinct-and-not-overclaimed",
        ),
        scenario_export_and_archive_cleanup_recovery,
    ),
    (
        "privacy-payload-fixtures",
        (
            "secret-payload-is-blocked-before-export-plan",
            "reasoning-payload-is-blocked-before-export-plan",
            "raw-field-payload-is-blocked-before-export-plan",
        ),
        scenario_privacy_payload_fixtures,
    ),
    (
        "privacy-signature-matrix",
        ("privacy-scanner-blocks-supported-secret-prompt-and-reasoning-signatures",),
        scenario_privacy_signature_matrix,
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
