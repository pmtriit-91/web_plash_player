#!/usr/bin/env python3
"""Dependency-free apply, rollback, and failure-recovery fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        merged.update(env)
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=merged,
    )


def lifecycle(project: Path, *arguments: str, env: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    process = run(
        [sys.executable, ".agents/_tools/agent_os_lifecycle.py", *arguments],
        project,
        env,
    )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = {"stdout": process.stdout, "stderr": process.stderr}
    return process.returncode, payload


def copy_agents(destination: Path) -> None:
    shutil.copytree(
        ROOT,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "_runtime"),
    )


def init_target(path: Path) -> None:
    path.mkdir(parents=True)
    copy_agents(path / ".agents")
    (path / "AGENTS.md").write_text(
        "# Fixture bridge\n\nRead `.agents/AGENTS.md`.\n",
        encoding="utf-8",
    )
    (path / ".gitignore").write_text(
        ".agents/_runtime/\n**/__pycache__/\n**/*.pyc\n",
        encoding="utf-8",
    )
    preserved = path / ".agents" / "project" / "fixture-state.txt"
    preserved.parent.mkdir(parents=True, exist_ok=True)
    preserved.write_text("application-owned fixture\n", encoding="utf-8")
    for command in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Agent OS Fixture"],
        ["git", "config", "user.email", "fixture@agent-os.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-m", "fixture baseline"],
    ):
        process = run(command, path)
        if process.returncode != 0:
            raise RuntimeError(process.stderr or process.stdout)


def create_candidate(path: Path) -> None:
    copy_agents(path / ".agents")
    readme = path / ".agents" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\ntransaction fixture release\n", encoding="utf-8")
    manifest_path = path / ".agents" / "_manifest" / "base-release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_id"] = "transaction-fixture-release"
    manifest["provenance"] = {
        "status": "verified-release",
        "source_locator": "fixture:transaction-source",
        "source_commit": "a" * 40,
        "created_from_repository_head": "a" * 40,
    }
    readme_hash = hashlib.sha256(readme.read_bytes()).hexdigest()
    for entry in manifest["entries"]:
        if entry["path"] == "README.md":
            entry["sha256"] = readme_hash
            break
    else:
        raise RuntimeError("README.md is missing from the release manifest")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def protected_digest(project: Path) -> str:
    digest = hashlib.sha256()
    roots = (
        project / ".agents" / "project",
        project / ".agents" / "skills" / "project-memory",
        project / ".agents" / "skills" / "project-local",
    )
    for root in roots:
        if not root.exists():
            continue
        for file in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if file.is_file() or file.is_symlink():
                digest.update(file.relative_to(project / ".agents").as_posix().encode("utf-8"))
                digest.update(os.readlink(file).encode("utf-8") if file.is_symlink() else file.read_bytes())
    return digest.hexdigest()


def apply_and_rollback(target: Path, source: Path) -> bool:
    before = protected_digest(target)
    code, plan = lifecycle(target, "plan-update", "--source", str(source / ".agents"))
    if code != 0 or not plan.get("ready_to_apply") or not plan.get("plan_id"):
        return False
    code, applied = lifecycle(
        target,
        "apply-update",
        "--source",
        str(source / ".agents"),
        "--plan-id",
        plan["plan_id"],
        "--confirm",
    )
    if code != 0 or not applied.get("ok") or before != protected_digest(target):
        return False
    if "transaction fixture release" not in (target / ".agents" / "README.md").read_text(encoding="utf-8"):
        return False
    code, rolled_back = lifecycle(
        target,
        "rollback-update",
        "--transaction-id",
        applied["transaction_id"],
        "--confirm",
    )
    return bool(
        code == 0
        and rolled_back.get("ok")
        and before == protected_digest(target)
        and "transaction fixture release" not in (target / ".agents" / "README.md").read_text(encoding="utf-8")
    )


def injected_failure_rolls_back(target: Path, source: Path) -> bool:
    before = protected_digest(target)
    original_readme = (target / ".agents" / "README.md").read_bytes()
    code, plan = lifecycle(target, "plan-update", "--source", str(source / ".agents"))
    if code != 0 or not plan.get("ready_to_apply"):
        return False
    code, failed = lifecycle(
        target,
        "apply-update",
        "--source",
        str(source / ".agents"),
        "--plan-id",
        plan["plan_id"],
        "--confirm",
        "--test-fail-after",
        "1",
        env={"AGENT_OS_TEST_MODE": "1"},
    )
    verify_code, verified = lifecycle(target, "verify-core")
    return bool(
        code == 2
        and failed.get("reason_codes") == ["UPDATE_APPLY_FAILED", "UPDATE_ROLLED_BACK"]
        and failed.get("rollback_core_ok") is True
        and before == protected_digest(target)
        and original_readme == (target / ".agents" / "README.md").read_bytes()
        and verify_code == 0
        and verified.get("ok") is True
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-os-update-transaction-") as temporary:
        base = Path(temporary)
        source = base / "source"
        target = base / "target"
        failure_target = base / "failure-target"
        create_candidate(source)
        init_target(target)
        init_target(failure_target)
        results = [
            {"id": "apply-and-explicit-rollback", "passed": apply_and_rollback(target, source)},
            {"id": "failure-auto-rollback", "passed": injected_failure_rolls_back(failure_target, source)},
        ]
    passed = sum(1 for result in results if result["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
