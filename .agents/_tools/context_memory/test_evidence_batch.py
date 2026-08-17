#!/usr/bin/env python3
"""BR3b1 focused shard for bounded batched Git evidence reads."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

from context_memory import git_batch


class Service:
    def __init__(self, root: Path):
        self.project_root = root.resolve()

    def evidence_path(self, relative: str) -> Path:
        path = (self.project_root / relative).resolve()
        path.relative_to(self.project_root)
        return path


def repository(base: Path) -> tuple[Service, str, bytes]:
    base.mkdir(parents=True)
    payload = b"binary\x00payload\n"
    (base / "evidence.bin").write_bytes(payload)
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "evidence.bin"],
        ["git", "commit", "-qm", "fixture"],
    ):
        subprocess.run(command, cwd=base, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=base,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Service(base), commit, payload


def case_reuses_batch_session(base: Path) -> bool:
    service, commit, payload = repository(base)
    original, calls = git_batch.subprocess.Popen, []

    def observed(command: list[str], **options: Any) -> Any:
        calls.append(command)
        return original(command, **options)

    git_batch.subprocess.Popen = observed
    try:
        with git_batch.GitBatchObjectReader(service) as batch:
            valid = (
                batch.blob_bytes(commit, "evidence.bin") == payload
                and batch.blob_bytes(commit, "missing.bin") is None
                and batch.blob_bytes(commit, "evidence.bin") == payload
            )
        return (
            valid
            and sum(command[-2:] == ["cat-file", "--batch"] for command in calls) == 1
        )
    finally:
        git_batch.subprocess.Popen = original


def case_oversize_fails_closed(base: Path) -> bool:
    service, commit, _payload = repository(base)
    batch = git_batch.GitBatchObjectReader(service, max_blob_bytes=3)
    first = batch.blob_bytes(commit, "evidence.bin")
    process = batch._process
    second = batch.blob_bytes(commit, "evidence.bin")
    return (
        first is None and second is None and batch._closed and batch._process is process
    )


class BlockingStream:
    def readline(self) -> bytes:
        time.sleep(0.15)
        return b""


class Sink:
    def write(self, value: bytes) -> int:
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class HangingProcess:
    pid, returncode = 4242, 0
    stdin, stdout = Sink(), BlockingStream()

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        return None

    def communicate(self, *, timeout: float) -> tuple[bytes, bytes]:
        raise subprocess.TimeoutExpired("git", timeout)


def case_timeout_kills_once(base: Path) -> bool:
    service, process, starts, killed = Service(base), HangingProcess(), [], []
    original_popen, original_kill = (
        git_batch.subprocess.Popen,
        git_batch._terminate_process_tree,
    )
    git_batch.subprocess.Popen = lambda *args, **options: (
        starts.append((args, options)) or process
    )
    git_batch._terminate_process_tree = lambda received: killed.append(received)
    try:
        batch = git_batch.GitBatchObjectReader(service, timeout_seconds=0.01)
        return (
            batch.blob_bytes("a" * 40, "a") is None
            and batch.blob_bytes("a" * 40, "a") is None
            and len(starts) == 1
            and killed == [process]
        )
    finally:
        git_batch.subprocess.Popen, git_batch._terminate_process_tree = (
            original_popen,
            original_kill,
        )


def case_kill_reaches_group_after_leader_exit(base: Path) -> bool:
    del base
    if git_batch.os.name == "nt":
        return True
    process, signals = HangingProcess(), []
    original = git_batch.os.killpg
    git_batch.os.killpg = lambda pid, command: signals.append((pid, command))
    try:
        git_batch._terminate_process_tree(process)
        return signals == [
            (process.pid, git_batch.signal.SIGTERM),
            (process.pid, git_batch.signal.SIGKILL),
        ]
    finally:
        git_batch.os.killpg = original


def case_unsafe_and_invalid_do_not_spawn(base: Path) -> bool:
    batch = git_batch.GitBatchObjectReader(Service(base))
    return (
        batch.blob_bytes("bad", "a") is None
        and batch.blob_bytes("a" * 40, "../a") is None
        and batch._process is None
    )


def case_memoizes_head_and_ancestry(base: Path) -> bool:
    service, commit, _payload = repository(base)
    original, calls = git_batch.subprocess.Popen, []

    def observed(command: list[str], **options: Any) -> Any:
        calls.append(command)
        return original(command, **options)

    git_batch.subprocess.Popen = observed
    try:
        reader = git_batch.GitBatchObjectReader(service)
        captured = reader.head()
        (base / "evidence.bin").write_bytes(b"next")
        for command in (
            ["git", "add", "evidence.bin"],
            ["git", "commit", "-qm", "next"],
        ):
            subprocess.run(command, cwd=base, check=True, capture_output=True)
        next_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        valid = (
            captured == commit == reader.head()
            and not reader.commit_is_ancestor(next_commit)
            and not reader.commit_is_ancestor(next_commit)
        )
        return (
            valid
            and sum(command[1:3] == ["rev-parse", "--verify"] for command in calls) == 1
            and sum("merge-base" in command for command in calls) == 1
        )
    finally:
        git_batch.subprocess.Popen = original


def case_cache_is_reader_local(base: Path) -> bool:
    service, commit, _payload = repository(base)
    original, calls = git_batch.subprocess.Popen, []
    git_batch.subprocess.Popen = lambda command, **options: (
        calls.append(command) or original(command, **options)
    )
    try:
        valid = all(
            git_batch.GitBatchObjectReader(service).commit_is_ancestor(commit)
            for _ in range(2)
        )
        return (
            valid
            and sum("rev-parse" in command for command in calls) == 2
            and sum("merge-base" in command for command in calls) == 2
        )
    finally:
        git_batch.subprocess.Popen = original


def case_head_timeout_is_cached(base: Path) -> bool:
    process, starts, killed = HangingProcess(), [], []
    original_popen, original_kill = (
        git_batch.subprocess.Popen,
        git_batch._terminate_process_tree,
    )
    git_batch.subprocess.Popen = lambda *args, **options: (
        starts.append((args, options)) or process
    )
    git_batch._terminate_process_tree = lambda received: killed.append(received)
    try:
        reader = git_batch.GitBatchObjectReader(Service(base), timeout_seconds=0.01)
        return (
            reader.head() is None
            and reader.head() is None
            and len(starts) == 1
            and killed == [process]
        )
    finally:
        git_batch.subprocess.Popen, git_batch._terminate_process_tree = (
            original_popen,
            original_kill,
        )


CASES = [
    ("reuse-session", case_reuses_batch_session),
    ("oversize-fail-closed", case_oversize_fails_closed),
    ("timeout-kill-zero-retry", case_timeout_kills_once),
    ("kill-group-after-leader-exit", case_kill_reaches_group_after_leader_exit),
    ("unsafe-invalid", case_unsafe_and_invalid_do_not_spawn),
    ("memoize-head-ancestry", case_memoizes_head_and_ancestry),
    ("reader-local-cache", case_cache_is_reader_local),
    ("head-timeout-zero-retry", case_head_timeout_is_cached),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br3b1-") as temporary:
        for index, (name, check) in enumerate(CASES):
            try:
                passed, error = bool(check(Path(temporary) / str(index))), None
            except Exception as exc:  # noqa: BLE001 - bounded case diagnostics
                passed, error = False, str(exc)
            results.append(
                {"id": name, "passed": passed, **({"error": error} if error else {})}
            )
    output = {
        "ok": all(item["passed"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
