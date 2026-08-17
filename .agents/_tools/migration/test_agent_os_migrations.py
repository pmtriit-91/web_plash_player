#!/usr/bin/env python3
"""Disposable V8 and V9 working-baseline migration acceptance fixtures."""

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
MIGRATE = ROOT / "_tools" / "agent_os_migrate.py"


def run_json(arguments: list[str], cwd: Path) -> tuple[int, dict[str, Any]]:
    process = subprocess.run([sys.executable, str(MIGRATE), *arguments], cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = {}
    return process.returncode, payload


def git(root: Path, *arguments: str, timeout_seconds: int = 30) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def initialize_git(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Agent OS Migration Fixture")
    git(root, "config", "user.email", "migration-fixture@agent-os.invalid")
    git(root, "add", ".", timeout_seconds=90)
    git(root, "commit", "-qm", "fixture baseline")


def base_bridge(root: Path) -> None:
    (root / "AGENTS.md").write_text("# Fixture bridge\n\nRead `.agents/AGENTS.md`.\n", encoding="utf-8")
    (root / ".gitignore").write_text(".agents/_runtime/\n**/__pycache__/\n**/*.pyc\n", encoding="utf-8")


def protected_digest(root: Path) -> str:
    digest = hashlib.sha256()
    agent = root / ".agents"
    for prefix in ("project", "skills/project-memory", "skills/project-local"):
        base = agent / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file() or path.is_symlink():
                digest.update(path.relative_to(agent).as_posix().encode("utf-8"))
                digest.update(os.readlink(path).encode("utf-8") if path.is_symlink() else path.read_bytes())
    return digest.hexdigest()


def v8_fixture(root: Path) -> None:
    agent = root / ".agents"
    (agent / "_manifest").mkdir(parents=True)
    (agent / "core").mkdir(parents=True)
    (agent / "project").mkdir(parents=True)
    (agent / "skills" / "project-memory").mkdir(parents=True)
    (agent / "_manifest" / "private-release-snapshot.json").write_text(json.dumps({"version": "8.0.7"}, indent=2) + "\n", encoding="utf-8")
    (agent / "AGENTS.md").write_text("# Legacy V8 Agent OS\n", encoding="utf-8")
    (agent / "core" / "legacy.txt").write_text("legacy release byte\n", encoding="utf-8")
    (agent / "project" / "consumer-state.txt").write_text("preserve v8 project state\n", encoding="utf-8")
    (agent / "skills" / "project-memory" / "SKILL.md").write_text("preserve v8 memory\n", encoding="utf-8")
    (root / "application.txt").write_text("unrelated v8 application\n", encoding="utf-8")
    base_bridge(root)
    initialize_git(root)


def v9_working_fixture(root: Path) -> None:
    shutil.copytree(ROOT, root / ".agents", symlinks=True, ignore=shutil.ignore_patterns("_runtime", "__pycache__", "*.pyc", ".DS_Store"))
    manifest_path = root / ".agents" / "_manifest" / "base-release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    readme = root / ".agents" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nworking baseline drift\n", encoding="utf-8")
    for entry in manifest["entries"]:
        if entry["path"] == "README.md":
            entry["sha256"] = hashlib.sha256(readme.read_bytes()).hexdigest()
    manifest["release_id"] = "v9-working-fixture"
    manifest["provenance"] = {"status": "working-baseline", "source_locator": "fixture", "source_commit": None, "created_from_repository_head": None}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / ".agents" / "project" / "consumer-state.txt").parent.mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "project" / "consumer-state.txt").write_text("preserve v9 project state\n", encoding="utf-8")
    (root / "application.txt").write_text("unrelated v9 application\n", encoding="utf-8")
    base_bridge(root)
    initialize_git(root)


def exercise(source: Path, root: Path, expected_family: str, legacy_marker: Path) -> dict[str, Any]:
    before = protected_digest(root)
    code, inspected = run_json(["inspect", "--target", str(root)], root)
    code_plan, planned = run_json(["plan", "--source", str(source), "--target", str(root)], root)
    plan = planned.get("plan", {})
    code_apply, applied = run_json(["apply", "--target", str(root), "--plan", str(plan.get("plan_id", "")), "--confirm"], root)
    after = protected_digest(root)
    core = subprocess.run([sys.executable, ".agents/_tools/agent_os_lifecycle.py", "verify-core"], cwd=root, capture_output=True, text=True, timeout=60, check=False)
    try:
        core_result = json.loads(core.stdout)
    except json.JSONDecodeError:
        core_result = {}
    transaction = applied.get("transaction_id", "")
    code_rollback, rolled = run_json(["rollback", "--target", str(root), "--transaction", transaction, "--confirm"], root)
    return {
        "passed": bool(
            code == 0
            and inspected.get("family") == expected_family
            and code_plan == 0
            and plan.get("ready_to_apply") is True
            and code_apply == 0
            and applied.get("ok") is True
            and core.returncode == 0
            and core_result.get("ok") is True
            and before == after
            and code_rollback == 0
            and rolled.get("ok") is True
            and legacy_marker.is_file()
            and protected_digest(root) == before
        ),
        "family": inspected.get("family"),
    }


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-migrations-") as temporary:
        base = Path(temporary)
        source = base / "verified-source"
        shutil.copytree(ROOT, source, symlinks=True, ignore=shutil.ignore_patterns("project", "_runtime", "__pycache__", "*.pyc", ".DS_Store"))
        source_manifest = source / "_manifest" / "base-release-manifest.json"
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        manifest["provenance"] = {
            "status": "verified-release",
            "source_locator": "fixture:aos12-content",
            "source_commit": "0" * 40,
            "created_from_repository_head": "0" * 40
        }
        source_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        v8 = base / "v8"
        v8.mkdir()
        v8_fixture(v8)
        result = exercise(source, v8, "v8-legacy", v8 / ".agents" / "core" / "legacy.txt")
        results.append({"id": "v8-legacy-transaction-and-rollback", **result})

        v9 = base / "v9-working"
        v9.mkdir()
        v9_working_fixture(v9)
        result = exercise(source, v9, "v9-working-baseline", v9 / ".agents" / "README.md")
        results.append({"id": "v9-working-baseline-transaction-and-rollback", **result})

        dirty = base / "dirty"
        dirty.mkdir()
        v8_fixture(dirty)
        (dirty / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
        _, planned = run_json(["plan", "--source", str(source), "--target", str(dirty)], dirty)
        results.append({"id": "dirty-migration-blocked", "passed": "MIGRATION_TARGET_DIRTY" in planned.get("plan", {}).get("reason_codes", [])})

    passed = sum(1 for item in results if item.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
