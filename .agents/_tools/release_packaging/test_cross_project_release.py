#!/usr/bin/env python3
"""Install and recover Agent OS in three unrelated disposable repositories."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent


FIXTURE_SPEC = ROOT / "evals" / "cross-project-fixtures.json"


def fixtures() -> list[dict[str, Any]]:
    value = json.loads(FIXTURE_SPEC.read_text(encoding="utf-8"))
    items = value.get("fixtures") if isinstance(value, dict) else None
    if value.get("schema_version") != 1 or not isinstance(items, list) or len(items) < 3:
        raise ValueError("cross-project fixture specification is invalid")
    return items


def run_json(command: list[str], cwd: Path, timeout: int = 120) -> tuple[int, dict[str, Any]]:
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError:
        value = {}
    return process.returncode, value


def git(root: Path, *args: str) -> str:
    process = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=True)
    return process.stdout.strip()


def write_binding(root: Path, fixture: dict[str, Any], commit: str) -> None:
    binding = {
        "schema_version": 1,
        "project_id": fixture["id"],
        "repository": {"kind": "git", "root_markers": fixture["root_markers"], "remote_aliases": [fixture["remote"]]},
        "workspaces": fixture["workspaces"],
        "commands": [],
        "context_entrypoints": [],
        "created_at": "2026-07-19T00:00:00Z",
        "last_verified_at": "2026-07-19T00:00:00Z",
        "last_verified_commit": commit,
    }
    path = root / ".agents" / "project" / "project-binding.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def exercise(root: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    code, packaged = run_json([
        sys.executable,
        str(ROOT / "_tools" / "package-release.py"),
        "--destination", str(root),
        "--client", "claude-code",
        "--client", "gemini-cli",
        "--client", "antigravity",
        "--confirm",
    ], PROJECT_ROOT)
    for relative, content in fixture["markers"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (root / ".gitignore").write_text(".agents/_runtime/\n.agents/_telemetry/*.jsonl\n**/__pycache__/\n**/*.pyc\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Agent OS Cross Project Fixture")
    git(root, "config", "user.email", "cross-project@agent-os.invalid")
    git(root, "remote", "add", "origin", f"https://example.invalid/{fixture['remote']}.git")
    git(root, "add", ".")
    git(root, "commit", "-qm", "application and release baseline")
    baseline = git(root, "rev-parse", "HEAD")
    write_binding(root, fixture, baseline)
    code_fp, fingerprint = run_json([sys.executable, ".agents/_tools/agent_os_lifecycle.py", "build-adapter-fingerprint", "--confirm"], root)
    git(root, "add", ".agents/project")
    git(root, "commit", "-qm", "bind Agent OS fixture")
    code_doctor, doctor = run_json([sys.executable, ".agents/_tools/agent_os_lifecycle.py", "doctor"], root)
    code_init, initialized = run_json([sys.executable, ".agents/_tools/agent_os_context_memory.py", "plan-initialize"], root)
    plan_id = initialized.get("plan", {}).get("plan_id", "")
    code_apply, applied = run_json([sys.executable, ".agents/_tools/agent_os_context_memory.py", "apply", "--plan", plan_id, "--confirm"], root)
    git(root, "add", ".agents/project/context", ".agents/skills/project-memory/SKILL.md")
    git(root, "commit", "-qm", "initialize project Context Memory")
    code_memory, memory = run_json([sys.executable, ".agents/_tools/agent_os_context_memory.py", "doctor"], root)
    return {
        "id": fixture["id"],
        "passed": bool(
            code == 0
            and packaged.get("application_scopes_included") is False
            and packaged.get("requested_clients") == ["antigravity", "claude-code", "codex", "gemini-cli"]
            and all((root / name).is_file() for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"))
            and code_fp == 0
            and fingerprint.get("ok") is True
            and code_doctor == 0
            and doctor.get("state") == "BOUND"
            and code_init == 0
            and code_apply == 0
            and applied.get("ok") is True
            and code_memory == 0
            and memory.get("state") == "FRESH"
            and memory.get("project_id") == fixture["id"]
        ),
        "lifecycle": doctor.get("state"),
        "memory": memory.get("state"),
    }


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-cross-project-") as temporary:
        base = Path(temporary)
        for fixture in fixtures():
            root = base / fixture["id"]
            root.mkdir()
            results.append(exercise(root, fixture))
    passed = sum(1 for item in results if item["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
