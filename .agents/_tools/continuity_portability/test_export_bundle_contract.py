#!/usr/bin/env python3
"""AOS-15 W5 focused shard: export bundle contract and tamper proof."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash, json_bytes, receipt_hash
from agent_os_continuity_portability import (
    EXPORT_FIELDS,
    ContinuityPortabilityService,
)
from continuity_portability.test_support import prepare_fixture, rehash_manifest

SHARD_ID = "export-bundle-contract"
GROUPS = ("export",)
TIMEOUT_SECONDS = 120


def scenario_export_bundle_contract(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-deterministic-") as temporary:
        root = prepare_fixture(Path(temporary), payload_mode="portable-bytes")
        service = ContinuityPortabilityService(root)
        first = service.build_export_manifest()
        second = service.build_export_manifest()
        destination = Path(temporary) / "bundle"
        planned = service.plan_export(destination)
        no_write_before_apply = not destination.exists()
        denied = service.apply_portability(
            planned["plan"]["plan_id"],
            False,
            expected_operation="export",
        )
        no_write_after_denial = not destination.exists()
        applied = service.apply_portability(
            planned["plan"]["plan_id"],
            True,
            expected_operation="export",
        )
        forged_export_receipt = deepcopy(applied["receipt"])
        forged_export_manifest = forged_export_receipt["artifact_manifest"]
        forged_export_manifest["binding_sha256"] = "0" * 64
        rehash_manifest(forged_export_manifest)
        forged_export_receipt["artifact_id"] = forged_export_manifest["bundle_id"]
        forged_export_receipt["artifact_path"] = (
            f"external-directory/{forged_export_manifest['bundle_id']}"
        )
        forged_export_receipt["manifest_sha256"] = hashlib.sha256(
            json_bytes(forged_export_manifest)
        ).hexdigest()
        forged_export_receipt["binding_sha256"] = "0" * 64
        forged_export_receipt["receipt_id"] = (
            "continuity-portability-"
            + canonical_hash(
                {
                    "plan_id": forged_export_receipt["plan_id"],
                    "operation": "export",
                    "artifact_id": forged_export_receipt["artifact_id"],
                    "applied_at": forged_export_receipt["applied_at"],
                }
            )[:24]
        )
        forged_export_receipt["content_sha256"] = receipt_hash(forged_export_receipt)
        inspected = service.inspect_bundle(destination)
        by_path = {
            item["canonical_path"]: item
            for item in inspected.get("manifest", {}).get("entries", [])
        }
        crlf_entry = by_path["docs/roadmap.md"]
        binary_entry = by_path["docs/context/current-status.md"]
        cases.extend(
            [
                (
                    "export-manifest-is-byte-deterministic-for-identical-state",
                    first.get("ok") is True
                    and second.get("ok") is True
                    and json_bytes(first["manifest"]) == json_bytes(second["manifest"]),
                ),
                (
                    "export-plan-is-reviewable-and-requires-confirmation",
                    no_write_before_apply
                    and denied.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"]
                    and no_write_after_denial,
                ),
                (
                    "export-publishes-strict-self-verifying-bundle",
                    applied.get("ok") is True
                    and inspected.get("ok") is True
                    and inspected.get("integrity_state") == "valid"
                    and inspected.get("authority_state") == "unverified-until-restore"
                    and set(inspected["manifest"]) == EXPORT_FIELDS,
                ),
                (
                    "external-export-receipt-is-provenance-only",
                    applied["receipt"]["artifact_state"] == "external-unverified"
                    and applied["receipt"]["artifact_path"]
                    == f"external-directory/{applied['receipt']['artifact_id']}"
                    and applied["receipt"]["artifact_manifest"]
                    == applied["artifact_manifest"]
                    and service.validate_portability_receipt(applied["receipt"]) == [],
                ),
                (
                    "rehash-cannot-forge-export-receipt-contract-provenance",
                    service.validate_portability_receipt(forged_export_receipt)
                    == ["PORTABILITY_RECEIPT_ARTIFACT_UNVERIFIABLE"],
                ),
                (
                    "CRLF-and-binary-payloads-are-preserved-byte-for-byte",
                    (destination / crlf_entry["storage_path"]).read_bytes()
                    == (root.parent / "docs/roadmap.md").read_bytes()
                    and (destination / binary_entry["storage_path"]).read_bytes()
                    == (root.parent / "docs/context/current-status.md").read_bytes(),
                ),
                (
                    "existing-export-destination-is-never-overwritten",
                    service.plan_export(destination).get("reason_codes")
                    == ["PORTABILITY_DESTINATION_INVALID"],
                ),
            ]
        )

        tampered = Path(temporary) / "tampered"
        shutil.copytree(destination, tampered)
        tampered_manifest = json.loads(
            (tampered / "continuity-export-manifest.json").read_text(encoding="utf-8")
        )
        payload_entry = next(
            item for item in tampered_manifest["entries"] if item["present"]
        )
        (tampered / payload_entry["storage_path"]).write_bytes(b"tampered")
        cases.append(
            (
                "tampered-payload-is-rejected",
                "PORTABILITY_PAYLOAD_TAMPERED"
                in service.inspect_bundle(tampered).get("reason_codes", []),
            )
        )


SCENARIOS = (
    (
        "export-bundle-contract",
        (
            "export-manifest-is-byte-deterministic-for-identical-state",
            "export-plan-is-reviewable-and-requires-confirmation",
            "export-publishes-strict-self-verifying-bundle",
            "external-export-receipt-is-provenance-only",
            "rehash-cannot-forge-export-receipt-contract-provenance",
            "CRLF-and-binary-payloads-are-preserved-byte-for-byte",
            "existing-export-destination-is-never-overwritten",
            "tampered-payload-is-rejected",
        ),
        scenario_export_bundle_contract,
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
