"""Bounded Git object batch session for Context Memory deep runs."""

from __future__ import annotations

import os
import queue
import re
import signal
import subprocess
import threading
from typing import Any

FULL_COMMIT = re.compile(r"[0-9a-f]{40}")
_UNSET = object()


def _process_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        # Descendants can retain pipes after the group leader exits.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        if process.poll() is None:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass


class GitBatchObjectReader:
    """Reuse one fail-closed ``git cat-file --batch`` process."""

    def __init__(self, service: Any, *, timeout_seconds: float = 10, max_blob_bytes: int = 1_048_576):
        self.service = service
        self.timeout_seconds = timeout_seconds
        self.max_blob_bytes = max_blob_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._head: str | None | object = _UNSET
        self._ancestry: dict[tuple[str, str], bool] = {}

    def __enter__(self) -> GitBatchObjectReader:  # noqa: PYI034 - Python 3.10 compatible
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def _start(self) -> bool:
        if self._closed:
            return False
        if self._process is not None:
            return True
        try:
            self._process = subprocess.Popen(
                ["git", "cat-file", "--batch"], cwd=self.service.project_root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **_process_options(),
            )
        except OSError:
            self._closed = True
        return self._process is not None

    @staticmethod
    def _read_exact(stream: Any, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = stream.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_response(self) -> tuple[bool, bytes | None]:
        assert self._process is not None and self._process.stdout is not None
        header = self._process.stdout.readline().rstrip(b"\n")
        fields = header.rsplit(b" ", 2)
        if header.endswith(b" missing"):
            return True, None
        if len(fields) != 3 or fields[1] != b"blob" or not fields[2].isdigit():
            return False, None
        size = int(fields[2])
        if size > self.max_blob_bytes:
            return False, None
        payload = self._read_exact(self._process.stdout, size + 1)
        return (True, payload[:-1]) if payload is not None and payload.endswith(b"\n") else (False, None)

    def _abort(self) -> None:
        self._closed = True
        if self._process is not None:
            _terminate_process_tree(self._process)

    def _run_git(self, arguments: list[str]) -> tuple[int, bytes] | None:
        try:
            process = subprocess.Popen(
                ["git", *arguments], cwd=self.service.project_root,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **_process_options(),
            )
        except OSError:
            return None
        try:
            stdout, _stderr = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            return None
        return process.returncode, stdout

    def head(self) -> str | None:
        """Return one immutable HEAD snapshot for this reader lifetime."""
        with self._lock:
            if self._head is _UNSET:
                result = self._run_git(["rev-parse", "--verify", "HEAD"])
                candidate = result[1].decode(errors="replace").strip() if result and result[0] == 0 else ""
                self._head = candidate if FULL_COMMIT.fullmatch(candidate) else None
            return self._head if isinstance(self._head, str) else None

    def commit_is_ancestor(self, commit: str) -> bool:
        """Memoize ancestry against this reader's captured HEAD only."""
        if FULL_COMMIT.fullmatch(commit) is None:
            return False
        head = self.head()
        if head is None:
            return False
        key = (head, commit)
        with self._lock:
            if key not in self._ancestry:
                result = self._run_git(["merge-base", "--is-ancestor", commit, head])
                self._ancestry[key] = result is not None and result[0] == 0
            return self._ancestry[key]

    def blob_bytes(self, commit: str, relative: str) -> bytes | None:
        if FULL_COMMIT.fullmatch(commit) is None:
            return None
        try:
            canonical = self.service.evidence_path(relative).relative_to(self.service.project_root).as_posix()
        except ValueError:
            return None
        if "\n" in canonical or "\r" in canonical:
            return None
        with self._lock:
            if not self._start() or self._process is None or self._process.stdin is None:
                return None
            try:
                self._process.stdin.write(f"{commit}:{canonical}\n".encode())
                self._process.stdin.flush()
            except (BrokenPipeError, OSError):
                self._abort()
                return None
            responses: queue.Queue[tuple[bool, bytes | None]] = queue.Queue(maxsize=1)
            threading.Thread(target=lambda: responses.put(self._read_response()), daemon=True).start()
            try:
                valid, payload = responses.get(timeout=self.timeout_seconds)
            except queue.Empty:
                self._abort()
                return None
            if not valid:
                self._abort()
                return None
            return payload

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            try:
                assert self._process.stdin is not None
                self._process.stdin.close()
                self._process.wait(timeout=min(self.timeout_seconds, 1))
            except (OSError, subprocess.TimeoutExpired):
                _terminate_process_tree(self._process)
        self._closed = True
