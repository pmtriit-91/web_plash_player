#!/usr/bin/env python3
"""AOS-15 W5 focused shard: export source and plan guards."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import receipt_hash
from agent_os_continuity_portability import (
    ContinuityPortabilityService,
    artifact_entry_id,
)
from continuity_portability.test_support import (
    create_directory_redirect,
    prepare_fixture,
    rehash_export_inventory,
    remove_directory_redirect,
    write_json,
)

SHARD_ID = "export-source-and-plan-guards"
GROUPS = ("export",)
TIMEOUT_SECONDS = 120


def scenario_export_bundle_source_closure_bounds(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-adversarial-") as temporary:
        root = prepare_fixture(Path(temporary), payload_mode="portable-bytes")
        service = ContinuityPortabilityService(root)
        destination = Path(temporary) / "bundle"
        planned = service.plan_export(destination)
        service.apply_portability(
            planned["plan"]["plan_id"],
            True,
            expected_operation="export",
        )

        omitted = Path(temporary) / "omitted"
        shutil.copytree(destination, omitted)
        omitted_manifest_path = omitted / "continuity-export-manifest.json"
        omitted_manifest = json.loads(omitted_manifest_path.read_text(encoding="utf-8"))
        omitted_entry = next(
            item
            for item in omitted_manifest["entries"]
            if item["present"] and item["restore_mode"] == "replace"
        )
        (omitted / omitted_entry["storage_path"]).unlink()
        omitted_manifest["entries"].remove(omitted_entry)
        rehash_export_inventory(omitted_manifest)
        write_json(omitted_manifest_path, omitted_manifest)
        cases.append(
            (
                "self-consistent-provider-omission-is-rejected",
                "PORTABILITY_SOURCE_CLOSURE_MISMATCH"
                in service.inspect_bundle(omitted).get("reason_codes", []),
            )
        )

        forged_catalog = Path(temporary) / "forged-catalog"
        shutil.copytree(destination, forged_catalog)
        forged_catalog_manifest_path = (
            forged_catalog / "continuity-export-manifest.json"
        )
        forged_catalog_manifest = json.loads(
            forged_catalog_manifest_path.read_text(encoding="utf-8")
        )
        catalog_entry = next(
            item
            for item in forged_catalog_manifest["entries"]
            if item["canonical_path"] == ".agents/project/context/continuity.json"
        )
        old_storage = forged_catalog / catalog_entry["storage_path"]
        forged_catalog_payload = old_storage.read_bytes() + b" "
        old_storage.unlink()
        catalog_entry["bytes"] = len(forged_catalog_payload)
        catalog_entry["sha256"] = hashlib.sha256(forged_catalog_payload).hexdigest()
        catalog_entry["entry_id"] = artifact_entry_id(
            catalog_entry["canonical_path"],
            True,
            catalog_entry["sha256"],
        )
        catalog_entry["storage_path"] = f"files/{catalog_entry['entry_id']}.bin"
        (forged_catalog / catalog_entry["storage_path"]).write_bytes(
            forged_catalog_payload
        )
        forged_catalog_manifest["catalog"]["catalog_sha256"] = catalog_entry["sha256"]
        rehash_export_inventory(forged_catalog_manifest)
        write_json(forged_catalog_manifest_path, forged_catalog_manifest)
        cases.append(
            (
                "self-consistent-forged-catalog-is-rejected",
                bool(
                    {
                        "PORTABILITY_SOURCE_AUTHORITY_MISMATCH",
                        "PORTABILITY_SOURCE_CLOSURE_MISMATCH",
                    }
                    & set(
                        service.inspect_bundle(forged_catalog).get("reason_codes", [])
                    )
                ),
            )
        )

        missing_verify = Path(temporary) / "missing-verify-only"
        shutil.copytree(destination, missing_verify)
        missing_verify_manifest_path = (
            missing_verify / "continuity-export-manifest.json"
        )
        missing_verify_manifest = json.loads(
            missing_verify_manifest_path.read_text(encoding="utf-8")
        )
        verify_entry = next(
            item
            for item in missing_verify_manifest["entries"]
            if item["present"] and item["restore_mode"] == "verify-only"
        )
        (missing_verify / verify_entry["storage_path"]).unlink()
        missing_verify_manifest["entries"].remove(verify_entry)
        rehash_export_inventory(missing_verify_manifest)
        write_json(missing_verify_manifest_path, missing_verify_manifest)
        cases.append(
            (
                "mandatory-verify-only-provider-entry-cannot-be-omitted",
                "PORTABILITY_SOURCE_CLOSURE_MISMATCH"
                in service.inspect_bundle(missing_verify).get("reason_codes", []),
            )
        )

        oversized_manifest = Path(temporary) / "oversized-manifest"
        shutil.copytree(destination, oversized_manifest)
        (oversized_manifest / "continuity-export-manifest.json").write_bytes(
            b"x" * (1024 * 1024 + 1)
        )
        cases.append(
            (
                "oversized-manifest-is-rejected-before-unbounded-read",
                service.inspect_bundle(oversized_manifest).get("reason_codes")
                == ["PORTABILITY_MANIFEST_BOUND_EXCEEDED"],
            )
        )


def scenario_export_plan_and_lock_guards(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-plan-guards-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        destination = Path(temporary) / "bundle"
        planned = service.plan_export(destination)
        plan_path = service.plans / f"{planned['plan']['plan_id']}.json"
        tampered_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        tampered_plan["destination"] = str(Path(temporary) / "redirected")
        tampered_plan["content_sha256"] = receipt_hash(tampered_plan)
        write_json(plan_path, tampered_plan)
        rejected = service.apply_portability(
            planned["plan"]["plan_id"],
            True,
            expected_operation="export",
        )
        cases.append(
            (
                "rehash-cannot-retarget-confirmed-export-plan",
                rejected.get("reason_codes") == ["PORTABILITY_PLAN_INVALID"]
                and not destination.exists()
                and not (Path(temporary) / "redirected").exists(),
            )
        )

        oversized_destination = Path(temporary) / "oversized-plan-bundle"
        oversized_plan = service.plan_export(oversized_destination)
        oversized_plan_path = (
            service.plans / f"{oversized_plan['plan']['plan_id']}.json"
        )
        oversized_plan_path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        oversized_plan_result = service.apply_portability(
            oversized_plan["plan"]["plan_id"],
            True,
            expected_operation="export",
        )
        cases.append(
            (
                "oversized-plan-is-rejected-before-unbounded-read",
                oversized_plan_result.get("reason_codes")
                == ["PORTABILITY_PLAN_NOT_FOUND_OR_TAMPERED"]
                and not oversized_destination.exists(),
            )
        )

        fresh = service.plan_export(destination)
        locks, lock_error = service.acquire_domain_locks()
        try:
            busy = service.apply_portability(
                fresh["plan"]["plan_id"],
                True,
                expected_operation="export",
            )
        finally:
            if locks is not None:
                service.release_domain_locks(locks)
        cases.append(
            (
                "shared-portability-lock-rejects-concurrent-domain-apply",
                lock_error is None
                and busy.get("reason_codes") == ["PORTABILITY_TRANSACTION_BUSY"]
                and not destination.exists(),
            )
        )

        approved = Path(temporary) / "approved"
        redirected_parent = Path(temporary) / "redirected-parent"
        approved.mkdir()
        redirected_parent.mkdir()
        redirected_destination = approved / "bundle"
        symlink_plan = service.plan_export(redirected_destination)
        approved.rmdir()
        approved_redirected = create_directory_redirect(
            approved,
            redirected_parent,
        )
        if approved_redirected:
            symlink_result = service.apply_portability(
                symlink_plan["plan"]["plan_id"],
                True,
                expected_operation="export",
            )
            destination_symlink_guarded = (
                symlink_result.get("reason_codes") == ["PORTABILITY_DESTINATION_DRIFT"]
                and not (redirected_parent / "bundle").exists()
            )
        else:
            destination_symlink_guarded = False
        remove_directory_redirect(approved)
        cases.append(
            (
                "export-parent-symlink-drift-is-rejected-before-publish",
                destination_symlink_guarded,
            )
        )


SCENARIOS = (
    (
        "export-bundle-source-closure-bounds",
        (
            "self-consistent-provider-omission-is-rejected",
            "self-consistent-forged-catalog-is-rejected",
            "mandatory-verify-only-provider-entry-cannot-be-omitted",
            "oversized-manifest-is-rejected-before-unbounded-read",
        ),
        scenario_export_bundle_source_closure_bounds,
    ),
    (
        "export-plan-and-lock-guards",
        (
            "rehash-cannot-retarget-confirmed-export-plan",
            "oversized-plan-is-rejected-before-unbounded-read",
            "shared-portability-lock-rejects-concurrent-domain-apply",
            "export-parent-symlink-drift-is-rejected-before-publish",
        ),
        scenario_export_plan_and_lock_guards,
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
