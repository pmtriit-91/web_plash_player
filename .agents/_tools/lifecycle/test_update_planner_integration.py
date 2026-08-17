#!/usr/bin/env python3
"""Dependency-free negative and preservation tests for the update planner."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent
LIFECYCLE = ROOT / "_tools" / "agent_os_lifecycle.py"
PROTECTED = (
    ROOT / "project",
    ROOT / "skills" / "project-memory",
    ROOT / "skills" / "project-local",
)


def tree_digest(roots: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for base in roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*"), key=lambda item: item.as_posix()):
            if not (path.is_file() or path.is_symlink()):
                continue
            relative = path.relative_to(ROOT).as_posix().encode("utf-8")
            digest.update(relative)
            if path.is_symlink():
                digest.update(path.readlink().as_posix().encode("utf-8"))
            else:
                digest.update(path.read_bytes())
    return digest.hexdigest()


def run_plan(source: Path) -> tuple[int, dict[str, Any]]:
    process = subprocess.run(
        [sys.executable, str(LIFECYCLE), "plan-update", "--source", str(source)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = {}
    return process.returncode, payload


def copy_release(destination: Path) -> None:
    shutil.copytree(
        ROOT,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def main() -> None:
    results: list[dict[str, Any]] = []
    before = tree_digest(PROTECTED)
    manifest = json.loads(
        (ROOT / "_manifest" / "base-release-manifest.json").read_text(encoding="utf-8")
    )
    provenance_status = manifest.get("provenance", {}).get("status")
    with tempfile.TemporaryDirectory(prefix="agent-os-update-planner-") as temp:
        temp_root = Path(temp)

        clean_source = temp_root / "clean" / ".agents"
        copy_release(clean_source)
        returncode, clean = run_plan(clean_source)
        provenance_passed = (
            provenance_status == "verified-release"
            and clean.get("source", {}).get("trusted_for_apply") is True
            and "SOURCE_PROVENANCE_UNVERIFIED" not in clean.get("reason_codes", [])
        ) or (
            provenance_status == "working-baseline"
            and clean.get("source", {}).get("trusted_for_apply") is False
            and "SOURCE_PROVENANCE_UNVERIFIED" in clean.get("reason_codes", [])
        )
        clean_passed = (
            returncode == 0
            and clean.get("ok") is True
            and clean.get("writes_performed") is False
            and clean.get("release_diff") == {"added": [], "modified": [], "removed": []}
            and clean.get("protected_application", {}).get("inventory_sha256")
            and provenance_passed
            and not clean.get("dirty_paths", {}).get("unclassified")
        )
        results.append({"id": "clean-source-plan", "passed": bool(clean_passed)})

        tampered_source = temp_root / "tampered" / ".agents"
        copy_release(tampered_source)
        with (tampered_source / "README.md").open("a", encoding="utf-8") as handle:
            handle.write("\ntampered fixture\n")
        returncode, tampered = run_plan(tampered_source)
        tampered_passed = (
            returncode == 2
            and tampered.get("ok") is False
            and "SOURCE_RELEASE_INVALID" in tampered.get("reason_codes", [])
            and "SOURCE_MANIFEST_MISMATCH" in tampered.get("reason_codes", [])
            and tampered.get("writes_performed") is False
        )
        results.append({"id": "tampered-source-rejected", "passed": tampered_passed})

        protected_source = temp_root / "protected" / ".agents"
        copy_release(protected_source)
        attack = protected_source / "project" / "attack.txt"
        attack.parent.mkdir(parents=True, exist_ok=True)
        attack.write_text("must never be release-owned\n", encoding="utf-8")
        manifest_path = protected_source / "_manifest" / "base-release-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["entries"].append(
            {
                "path": "project/attack.txt",
                "type": "file",
                "sha256": hashlib.sha256(attack.read_bytes()).hexdigest(),
            }
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        returncode, protected = run_plan(protected_source)
        protected_passed = (
            returncode == 2
            and protected.get("ok") is False
            and "SOURCE_PROTECTED_SCOPE_DECLARED" in protected.get("reason_codes", [])
            and protected.get("writes_performed") is False
        )
        results.append({"id": "protected-scope-rejected", "passed": protected_passed})

    after = tree_digest(PROTECTED)
    results.append({"id": "application-state-preserved", "passed": before == after})
    passed = sum(1 for result in results if result["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
