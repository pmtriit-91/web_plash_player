#!/usr/bin/env python3
"""Verify that release packaging is complete and ownership-pure."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=60, check=False, env=env)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not (path.is_file() or path.is_symlink()):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(os.readlink(path).encode("utf-8") if path.is_symlink() else path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-os-package-") as temporary:
        destination = Path(temporary) / "release"
        second_destination = Path(temporary) / "release-second"
        command = [
            sys.executable,
            ".agents/_tools/package-release.py",
            "--client",
            "claude-code",
            "--client",
            "gemini-cli",
            "--client",
            "antigravity",
            "--confirm",
        ]
        packaged = run(
            [*command, "--destination", str(destination)],
            PROJECT_ROOT,
        )
        packaged_second = run([*command, "--destination", str(second_destination)], PROJECT_ROOT)
        try:
            package_result = json.loads(packaged.stdout)
        except json.JSONDecodeError:
            package_result = {}
        verified = run(
            [sys.executable, ".agents/_tools/agent_os_lifecycle.py", "verify-core"],
            destination,
        )
        try:
            verify_result = json.loads(verified.stdout)
        except json.JSONDecodeError:
            verify_result = {}
        forbidden = [
            destination / ".agents" / "project",
            destination / ".agents" / "skills" / "project-memory",
            destination / ".agents" / "skills" / "project-local",
            destination / ".agents" / "_runtime",
        ]
        passed = bool(
            packaged.returncode == 0
            and package_result.get("ok") is True
            and package_result.get("application_scopes_included") is False
            and verified.returncode == 0
            and verify_result.get("ok") is True
            and (destination / "AGENTS.md").is_file()
            and (destination / ".agents" / "THIRD_PARTY_NOTICES.md").is_file()
            and (destination / "CLAUDE.md").is_file()
            and (destination / "GEMINI.md").is_file()
            and package_result.get("requested_clients") == ["antigravity", "claude-code", "codex", "gemini-cli"]
            and packaged_second.returncode == 0
            and tree_digest(destination) == tree_digest(second_destination)
            and not any(path.exists() for path in forbidden)
        )
        output = {
            "ok": passed,
            "passed": 1 if passed else 0,
            "total": 1,
            "results": [{"id": "manifest-only-release-package", "passed": passed}],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
