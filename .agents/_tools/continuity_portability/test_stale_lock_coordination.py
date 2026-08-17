#!/usr/bin/env python3
"""Focused proof for Portability's three-domain kernel-lock coordination."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import agent_os_continuity_portability as portability
from agent_os_transaction_lock import (
    TransactionLockHandle,
    acquire_transaction_lock,
    release_transaction_lock,
)
from continuity_portability.test_support import prepare_fixture

LOCK_SPECS = (
    ("_runtime/continuity-portability/apply.lock", "continuity-portability-apply"),
    ("_runtime/context-memory/apply.lock", "context-memory-apply"),
    ("_runtime/continuity/apply.lock", "continuity-apply"),
)


def lock_service(base: Path) -> portability.ContinuityPortabilityService:
    root = base / ".agents"
    root.mkdir(parents=True)
    return portability.ContinuityPortabilityService(root)


def case_fixed_acquire_reverse_release(base: Path) -> bool:
    service = lock_service(base)
    acquired_calls: list[tuple[Path, str]] = []
    released_calls: list[Path] = []

    def fake_acquire(path: Path, owner: str) -> TransactionLockHandle:
        acquired_calls.append((path, owner))
        return TransactionLockHandle(len(acquired_calls), path, "test")

    def fake_release(handle: TransactionLockHandle) -> None:
        released_calls.append(handle.path)

    with (
        patch.object(portability, "acquire_transaction_lock", side_effect=fake_acquire),
        patch.object(portability, "release_transaction_lock", side_effect=fake_release),
    ):
        handles, error = service.acquire_domain_locks()
        if handles is not None:
            service.release_domain_locks(handles)
    expected_paths = [service.root / relative for relative, _owner in LOCK_SPECS]
    return bool(
        error is None
        and [item[0] for item in acquired_calls] == expected_paths
        and [item[1] for item in acquired_calls]
        == [owner for _relative, owner in LOCK_SPECS]
        and released_calls == list(reversed(expected_paths))
    )


def case_stable_metadata_and_reacquire(base: Path) -> bool:
    service = lock_service(base)
    first, first_error = service.acquire_domain_locks()
    if first is None:
        return False
    service.release_domain_locks(first)
    metadata = [
        json.loads((service.root / relative).read_text(encoding="utf-8"))
        for relative, _owner in LOCK_SPECS
    ]
    second, second_error = service.acquire_domain_locks()
    if second is not None:
        service.release_domain_locks(second)
    return bool(
        first_error is None
        and second is not None
        and second_error is None
        and [item.get("owner") for item in metadata]
        == [owner for _relative, owner in LOCK_SPECS]
        and all(
            item.get("format") == "agent-os-transaction-lock-v1" for item in metadata
        )
        and all((service.root / relative).is_file() for relative, _owner in LOCK_SPECS)
    )


def live_owner_case(base: Path, held_index: int) -> bool:
    service = lock_service(base)
    relative, owner = LOCK_SPECS[held_index]
    held_path = service.root / relative
    held_path.parent.mkdir(parents=True, exist_ok=True)
    held = acquire_transaction_lock(held_path, owner)
    try:
        blocked, error = service.acquire_domain_locks()
    finally:
        release_transaction_lock(held)
    probe, probe_error = service.acquire_domain_locks()
    if probe is not None:
        service.release_domain_locks(probe)
    return bool(
        blocked is None
        and error == "PORTABILITY_TRANSACTION_BUSY"
        and probe is not None
        and probe_error is None
    )


def case_live_middle_releases_prior(base: Path) -> bool:
    return live_owner_case(base, 1)


def case_live_last_releases_prior(base: Path) -> bool:
    return live_owner_case(base, 2)


def case_legacy_empty_and_corrupt_fail_closed(base: Path) -> bool:
    outcomes: list[bool] = []
    for name, content in (("empty", b""), ("corrupt", b"not-json\n")):
        service = lock_service(base / name)
        legacy = service.context_lock
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(content)
        handles, error = service.acquire_domain_locks()
        probe = acquire_transaction_lock(service.portability_lock, "probe")
        release_transaction_lock(probe)
        outcomes.append(
            handles is None
            and error == "TRANSACTION_LOCK_LEGACY_UNVERIFIED"
            and service.portability_lock.is_file()
        )
    return all(outcomes)


def case_link_like_lock_fails_closed(base: Path) -> bool:
    service = lock_service(base)
    outside = base / "outside.lock"
    outside.write_text("outside\n", encoding="utf-8")
    service.context_lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        service.context_lock.symlink_to(outside)
    except OSError:
        return False
    handles, error = service.acquire_domain_locks()
    probe = acquire_transaction_lock(service.portability_lock, "probe")
    release_transaction_lock(probe)
    return bool(
        handles is None
        and error == "PORTABILITY_RUNTIME_UNSAFE"
        and outside.read_text(encoding="utf-8") == "outside\n"
    )


def case_crash_releases_all_without_false_receipt(base: Path) -> bool:
    root = prepare_fixture(base)
    service = portability.ContinuityPortabilityService(root)
    destination = base / "crash-bundle"
    planned = service.plan_export(destination)
    plan_id = planned["plan"]["plan_id"]
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from agent_os_continuity_portability import ContinuityPortabilityService\n"
        "service = ContinuityPortabilityService(Path(sys.argv[1]))\n"
        "service.policy = lambda: os._exit(23)\n"
        "service.apply_portability(sys.argv[2], True, expected_operation='export')\n"
        "raise SystemExit(91)\n"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(TOOLS_DIR)
    child = subprocess.run(
        [sys.executable, "-c", script, str(root), plan_id],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=environment,
    )
    probe, probe_error = service.acquire_domain_locks()
    if probe is not None:
        service.release_domain_locks(probe)
    receipts = root / "project/context/continuity-portability-receipts"
    return bool(
        child.returncode == 23
        and probe is not None
        and probe_error is None
        and not destination.exists()
        and (not receipts.exists() or not list(receipts.iterdir()))
    )


CASES = (
    ("fixed-acquire-reverse-release", case_fixed_acquire_reverse_release),
    ("stable-metadata-and-reacquire", case_stable_metadata_and_reacquire),
    ("live-middle-releases-prior", case_live_middle_releases_prior),
    ("live-last-releases-prior", case_live_last_releases_prior),
    ("legacy-empty-and-corrupt-fail-closed", case_legacy_empty_and_corrupt_fail_closed),
    ("link-like-lock-fails-closed", case_link_like_lock_fails_closed),
    (
        "crash-releases-all-without-false-receipt",
        case_crash_releases_all_without_false_receipt,
    ),
)


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="aos15-p1c3-lock-coordination-"
    ) as temporary:
        root = Path(temporary)
        for index, (identifier, check) in enumerate(CASES):
            try:
                passed = bool(check(root / f"{index:02d}-{identifier}"))
                results.append({"id": identifier, "passed": passed})
            except Exception as error:  # noqa: BLE001 - isolate focused case failures
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
