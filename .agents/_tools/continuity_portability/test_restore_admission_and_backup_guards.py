#!/usr/bin/env python3
"""AOS-15 W5 focused shard: restore admission and backup guards."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import receipt_hash
from agent_os_continuity_portability import (
    RESTORE_BACKUP_DIR_AGENT_REL,
    ContinuityPortabilityService,
)
from continuity_portability.test_support import (
    ReparseStat,
    create_directory_redirect,
    export_bundle,
    prepare_fixture,
    rehash_manifest,
    remove_directory_redirect,
    write_json,
)

SHARD_ID = "restore-admission-and-backup-guards"
GROUPS = ("restore",)
TIMEOUT_SECONDS = 180


def scenario_restore_project_and_core_admission(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-c23-") as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        foreign = Path(temporary) / "foreign"
        shutil.copytree(destination, foreign)
        foreign_path = foreign / "continuity-export-manifest.json"
        foreign_manifest = json.loads(foreign_path.read_text(encoding="utf-8"))
        foreign_manifest["project_id"] = "foreign-project"
        rehash_manifest(foreign_manifest)
        write_json(foreign_path, foreign_manifest)
        inspected = service.inspect_bundle(foreign)
        restore = service.plan_restore(foreign)
        cases.append(
            (
                "C23-self-consistent-wrong-project-bundle-rejected-before-write",
                inspected.get("ok") is False
                and restore.get("reason_codes")
                == ["PORTABILITY_SOURCE_AUTHORITY_MISMATCH"]
                and not service.staging.joinpath(
                    foreign_manifest["bundle_id"]
                ).exists(),
            )
        )

        core_escalation = Path(temporary) / "core-escalation"
        shutil.copytree(destination, core_escalation)
        core_path = core_escalation / "continuity-export-manifest.json"
        core_manifest = json.loads(core_path.read_text(encoding="utf-8"))
        core_entry = next(
            item
            for item in core_manifest["entries"]
            if item["canonical_owner"] == "core"
        )
        core_entry["restore_mode"] = "replace"
        rehash_manifest(core_manifest)
        write_json(core_path, core_manifest)
        cases.append(
            (
                "bundle-cannot-self-authorize-Core-overwrite",
                "PORTABILITY_MANIFEST_ENTRY_INVALID"
                in service.inspect_bundle(core_escalation).get("reason_codes", []),
            )
        )


def scenario_restore_backup_root_symlink_guard(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-backup-root-symlink-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        roadmap = root.parent / "docs/roadmap.md"
        roadmap.write_bytes(b"# drift before unsafe backup root\n")
        before = roadmap.read_bytes()
        planned = service.plan_restore(destination)
        backup_root = root / RESTORE_BACKUP_DIR_AGENT_REL
        redirected = Path(temporary) / "redirected-backups"
        redirected.mkdir()
        backup_redirected = create_directory_redirect(backup_root, redirected)
        if backup_redirected:
            rejected = service.apply_restore(planned["plan"]["plan_id"], True)
            backup_root_guarded = (
                rejected.get("reason_codes")
                == ["PORTABILITY_RESTORE_BACKUP_ROOT_INVALID"]
                and roadmap.read_bytes() == before
                and not any(redirected.iterdir())
            )
        else:
            backup_root_guarded = False
        remove_directory_redirect(backup_root)
        cases.append(
            (
                "restore-backup-root-symlink-swap-is-rejected-before-write",
                backup_root_guarded,
            )
        )


def scenario_restore_backup_parent_reparse_guard(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-backup-parent-reparse-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        context_parent = service.root / "project/context"
        backup_root = service.root / RESTORE_BACKUP_DIR_AGENT_REL
        original_lstat = Path.lstat

        def modeled_parent_reparse(path: Path) -> os.stat_result | ReparseStat:
            details = original_lstat(path)
            if Path(path) == context_parent:
                return ReparseStat(details)
            return details

        with patch.object(Path, "lstat", modeled_parent_reparse):
            guarded_backup_root = service.verified_restore_backup_root(create=True)
        cases.append(
            (
                "restore-backup-parent-reparse-is-rejected-before-child-creation",
                guarded_backup_root is None and not backup_root.exists(),
            )
        )


def scenario_restore_target_parent_swap_guard(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-restore-parent-swap-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        docs_root = root.parent / "docs"
        held_docs = root.parent / "docs-held"
        redirected_docs = Path(temporary) / "redirected-docs"
        redirected_docs.mkdir()
        roadmap = docs_root / "roadmap.md"
        roadmap.write_bytes(b"# drift before parent swap\n")
        drifted_bytes = roadmap.read_bytes()
        planned = service.plan_restore(destination)
        original_backup = service.create_restore_backup
        swap_performed = False

        def swap_after_backup(
            plan: dict[str, Any],
        ) -> tuple[dict[str, Any] | None, list[str]]:
            nonlocal swap_performed
            result = original_backup(plan)
            if result[0] is not None:
                docs_root.rename(held_docs)
                if create_directory_redirect(docs_root, redirected_docs):
                    swap_performed = True
                else:
                    held_docs.rename(docs_root)
            return result

        with patch.object(
            service,
            "create_restore_backup",
            side_effect=swap_after_backup,
        ):
            swapped_restore = service.apply_restore(
                planned["plan"]["plan_id"],
                True,
            )
        redirected_empty = not any(redirected_docs.iterdir())
        held_bytes = (held_docs / "roadmap.md").read_bytes()
        remove_directory_redirect(docs_root)
        if held_docs.exists() and not docs_root.exists():
            held_docs.rename(docs_root)
        swapped_failed_plan = json.loads(
            (service.plans / f"{planned['plan']['plan_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        cases.append(
            (
                "restore-target-parent-swap-is-rejected-without-external-write",
                swap_performed
                and swapped_restore.get("ok") is False
                and swapped_restore.get("reason_codes")
                == ["PORTABILITY_RESTORE_ROLLBACK_INCOMPLETE"]
                and swapped_restore.get("writes_started") is False
                and redirected_empty
                and held_bytes == drifted_bytes
                and swapped_failed_plan.get("status") == "failed"
                and swapped_failed_plan.get("content_sha256")
                == receipt_hash(swapped_failed_plan),
            )
        )


def scenario_restore_apply_and_backup_guards(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-restore-") as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        roadmap = root.parent / "docs/roadmap.md"
        original = roadmap.read_bytes()
        roadmap.write_bytes(b"# drifted target\r\n")
        absent_genesis = root / "project/genesis.json"
        absent_genesis.write_bytes(b'{"unexpected":"must-not-be-deleted"}\n')
        planned = service.plan_restore(destination)
        no_delete_for_absent_entry = all(
            target["path"] != ".agents/project/genesis.json"
            for target in planned["plan"]["targets"]
        )
        absent_genesis.unlink()
        restored = service.apply_restore(planned["plan"]["plan_id"], True)
        receipt_listing = service.list_receipts()
        cases.append(
            (
                "restore-replaces-only-provider-authorized-application-targets",
                planned.get("ok") is True
                and no_delete_for_absent_entry
                and all(
                    target["path"].startswith(
                        ("docs/", ".agents/project/", ".agents/skills/project-")
                    )
                    for target in planned["plan"]["targets"]
                )
                and restored.get("ok") is True
                and roadmap.read_bytes() == original
                and restored["receipt"]["core_overwritten"] is False
                and receipt_listing.get("ok") is True
                and len(receipt_listing.get("receipts", [])) == 2,
            )
        )
        restore_receipt = restored["receipt"]
        backup_index_path = root.parent / restore_receipt["backup"]["index_path"]
        backup_directory = backup_index_path.parent
        backup_index = json.loads(backup_index_path.read_text(encoding="utf-8"))
        present_backup = next(item for item in backup_index["files"] if item["present"])
        backup_payload_path = backup_directory / present_backup["storage_path"]
        backup_payload_before = backup_payload_path.read_bytes()
        cases.append(
            (
                "successful-restore-keeps-durable-rollback-ready-backup",
                restore_receipt["rollback_ready"] is True
                and restore_receipt["backup"]["index_path"].startswith(
                    f".agents/{RESTORE_BACKUP_DIR_AGENT_REL}/"
                )
                and service.validate_restore_receipt(restore_receipt) == []
                and backup_index_path.is_file(),
            )
        )

        backup_payload_path.write_bytes(b"tampered backup")
        tampered_backup_validation = service.validate_restore_receipt(restore_receipt)
        backup_payload_path.write_bytes(backup_payload_before)
        backup_payload_path.unlink()
        missing_backup_validation = service.validate_restore_receipt(restore_receipt)
        backup_payload_path.write_bytes(backup_payload_before)
        cases.append(
            (
                "restore-receipt-detects-tampered-or-missing-backup-payload",
                tampered_backup_validation
                == ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
                and missing_backup_validation
                == ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"],
            )
        )


# fmt: off
SCENARIOS = (
    ("restore-project-and-core-admission", ("C23-self-consistent-wrong-project-bundle-rejected-before-write", "bundle-cannot-self-authorize-Core-overwrite"), scenario_restore_project_and_core_admission),
    ("restore-backup-root-symlink-guard", ("restore-backup-root-symlink-swap-is-rejected-before-write",), scenario_restore_backup_root_symlink_guard),
    ("restore-backup-parent-reparse-guard", ("restore-backup-parent-reparse-is-rejected-before-child-creation",), scenario_restore_backup_parent_reparse_guard),
    ("restore-target-parent-swap-guard", ("restore-target-parent-swap-is-rejected-without-external-write",), scenario_restore_target_parent_swap_guard),
    ("restore-apply-and-backup-guards", ("restore-replaces-only-provider-authorized-application-targets", "successful-restore-keeps-durable-rollback-ready-backup", "restore-receipt-detects-tampered-or-missing-backup-payload"), scenario_restore_apply_and_backup_guards),
)
# fmt: on


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
