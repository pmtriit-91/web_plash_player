#!/usr/bin/env python3
"""Shared fixture primitives for Control Center acceptance owners."""

from __future__ import annotations

import subprocess
from pathlib import Path

BASE_SETTINGS = {
    "schema_version": 1,
    "project_id": "fixture-project",
    "default_mode": "DEEP",
    "automation": {
        "discovery": "event-driven-and-manual",
        "activation_requires_approval": True,
        "background_daemon": False,
        "auto_commit": False,
        "auto_push": False,
    },
    "connectors": {
        "github": "optional",
        "notebooklm": "optional",
        "mcp-skill-index": "disabled",
    },
    "budgets": {
        "max_candidates_per_scan": 20,
        "max_snapshot_bytes": 10485760,
        "plan_expiry_seconds": 900,
    },
}


def git(root: Path, *arguments: str) -> None:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
