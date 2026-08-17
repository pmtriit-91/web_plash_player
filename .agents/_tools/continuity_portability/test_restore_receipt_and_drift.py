#!/usr/bin/env python3
"""AOS-15 W5 focused shard: restore receipt and drift guards."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash, receipt_hash
from agent_os_continuity_portability import artifact_id
from continuity_portability.test_support import (
    digest,
    export_bundle,
    prepare_fixture,
    rehash_restore_plan,
    write_json,
)

SHARD_ID = "restore-receipt-and-drift"
GROUPS = ("restore",)
TIMEOUT_SECONDS = 120


def scenario_restore_receipt_and_drift(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-restore-") as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        roadmap = root.parent / "docs/roadmap.md"
        roadmap.write_bytes(b"# drifted target\r\n")
        planned = service.plan_restore(destination)
        restored = service.apply_restore(planned["plan"]["plan_id"], True)
        restore_receipt = restored["receipt"]
        backup_index_path = root.parent / restore_receipt["backup"]["index_path"]
        backup_directory = backup_index_path.parent
        backup_index_before = backup_index_path.read_bytes()
        extra_backup = backup_directory / "unexpected.bin"
        extra_backup.write_bytes(b"extra")
        extra_backup_validation = service.validate_restore_receipt(restore_receipt)
        extra_backup.unlink()
        redirected_backup_receipt = deepcopy(restore_receipt)
        redirected_backup_receipt["backup"]["index_path"] = (
            ".agents/project/context/continuity-restore-backups/"
            "continuity-restore-backup-000000000000000000000000/index.json"
        )
        redirected_backup_receipt["receipt_id"] = artifact_id(
            redirected_backup_receipt,
            "continuity-restore-",
            "receipt_id",
        )
        redirected_backup_receipt["content_sha256"] = receipt_hash(
            redirected_backup_receipt
        )
        wrong_binding_index = json.loads(backup_index_before)
        wrong_binding_index["project_id"] = "wrong-project"
        wrong_binding_index["content_sha256"] = receipt_hash(wrong_binding_index)
        write_json(backup_index_path, wrong_binding_index)
        wrong_binding_receipt = deepcopy(restore_receipt)
        wrong_binding_receipt["backup"]["index_sha256"] = digest(backup_index_path)
        wrong_binding_receipt["receipt_id"] = artifact_id(
            wrong_binding_receipt,
            "continuity-restore-",
            "receipt_id",
        )
        wrong_binding_receipt["content_sha256"] = receipt_hash(wrong_binding_receipt)
        wrong_binding_validation = service.validate_restore_receipt(
            wrong_binding_receipt
        )
        backup_index_path.write_bytes(backup_index_before)
        forged_contract_receipt = deepcopy(restore_receipt)
        forged_contract_receipt["binding_sha256"] = "0" * 64
        forged_contract_receipt["receipt_id"] = artifact_id(
            forged_contract_receipt,
            "continuity-restore-",
            "receipt_id",
        )
        forged_contract_receipt["content_sha256"] = receipt_hash(
            forged_contract_receipt
        )
        forged_contract_validation = service.validate_restore_receipt(
            forged_contract_receipt
        )
        foreign_index = json.loads(backup_index_before)
        foreign_index["project_id"] = "foreign-project"
        foreign_index["content_sha256"] = receipt_hash(foreign_index)
        write_json(backup_index_path, foreign_index)
        foreign_receipt = deepcopy(restore_receipt)
        foreign_receipt["project_id"] = "foreign-project"
        foreign_receipt["backup"]["index_sha256"] = digest(backup_index_path)
        foreign_receipt["receipt_id"] = artifact_id(
            foreign_receipt,
            "continuity-restore-",
            "receipt_id",
        )
        foreign_receipt["content_sha256"] = receipt_hash(foreign_receipt)
        foreign_validation = service.validate_restore_receipt(foreign_receipt)
        backup_index_path.write_bytes(backup_index_before)

        action_mismatch = deepcopy(restore_receipt)
        action_target = action_mismatch["targets"][0]
        action_target["action"] = (
            "replace" if action_target["before_sha256"] is None else "create"
        )
        action_mismatch["target_inventory_sha256"] = canonical_hash(
            action_mismatch["targets"]
        )
        action_mismatch["receipt_id"] = artifact_id(
            action_mismatch,
            "continuity-restore-",
            "receipt_id",
        )
        action_mismatch["content_sha256"] = receipt_hash(action_mismatch)
        duplicate_reasons = deepcopy(restore_receipt)
        duplicate_reasons["post_apply"]["reason_codes"] = [
            "CONTINUITY_AUTHORITY_PARTIAL",
            "CONTINUITY_AUTHORITY_PARTIAL",
        ]
        duplicate_reasons["receipt_id"] = artifact_id(
            duplicate_reasons,
            "continuity-restore-",
            "receipt_id",
        )
        duplicate_reasons["content_sha256"] = receipt_hash(duplicate_reasons)
        aggregate_overflow = deepcopy(restore_receipt)
        aggregate_overflow["targets"] = [
            {
                "entry_id": f"continuity-entry-{index:024x}",
                "path": f"docs/aggregate-{index:02d}.md",
                "action": "create",
                "before_sha256": None,
                "after_sha256": f"{index + 1:064x}",
                "bytes": 8388608,
            }
            for index in range(9)
        ]
        aggregate_overflow["target_inventory_sha256"] = canonical_hash(
            aggregate_overflow["targets"]
        )
        aggregate_overflow["receipt_id"] = artifact_id(
            aggregate_overflow,
            "continuity-restore-",
            "receipt_id",
        )
        aggregate_overflow["content_sha256"] = receipt_hash(aggregate_overflow)
        oversized_receipt_path = (
            root / "project/context/continuity-portability-receipts" / "oversized.json"
        )
        oversized_receipt_path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        oversized_receipt_listing = service.list_receipts()
        oversized_receipt_path.unlink()
        cases.extend(
            [
                (
                    "restore-receipt-detects-extra-backup-file",
                    extra_backup_validation
                    == ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"],
                ),
                (
                    "rehash-cannot-redirect-restore-backup",
                    service.validate_restore_receipt(redirected_backup_receipt)
                    == ["PORTABILITY_RESTORE_RECEIPT_INVALID"],
                ),
                (
                    "rehash-cannot-change-restore-backup-project-binding",
                    wrong_binding_validation
                    == ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"],
                ),
                (
                    "restore-receipt-binds-project-and-contracts-to-exact-Git",
                    forged_contract_validation
                    == ["PORTABILITY_RESTORE_RECEIPT_PROVENANCE_UNVERIFIABLE"]
                    and foreign_validation
                    == ["PORTABILITY_RESTORE_RECEIPT_PROVENANCE_UNVERIFIABLE"],
                ),
                (
                    "restore-receipt-enforces-action-reason-and-byte-bounds",
                    service.validate_restore_receipt(action_mismatch)
                    == ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
                    and service.validate_restore_receipt(duplicate_reasons)
                    == ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
                    and service.validate_restore_receipt(aggregate_overflow)
                    == ["PORTABILITY_RESTORE_RECEIPT_INVALID"],
                ),
                (
                    "receipt-listing-rejects-oversized-input-before-read",
                    oversized_receipt_listing.get("ok") is False
                    and oversized_receipt_listing.get("errors")
                    == [{"code": "PORTABILITY_RECEIPT_BOUND_EXCEEDED"}],
                ),
            ]
        )

        roadmap.write_bytes(b"# first drift\n")
        stale = service.plan_restore(destination)
        traversal_plan = deepcopy(stale["plan"])
        traversal_plan["targets"][0]["path"] = "../escape"
        rehash_restore_plan(traversal_plan)
        write_json(
            service.plans / f"{traversal_plan['plan_id']}.json",
            traversal_plan,
        )
        traversal_result = service.apply_restore(traversal_plan["plan_id"], True)
        cases.append(
            (
                "rehashed-restore-target-traversal-fails-closed",
                traversal_result.get("reason_codes")
                == ["PORTABILITY_RESTORE_TARGETS_INVALID"]
                and roadmap.read_bytes() == b"# first drift\n",
            )
        )
        roadmap.write_bytes(b"# second drift\n")
        stale_result = service.apply_restore(stale["plan"]["plan_id"], True)
        cases.append(
            (
                "restore-plan-rejects-target-drift-before-write",
                stale_result.get("reason_codes")
                == ["PORTABILITY_RESTORE_TARGETS_INVALID"]
                and roadmap.read_bytes() == b"# second drift\n",
            )
        )


SCENARIOS = (
    (
        "restore-receipt-and-drift",
        (
            "restore-receipt-detects-extra-backup-file",
            "rehash-cannot-redirect-restore-backup",
            "rehash-cannot-change-restore-backup-project-binding",
            "restore-receipt-binds-project-and-contracts-to-exact-Git",
            "restore-receipt-enforces-action-reason-and-byte-bounds",
            "receipt-listing-rejects-oversized-input-before-read",
            "rehashed-restore-target-traversal-fails-closed",
            "restore-plan-rejects-target-drift-before-write",
        ),
        scenario_restore_receipt_and_drift,
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
