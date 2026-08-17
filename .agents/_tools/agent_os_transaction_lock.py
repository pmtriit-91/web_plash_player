#!/usr/bin/env python3
"""Small cross-platform kernel-backed transaction lock primitive."""

from __future__ import annotations

import errno
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import NoReturn

_LOCK_API = import_module("msvcrt" if os.name == "nt" else "fcntl")

LOCK_FORMAT = "agent-os-transaction-lock-v1"
MAX_METADATA_BYTES = 1024
BUSY_ERRNOS = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


class TransactionLockError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


@dataclass
class TransactionLockHandle:
    descriptor: int
    path: Path
    backend: str
    released: bool = False


def _fail(reason_code: str, detail: str) -> NoReturn:
    raise TransactionLockError(reason_code, detail)


def _metadata(owner: str) -> bytes:
    if not owner or len(owner) > 128 or any(ord(character) < 32 for character in owner):
        _fail("TRANSACTION_LOCK_OWNER_INVALID", "owner must be bounded printable text")
    content = {
        "acquired_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "format": LOCK_FORMAT,
        "nonce": secrets.token_hex(16),
        "owner": owner,
        "pid": os.getpid(),
    }
    encoded = (
        json.dumps(content, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if len(encoded) > MAX_METADATA_BYTES:
        _fail("TRANSACTION_LOCK_METADATA_INVALID", "metadata exceeds bound")
    return encoded


def _write(descriptor: int, content: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    written = 0
    while written < len(content):
        written += os.write(descriptor, content[written:])
    os.ftruncate(descriptor, len(content))
    os.fsync(descriptor)


def _valid_metadata(descriptor: int) -> bool:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, MAX_METADATA_BYTES + 1)
    if not raw or len(raw) > MAX_METADATA_BYTES:
        return False
    try:
        content = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(content, dict)
        and set(content) == {"acquired_at", "format", "nonce", "owner", "pid"}
        and content.get("format") == LOCK_FORMAT
        and isinstance(content.get("owner"), str)
        and 1 <= len(content["owner"]) <= 128
        and isinstance(content.get("pid"), int)
        and content["pid"] > 0
        and isinstance(content.get("acquired_at"), str)
        and content["acquired_at"].endswith("Z")
        and isinstance(content.get("nonce"), str)
        and len(content["nonce"]) == 32
        and all(character in "0123456789abcdef" for character in content["nonce"])
    )


def _kernel_lock(descriptor: int) -> str:
    try:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            _LOCK_API.locking(descriptor, _LOCK_API.LK_NBLCK, 1)
            return "windows-msvcrt"
        _LOCK_API.flock(descriptor, _LOCK_API.LOCK_EX | _LOCK_API.LOCK_NB)
        return "posix-flock"
    except OSError as error:
        if error.errno in BUSY_ERRNOS:
            _fail("TRANSACTION_LOCK_BUSY", "kernel lock is held")
        _fail("TRANSACTION_LOCK_IO_FAILED", str(error))


def acquire_transaction_lock(path: Path, owner: str) -> TransactionLockHandle:
    """Acquire a stable lock file; legacy files without valid metadata fail closed."""
    path = Path(path)
    if not path.parent.is_dir() or path.is_symlink():
        _fail("TRANSACTION_LOCK_PATH_UNSAFE", str(path))
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    content = _metadata(owner)
    try:
        try:
            descriptor = os.open(path, flags | os.O_EXCL, 0o600)
            _write(descriptor, content)
        except FileExistsError:
            descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        _fail("TRANSACTION_LOCK_PATH_UNSAFE", str(error))
    try:
        backend = _kernel_lock(descriptor)
        if not _valid_metadata(descriptor):
            _fail("TRANSACTION_LOCK_LEGACY_UNVERIFIED", str(path))
        _write(descriptor, content)
        return TransactionLockHandle(descriptor, path, backend)
    except Exception:
        os.close(descriptor)
        raise


def release_transaction_lock(handle: TransactionLockHandle) -> None:
    """Release kernel ownership while intentionally retaining the stable file."""
    if handle.released:
        return
    if handle.backend == "windows-msvcrt":
        os.lseek(handle.descriptor, 0, os.SEEK_SET)
        _LOCK_API.locking(handle.descriptor, _LOCK_API.LK_UNLCK, 1)
    else:
        _LOCK_API.flock(handle.descriptor, _LOCK_API.LOCK_UN)
    os.close(handle.descriptor)
    handle.released = True
