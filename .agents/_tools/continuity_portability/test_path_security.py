#!/usr/bin/env python3
"""AOS-15 W5 test shard: path-security."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity_portability import (
    ARCHIVE_DIR_AGENT_REL,
    ContinuityPortabilityService,
    read_regular_bounded,
)
from continuity_portability.test_support import (
    ReparseStat,
    create_directory_redirect,
    export_bundle,
    prepare_fixture,
    remove_directory_redirect,
)

SHARD_ID = "path-security"
GROUPS = ("path-security",)
TIMEOUT_SECONDS = 120


def scenario_descriptor_bounded_read(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-bounded-read-") as temporary:
        bounded_source = Path(temporary) / "payload.bin"
        bounded_source.write_bytes(b"bounded")
        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("unbounded Path.read_bytes() used"),
        ):
            bounded_payload, bounded_error = read_regular_bounded(
                bounded_source,
                7,
            )
            oversized_payload, oversized_error = read_regular_bounded(
                bounded_source,
                6,
            )
        cases.append(
            (
                "regular-file-read-is-descriptor-bounded",
                bounded_payload == b"bounded"
                and bounded_error is None
                and oversized_payload is None
                and oversized_error == "PORTABILITY_FILE_BOUND_EXCEEDED",
            )
        )


def scenario_runtime_root_symlink_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-runtime-root-symlink-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        redirected = Path(temporary) / "redirected-runtime"
        redirected.mkdir()
        runtime_root = root / "_runtime/continuity-portability"
        runtime_root.parent.mkdir(parents=True, exist_ok=True)
        runtime_redirected = create_directory_redirect(runtime_root, redirected)
        if runtime_redirected:
            rejected = service.plan_export(Path(temporary) / "bundle")
            runtime_root_guarded = rejected.get("reason_codes") == [
                "PORTABILITY_RUNTIME_UNSAFE"
            ] and not any(redirected.iterdir())
        else:
            runtime_root_guarded = False
        remove_directory_redirect(runtime_root)
        cases.append(
            (
                "portability-runtime-root-symlink-is-rejected-before-write",
                runtime_root_guarded,
            )
        )


def scenario_plan_root_symlink_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-plan-root-symlink-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        redirected = Path(temporary) / "redirected-plans"
        redirected.mkdir()
        plan_root = root / "_runtime/continuity-portability/plans"
        plan_root.parent.mkdir(parents=True, exist_ok=True)
        plan_redirected = create_directory_redirect(plan_root, redirected)
        if plan_redirected:
            rejected = service.plan_export(Path(temporary) / "bundle")
            plan_root_guarded = rejected.get("reason_codes") == [
                "PORTABILITY_RUNTIME_UNSAFE"
            ] and not any(redirected.iterdir())
        else:
            plan_root_guarded = False
        remove_directory_redirect(plan_root)
        cases.append(
            (
                "portability-plan-root-symlink-is-rejected-before-write",
                plan_root_guarded,
            )
        )


def scenario_plan_directory_swap_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-plan-root-swap-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        plan_root = service.root / "_runtime/continuity-portability/plans"
        held_root = service.root / "_runtime/continuity-portability/plans-held"
        redirected = Path(temporary) / "redirected-plan-swap"
        redirected.mkdir()
        original_guard = service.verified_owned_directory
        swap_performed = False

        def swap_after_plan_guard(
            relative: str,
            *,
            create: bool = False,
        ) -> Path | None:
            nonlocal swap_performed
            result = original_guard(relative, create=create)
            if (
                not swap_performed
                and relative == "_runtime/continuity-portability/plans"
                and create
                and result == plan_root
            ):
                plan_root.rename(held_root)
                if create_directory_redirect(plan_root, redirected):
                    swap_performed = True
                else:
                    held_root.rename(plan_root)
            return result

        with patch.object(
            service,
            "verified_owned_directory",
            side_effect=swap_after_plan_guard,
        ):
            swapped_plan = service.plan_export(Path(temporary) / "bundle")
        redirected_empty = not any(redirected.iterdir())
        remove_directory_redirect(plan_root)
        cases.append(
            (
                "portability-plan-dir-swap-is-rejected-without-redirected-write",
                swap_performed
                and swapped_plan.get("reason_codes") == ["PORTABILITY_RUNTIME_UNSAFE"]
                and redirected_empty
                and not list(held_root.glob("*.json")),
            )
        )


def scenario_staging_root_symlink_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-staging-root-symlink-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        redirected = Path(temporary) / "redirected-staging"
        redirected.mkdir()
        staging_root = root / "_runtime/continuity-portability/staging"
        staging_redirected = create_directory_redirect(staging_root, redirected)
        if staging_redirected:
            rejected = service.plan_restore(destination)
            staging_root_guarded = rejected.get("reason_codes") == [
                "PORTABILITY_RUNTIME_UNSAFE"
            ] and not any(redirected.iterdir())
        else:
            staging_root_guarded = False
        remove_directory_redirect(staging_root)
        cases.append(
            (
                "portability-staging-root-symlink-is-rejected-before-copy",
                staging_root_guarded,
            )
        )


def scenario_shared_lock_root_symlink_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-lock-root-symlink-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        destination = Path(temporary) / "bundle"
        planned = service.plan_export(destination)
        lock_root = root / "_runtime/context-memory"
        if lock_root.exists() and not lock_root.is_symlink():
            shutil.rmtree(lock_root)
        redirected = Path(temporary) / "redirected-locks"
        redirected.mkdir()
        lock_redirected = create_directory_redirect(lock_root, redirected)
        if lock_redirected:
            rejected = service.apply_portability(
                planned["plan"]["plan_id"],
                True,
                expected_operation="export",
            )
            lock_root_guarded = (
                rejected.get("reason_codes") == ["PORTABILITY_RUNTIME_UNSAFE"]
                and not any(redirected.iterdir())
                and not service.portability_lock.exists()
            )
        else:
            lock_root_guarded = False
        remove_directory_redirect(lock_root)
        cases.append(
            (
                "shared-lock-root-symlink-is-rejected-before-lock-write",
                lock_root_guarded,
            )
        )


def scenario_archive_root_symlink_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-archive-root-symlink-"
    ) as temporary:
        root = prepare_fixture(Path(temporary), historical=True)
        service = ContinuityPortabilityService(root)
        planned = service.plan_archive(["roadmap-history"])
        archive_root = root / ARCHIVE_DIR_AGENT_REL
        archive_root.parent.mkdir(parents=True, exist_ok=True)
        redirected = Path(temporary) / "redirected-archives"
        redirected.mkdir()
        archive_redirected = create_directory_redirect(archive_root, redirected)
        if archive_redirected:
            rejected = service.apply_portability(
                planned["plan"]["plan_id"],
                True,
                expected_operation="archive",
            )
            archive_root_guarded = rejected.get("reason_codes") == [
                "PORTABILITY_ARCHIVE_ROOT_UNSAFE"
            ] and not any(redirected.iterdir())
        else:
            archive_root_guarded = False
        remove_directory_redirect(archive_root)
        cases.append(
            (
                "archive-root-symlink-is-rejected-before-publish",
                archive_root_guarded,
            )
        )


def scenario_receipt_root_symlink_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-receipt-root-symlink-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        destination = Path(temporary) / "bundle"
        planned = service.plan_export(destination)
        receipt_root = service.root / "project/context/continuity-portability-receipts"
        receipt_root.parent.mkdir(parents=True, exist_ok=True)
        redirected = Path(temporary) / "redirected-receipts"
        redirected.mkdir()
        receipt_redirected = create_directory_redirect(receipt_root, redirected)
        if receipt_redirected:
            rejected = service.apply_portability(
                planned["plan"]["plan_id"],
                True,
                expected_operation="export",
            )
            receipt_root_guarded = (
                rejected.get("reason_codes")
                == ["PORTABILITY_RECOVERY_DIRECTORY_INVALID"]
                and not destination.exists()
                and not any(redirected.iterdir())
            )
        else:
            receipt_root_guarded = False
        remove_directory_redirect(receipt_root)
        cases.append(
            (
                "receipt-root-symlink-is-rejected-before-publish",
                receipt_root_guarded,
            )
        )


def scenario_receipt_root_reparse_guard(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(
        prefix="aos15-w5-receipt-root-reparse-"
    ) as temporary:
        root = prepare_fixture(Path(temporary))
        service, _applied = export_bundle(
            root,
            Path(temporary) / "bundle",
        )
        receipt_root = service.root / "project/context/continuity-portability-receipts"
        original_lstat = Path.lstat

        def modeled_receipt_reparse(path: Path) -> os.stat_result | ReparseStat:
            details = original_lstat(path)
            if Path(path) == receipt_root:
                return ReparseStat(details)
            return details

        with patch.object(Path, "lstat", modeled_receipt_reparse):
            reparse_listing = service.list_receipts()
        cases.append(
            (
                "receipt-listing-rejects-modeled-windows-reparse-root",
                reparse_listing.get("ok") is False
                and reparse_listing.get("receipts") == []
                and reparse_listing.get("errors")
                == [{"code": "PORTABILITY_RECEIPT_DIRECTORY_INVALID"}],
            )
        )


SCENARIOS = (
    (
        "descriptor-bounded-read",
        ("regular-file-read-is-descriptor-bounded",),
        scenario_descriptor_bounded_read,
    ),
    (
        "runtime-root-symlink-guard",
        ("portability-runtime-root-symlink-is-rejected-before-write",),
        scenario_runtime_root_symlink_guard,
    ),
    (
        "plan-root-symlink-guard",
        ("portability-plan-root-symlink-is-rejected-before-write",),
        scenario_plan_root_symlink_guard,
    ),
    (
        "plan-directory-swap-guard",
        ("portability-plan-dir-swap-is-rejected-without-redirected-write",),
        scenario_plan_directory_swap_guard,
    ),
    (
        "staging-root-symlink-guard",
        ("portability-staging-root-symlink-is-rejected-before-copy",),
        scenario_staging_root_symlink_guard,
    ),
    (
        "shared-lock-root-symlink-guard",
        ("shared-lock-root-symlink-is-rejected-before-lock-write",),
        scenario_shared_lock_root_symlink_guard,
    ),
    (
        "archive-root-symlink-guard",
        ("archive-root-symlink-is-rejected-before-publish",),
        scenario_archive_root_symlink_guard,
    ),
    (
        "receipt-root-symlink-guard",
        ("receipt-root-symlink-is-rejected-before-publish",),
        scenario_receipt_root_symlink_guard,
    ),
    (
        "receipt-root-reparse-guard",
        ("receipt-listing-rejects-modeled-windows-reparse-root",),
        scenario_receipt_root_reparse_guard,
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
