#!/usr/bin/env python3
"""AOS-15 W5 focused shard: retention archive and schema parity."""

from __future__ import annotations

import json
import shutil
import subprocess
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
    ARCHIVE_DIR_AGENT_REL,
    ARCHIVE_FIELDS,
    EXPORT_FIELDS,
    POLICY_FIELDS,
    PORTABILITY_PLAN_FIELDS,
    PORTABILITY_RECEIPT_FIELDS,
    RESTORE_BACKUP_FIELDS,
    RESTORE_PLAN_FIELDS,
    RESTORE_RECEIPT_FIELDS,
    ContinuityPortabilityService,
    artifact_id,
)
from continuity_portability.test_support import (
    SOURCE_ROOT,
    initialize_w4,
    prepare_fixture,
    write_json,
)

SHARD_ID = "retention-archive"
GROUPS = ("retention-archive",)
TIMEOUT_SECONDS = 120


def scenario_archive_lifecycle_and_provenance(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-archive-") as temporary:
        root = prepare_fixture(Path(temporary), historical=True)
        service = ContinuityPortabilityService(root)
        source = root.parent / "docs/roadmap-history.md"
        source_before = source.read_bytes()
        candidate = next(
            item
            for item in service.inspect_retention()["candidates"]
            if item["reference_id"] == "roadmap-history"
        )
        planned = service.plan_archive(["roadmap-history"])
        denied = service.apply_portability(
            planned["plan"]["plan_id"],
            False,
            expected_operation="archive",
        )
        applied = service.apply_portability(
            planned["plan"]["plan_id"],
            True,
            expected_operation="archive",
        )
        archive_manifest, archive_receipt = require_archive_apply(applied)
        archive_path = (
            root
            / "project/context/continuity-archives"
            / archive_manifest.get("archive_id", "missing")
        )
        cases.extend(
            [
                (
                    "critical-history-with-active-successor-is-archive-eligible",
                    candidate["archive_eligible"] is True
                    and candidate["successor_reference_ids"] == ["roadmap"]
                    and not candidate["hold_reasons"],
                ),
                (
                    "archive-requires-confirmation-and-preserves-original",
                    denied.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"]
                    and applied.get("ok") is True
                    and source.read_bytes() == source_before
                    and archive_manifest.get("source_deleted") is False,
                ),
                (
                    "archive-manifest-summary-and-storage-are-deterministic",
                    set(archive_manifest) == ARCHIVE_FIELDS
                    and archive_manifest["summary"]["inventory_sha256"]
                    == archive_manifest["inventory_sha256"]
                    and archive_manifest["summary"]["source_deleted"] is False
                    and (archive_path / "continuity-archive-manifest.json").is_file()
                    and service.validate_archive_manifest(archive_manifest) == []
                    and modeled_windows_fixture_json_is_canonical(),
                ),
            ]
        )
        archive_payload = next(
            archive_path / entry["storage_path"]
            for entry in archive_manifest["entries"]
        )
        archive_payload_before = archive_payload.read_bytes()
        receipt_listing = service.list_receipts()
        archive_payload.write_bytes(b"tampered archive payload")
        tampered_listing = service.list_receipts()
        archive_payload.write_bytes(archive_payload_before)
        redirected_receipt = deepcopy(archive_receipt)
        redirected_receipt["artifact_path"] = (
            f".agents/{ARCHIVE_DIR_AGENT_REL}/redirected"
        )
        redirected_receipt["content_sha256"] = receipt_hash(redirected_receipt)
        forged_archive = Path(temporary) / "forged-archive"
        shutil.copytree(archive_path, forged_archive)
        forged_manifest_path = forged_archive / "continuity-archive-manifest.json"
        forged_manifest = json.loads(forged_manifest_path.read_text(encoding="utf-8"))
        forged_manifest["catalog_sha256"] = "0" * 64
        forged_manifest["archive_id"] = artifact_id(
            forged_manifest,
            "continuity-archive-",
            "archive_id",
        )
        forged_manifest["content_sha256"] = receipt_hash(forged_manifest)
        write_json(forged_manifest_path, forged_manifest)
        forged_archive_result = service.inspect_archive(forged_archive)
        cases.extend(
            [
                (
                    "archive-receipt-reopens-durable-artifact",
                    archive_receipt["artifact_state"] == "durable-verified"
                    and receipt_listing.get("ok") is True
                    and service.validate_portability_receipt(archive_receipt) == [],
                ),
                (
                    "archive-receipt-detects-payload-loss-or-tamper",
                    tampered_listing.get("ok") is False
                    and any(
                        item.get("code") == "PORTABILITY_RECEIPT_ARTIFACT_UNVERIFIABLE"
                        for item in tampered_listing.get("errors", [])
                    ),
                ),
                (
                    "rehash-cannot-redirect-durable-archive-receipt",
                    service.validate_portability_receipt(redirected_receipt)
                    == ["PORTABILITY_RECEIPT_INVALID"],
                ),
                (
                    "rehash-cannot-forge-archive-git-catalog-provenance",
                    forged_archive_result.get("ok") is False
                    and "RETENTION_ARCHIVE_GIT_AUTHORITY_MISMATCH"
                    in forged_archive_result.get("reason_codes", []),
                ),
            ]
        )


def require_archive_apply(
    result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = result.get("artifact_manifest")
    receipt = result.get("receipt")
    if (
        result.get("ok") is not True
        or not isinstance(manifest, dict)
        or not isinstance(receipt, dict)
    ):
        reason_codes = result.get("reason_codes")
        bounded_reasons = (
            ",".join(str(item) for item in reason_codes[:8])
            if isinstance(reason_codes, list)
            else "PORTABILITY_ARCHIVE_APPLY_RESULT_INVALID"
        )
        bounded_error = str(result.get("error", ""))[:480]
        detail = f"; {bounded_error}" if bounded_error else ""
        raise RuntimeError(f"archive apply failed closed: {bounded_reasons}{detail}")
    return manifest, receipt


def modeled_windows_fixture_json_is_canonical() -> bool:
    document = {"schema_version": 1, "project_id": "windows-newline-model"}
    with tempfile.TemporaryDirectory(prefix="aos15-p3b14-newline-") as temporary:
        path = Path(temporary) / "fixture.json"
        with patch.object(
            Path,
            "write_text",
            side_effect=AssertionError("fixture JSON must not use host text newlines"),
        ):
            initialize_w4().write_json(path, document)
        content = path.read_bytes()
        try:
            require_archive_apply(
                {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PUBLISH_FAILED"],
                    "error": "RETENTION_ARCHIVE_GIT_AUTHORITY_MISMATCH",
                }
            )
        except RuntimeError as error:
            fail_closed = "PORTABILITY_PUBLISH_FAILED" in str(
                error
            ) and "RETENTION_ARCHIVE_GIT_AUTHORITY_MISMATCH" in str(error)
        else:
            fail_closed = False
        return content == json_bytes(document) and b"\r" not in content and fail_closed


def scenario_schema_runtime_field_parity(cases: list[tuple[str, bool]]) -> None:
    policy_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-retention-policy.schema.json"
        ).read_text(encoding="utf-8")
    )

    export_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-export-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )

    archive_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-archive-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )

    portability_plan_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-portability-plan.schema.json"
        ).read_text(encoding="utf-8")
    )

    portability_receipt_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-portability-receipt.schema.json"
        ).read_text(encoding="utf-8")
    )

    restore_plan_schema = json.loads(
        (SOURCE_ROOT / "core/contracts/continuity-restore-plan.schema.json").read_text(
            encoding="utf-8"
        )
    )

    restore_receipt_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-restore-receipt.schema.json"
        ).read_text(encoding="utf-8")
    )

    restore_backup_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-restore-backup-index.schema.json"
        ).read_text(encoding="utf-8")
    )

    export_entry_schema = export_schema["$defs"]["entry"]

    archive_summary_schema = archive_schema["properties"]["summary"]

    cases.append(
        (
            "W5-schema-runtime-field-parity",
            set(policy_schema["required"]) == POLICY_FIELDS
            and set(export_schema["required"]) == EXPORT_FIELDS
            and set(archive_schema["required"]) == ARCHIVE_FIELDS
            and set(portability_plan_schema["required"]) == PORTABILITY_PLAN_FIELDS
            and set(portability_receipt_schema["required"])
            == PORTABILITY_RECEIPT_FIELDS
            and set(restore_plan_schema["required"]) == RESTORE_PLAN_FIELDS
            and set(restore_receipt_schema["required"]) == RESTORE_RECEIPT_FIELDS
            and set(restore_backup_schema["required"]) == RESTORE_BACKUP_FIELDS
            and set(export_entry_schema["required"])
            == {
                "entry_id",
                "canonical_path",
                "storage_path",
                "canonical_owner",
                "restore_mode",
                "present",
                "bytes",
                "sha256",
                "privacy_class",
                "retention_class",
                "reference_ids",
            }
            and export_entry_schema["properties"]["privacy_class"]["enum"]
            == ["public-metadata", "project-internal"]
            and bool(export_entry_schema.get("allOf"))
            and set(archive_summary_schema["required"])
            == {
                "reference_count",
                "entry_count",
                "total_bytes",
                "retention_classes",
                "predecessors",
                "successors",
                "holds",
                "inventory_sha256",
                "source_deleted",
            }
            and archive_schema["properties"]["reference_ids"]["maxItems"] == 2048
            and archive_schema["properties"]["entries"]["maxItems"] == 2048
            and archive_schema["properties"]["entry_count"]["maximum"] == 2048
            and archive_summary_schema["properties"]["reference_count"]["maximum"]
            == 2048
            and len(portability_plan_schema.get("allOf", [])) == 2
            and len(portability_receipt_schema.get("allOf", [])) == 2
            and "artifact_manifest" in portability_receipt_schema["properties"]
            and restore_plan_schema["properties"]["targets"]["maxItems"] == 2048
            and restore_plan_schema["properties"]["exact_diff"]["maxLength"] == 1048576
            and restore_backup_schema["properties"]["files"]["maxItems"] == 2048
            and restore_backup_schema["properties"]["files"]["items"]["properties"][
                "bytes"
            ]["maximum"]
            == 8388608,
        )
    )


SCENARIOS = (
    (
        "archive-lifecycle-and-provenance",
        (
            "critical-history-with-active-successor-is-archive-eligible",
            "archive-requires-confirmation-and-preserves-original",
            "archive-manifest-summary-and-storage-are-deterministic",
            "archive-receipt-reopens-durable-artifact",
            "archive-receipt-detects-payload-loss-or-tamper",
            "rehash-cannot-redirect-durable-archive-receipt",
            "rehash-cannot-forge-archive-git-catalog-provenance",
        ),
        scenario_archive_lifecycle_and_provenance,
    ),
    (
        "schema-runtime-field-parity",
        ("W5-schema-runtime-field-parity",),
        scenario_schema_runtime_field_parity,
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
