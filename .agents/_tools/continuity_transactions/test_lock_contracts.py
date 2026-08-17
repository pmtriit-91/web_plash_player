#!/usr/bin/env python3
"""Continuity adoption contracts for the shared transaction lock."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_continuity_transactions import (
    BACKUP_DIR_REL,
    CATALOG_REL,
    PROJECTION_REL,
    TRANSACTION_DIR_REL,
    ContinuityTransactionService,
)
from continuity_transactions.test_support import initialize, make_fixture


def untouched(root: Path) -> bool:
    return bool(
        not (root / CATALOG_REL).exists()
        and not (root / PROJECTION_REL).exists()
        and not (root / BACKUP_DIR_REL).exists()
        and not (root / TRANSACTION_DIR_REL).exists()
    )


def pending_initialize(
    base: Path,
) -> tuple[Path, ContinuityTransactionService, dict[str, Any]]:
    root = make_fixture(base, configured=False)
    service = ContinuityTransactionService(root)
    planned = service.plan_initialize()
    if not planned.get("ok"):
        raise RuntimeError(planned)
    return root, service, planned["plan"]


def case_stable_lock_retained(base: Path) -> bool:
    root = make_fixture(base, configured=False)
    service, _result = initialize(root)
    metadata = json.loads(service.lock_path.read_text(encoding="utf-8"))
    return bool(
        service.lock_path.is_file()
        and metadata.get("format") == "agent-os-transaction-lock-v1"
        and metadata.get("owner") == "continuity-apply"
    )


def case_normal_apply_reacquires(base: Path) -> bool:
    root = make_fixture(base, configured=False)
    service, initialized = initialize(root)
    rollback = service.plan_rollback(initialized["receipt"]["transaction_id"])
    result = service.apply(rollback["plan"]["plan_id"], True)
    return bool(
        result.get("ok")
        and not (root / CATALOG_REL).exists()
        and service.lock_path.is_file()
    )


def case_live_owner_excluded(base: Path) -> bool:
    root, service, plan = pending_initialize(base)
    held = service.acquire_lock()
    try:
        result = service.apply(plan["plan_id"], True)
    finally:
        service.release_lock(held)
    return bool(
        result.get("reason_codes")
        == ["CONTINUITY_TRANSACTION_BUSY", "TRANSACTION_LOCK_BUSY"]
        and untouched(root)
    )


def case_legacy_empty_fails_closed(base: Path) -> bool:
    root, service, plan = pending_initialize(base)
    service.runtime.mkdir(parents=True, exist_ok=True)
    service.lock_path.write_bytes(b"")
    result = service.apply(plan["plan_id"], True)
    return bool(
        result.get("reason_codes") == ["TRANSACTION_LOCK_LEGACY_UNVERIFIED"]
        and untouched(root)
    )


def case_corrupt_metadata_fails_closed(base: Path) -> bool:
    root, service, plan = pending_initialize(base)
    service.runtime.mkdir(parents=True, exist_ok=True)
    service.lock_path.write_text("not-json\n", encoding="utf-8")
    result = service.apply(plan["plan_id"], True)
    return bool(
        result.get("reason_codes") == ["TRANSACTION_LOCK_LEGACY_UNVERIFIED"]
        and untouched(root)
    )


def case_rollback_releases_kernel_lock(base: Path) -> bool:
    root, service, plan = pending_initialize(base)
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        failed = service.apply(plan["plan_id"], True, test_fail_after=1)
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    probe = service.acquire_lock()
    service.release_lock(probe)
    return bool(
        failed.get("reason_codes") == ["CONTINUITY_APPLY_FAILED_ROLLED_BACK"]
        and failed.get("rollback_verified") is True
        and not (root / CATALOG_REL).exists()
        and not (root / PROJECTION_REL).exists()
        and not (root / TRANSACTION_DIR_REL).exists()
        and (root / BACKUP_DIR_REL).is_dir()
        and service.lock_path.is_file()
    )


CASES = [
    ("stable-lock-retained", case_stable_lock_retained),
    ("normal-apply-reacquires", case_normal_apply_reacquires),
    ("live-owner-excluded", case_live_owner_excluded),
    ("legacy-empty-fails-closed", case_legacy_empty_fails_closed),
    ("corrupt-metadata-fails-closed", case_corrupt_metadata_fails_closed),
    ("rollback-releases-kernel-lock", case_rollback_releases_kernel_lock),
]


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="agent-os-continuity-transaction-lock-"
    ) as temporary:
        root = Path(temporary)
        for index, (identifier, check) in enumerate(CASES):
            try:
                passed = bool(check(root / f"{index:02d}-{identifier}"))
                results.append({"id": identifier, "passed": passed})
            except Exception as error:  # noqa: BLE001 - report isolated case failure
                results.append(
                    {
                        "id": identifier,
                        "passed": False,
                        "error": f"{error.__class__.__name__}: {error}",
                    }
                )
    passed = sum(1 for item in results if item["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
