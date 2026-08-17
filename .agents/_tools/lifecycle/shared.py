#!/usr/bin/env python3
"""Shared dependency-free primitives for the Agent OS lifecycle domain."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FULL_COMMIT = re.compile(r"^[a-f0-9]{40}$")
FULL_SHA256 = re.compile(r"^[a-f0-9]{64}$")
FORBIDDEN_UPDATE_SCOPES = (
    "project/**",
    "skills/project-memory/**",
    "skills/project-local/**",
    "_runtime/**",
    "_telemetry/*.jsonl",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/.DS_Store",
)


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=True, indent=2, sort_keys=False))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256_bytes(payload.encode("utf-8"))


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def git_output(*args: str) -> str | None:
    try:
        process = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    return process.stdout.strip()
