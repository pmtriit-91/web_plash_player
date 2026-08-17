"""Reusable Git/worktree fixtures for task-growth contract shards."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


def git(root: Path, *arguments: str) -> str:
    command = ["git", *arguments]
    return subprocess.check_output(command, cwd=root, text=True, timeout=10).strip()


def write(root: Path, relative: str, content: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def build_growth_fixture(
    root: Path,
) -> tuple[dict[str, bytes], dict[str, Any], Callable[[], None]]:
    """Initialize the shared repository and return baseline, envelope, and restore."""
    git(root, "init", "-q")
    git(root, "config", "user.name", "Agent OS Test")
    git(root, "config", "user.email", "agent-os@example.invalid")
    baseline = {
        ".agents/_tools/existing.py": b"x\n",
        ".agents/_tools/group/caller.py": b"x\n",
        ".agents/_tools/tooling_topology/topology.json": (
            json.dumps(
                {
                    "direct_root_exceptions": [
                        {
                            "name": "approved.py",
                            "owner": "fixture-owner",
                            "role": "stable-public-entrypoint",
                            "caller_path": "group/caller.py",
                        }
                    ]
                }
            )
            + "\n"
        ).encode(),
        "src/large.py": b"x\n" * 1001,
        "src/small.py": b"x\n",
        "docs/status.md": b"x\n",
        "data/state.bin": b"12",
        "build/projection.json": b"{}\n",
    }

    def restore() -> None:
        (root / "extra.txt").unlink(missing_ok=True)
        (root / ".agents/_tools/new.py").unlink(missing_ok=True)
        (root / ".agents/_tools/approved.py").unlink(missing_ok=True)
        (root / ".agents/_tools/group/new.py").unlink(missing_ok=True)
        for relative, content in baseline.items():
            target = root / relative
            if target.is_dir():
                shutil.rmtree(target)
            write(root, relative, content)

    restore()
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    envelope = {
        "schema_version": 1,
        "base_commit": git(root, "rev-parse", "HEAD"),
        "budgets": {
            "oversized_source_test_lines": 1000,
            "source_test_growth_lines": 2,
            "documentation_growth_lines": 2,
            "data_growth_bytes": 2,
            "max_file_bytes": 200000,
        },
        "paths": [
            {"path": "src/large.py", "artifact_class": "source-test"},
            {"path": "src/small.py", "artifact_class": "source-test"},
            {"path": "docs/status.md", "artifact_class": "documentation"},
            {"path": "data/state.bin", "artifact_class": "data"},
            {"path": "build/projection.json", "artifact_class": "generated"},
        ],
    }
    return baseline, envelope, restore
