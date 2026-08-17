#!/usr/bin/env python3
"""Focused P1c1 checks for the shared kernel-backed lock primitive."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import agent_os_transaction_lock as transaction_lock
from agent_os_transaction_lock import (
    LOCK_FORMAT,
    MAX_METADATA_BYTES,
    TransactionLockError,
    acquire_transaction_lock,
    release_transaction_lock,
)


def rejected(code: str, operation: Callable[[], object]) -> bool:
    try:
        operation()
    except TransactionLockError as error:
        return error.reason_code == code
    return False


def wait_for(path: Path, process: subprocess.Popen[bytes]) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.02)
    return False


def stop(process: subprocess.Popen[bytes]) -> None:
    if process.stdin:
        process.stdin.write(b"x")
        process.stdin.flush()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


def child(mode: str, lock: Path, ready: Path) -> None:
    handle = acquire_transaction_lock(lock, f"child-{mode}")
    ready.write_text("ready", encoding="utf-8")
    if mode == "crash":
        os._exit(0)
    sys.stdin.buffer.read(1)
    release_transaction_lock(handle)


def main() -> None:
    cases: list[dict[str, object]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    with tempfile.TemporaryDirectory(prefix="aos15-p1c1-") as temporary:
        root = Path(temporary)
        lock = root / "apply.lock"
        first = acquire_transaction_lock(lock, "first-owner")
        metadata = json.loads(lock.read_text(encoding="utf-8"))
        check(
            "metadata-is-bounded-and-diagnostic",
            len(lock.read_bytes()) <= MAX_METADATA_BYTES
            and metadata["format"] == LOCK_FORMAT
            and metadata["owner"] == "first-owner",
        )
        release_transaction_lock(first)
        check("release-retains-stable-lock-file", lock.is_file())
        release_transaction_lock(first)
        check("release-is-idempotent", first.released)

        calls: list[str] = []
        original_kernel_lock = transaction_lock._kernel_lock
        original_valid_metadata = transaction_lock._valid_metadata

        def traced_kernel_lock(descriptor: int) -> str:
            calls.append("kernel-lock")
            return original_kernel_lock(descriptor)

        def traced_valid_metadata(descriptor: int) -> bool:
            calls.append("metadata-read")
            return original_valid_metadata(descriptor)

        with (
            patch.object(
                transaction_lock, "_kernel_lock", side_effect=traced_kernel_lock
            ),
            patch.object(
                transaction_lock, "_valid_metadata", side_effect=traced_valid_metadata
            ),
        ):
            second = acquire_transaction_lock(lock, "second-owner")
        release_transaction_lock(second)
        check(
            "valid-file-reacquires-kernel-before-metadata-read",
            json.loads(lock.read_text())["owner"] == "second-owner"
            and calls == ["kernel-lock", "metadata-read"],
        )

        other = acquire_transaction_lock(root / "other.lock", "independent")
        release_transaction_lock(other)
        check("independent-lock-paths-do-not-conflict", True)

        legacy = root / "legacy.lock"
        legacy.touch()
        check(
            "legacy-empty-lock-fails-closed",
            rejected(
                "TRANSACTION_LOCK_LEGACY_UNVERIFIED",
                lambda: acquire_transaction_lock(legacy, "owner"),
            ),
        )
        corrupt = root / "corrupt.lock"
        corrupt.write_text("not-json", encoding="utf-8")
        check(
            "corrupt-lock-metadata-fails-closed",
            rejected(
                "TRANSACTION_LOCK_LEGACY_UNVERIFIED",
                lambda: acquire_transaction_lock(corrupt, "owner"),
            ),
        )
        check(
            "invalid-owner-fails-closed",
            rejected(
                "TRANSACTION_LOCK_OWNER_INVALID",
                lambda: acquire_transaction_lock(root / "bad.lock", "bad\nowner"),
            ),
        )

        ready = root / "live.ready"
        live = subprocess.Popen(
            [sys.executable, __file__, "--child", "hold", str(lock), str(ready)],
            stdin=subprocess.PIPE,
        )
        live_ready = wait_for(ready, live)
        check(
            "live-kernel-owner-cannot-be-stolen",
            live_ready
            and rejected(
                "TRANSACTION_LOCK_BUSY",
                lambda: acquire_transaction_lock(lock, "contender"),
            ),
        )
        stop(live)

        ready = root / "crash.ready"
        crashed = subprocess.Popen(
            [sys.executable, __file__, "--child", "crash", str(lock), str(ready)]
        )
        crash_ready = wait_for(ready, crashed)
        crashed.wait(timeout=5)
        recovered = acquire_transaction_lock(lock, "recovered") if crash_ready else None
        check("crash-drops-kernel-lock-and-allows-recovery", recovered is not None)
        if recovered:
            release_transaction_lock(recovered)

    passed = sum(bool(item["passed"]) for item in cases)
    output = {
        "ok": passed == len(cases),
        "passed": passed,
        "total": len(cases),
        "results": cases,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--child":
        child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        main()
