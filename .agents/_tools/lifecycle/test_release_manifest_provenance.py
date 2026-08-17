#!/usr/bin/env python3
"""Adversarial acceptance tests for verified-release manifest provenance."""

from __future__ import annotations

import importlib
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
sys.path.insert(0, str(ROOT / "_tools"))
lifecycle = importlib.import_module("agent_os_lifecycle")
VERIFIED_LOCATOR = "fixture://verified-source"


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        env=environment,
    )


def git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *arguments], repo)


def lifecycle_command(
    repo: Path,
    release_id: str,
    *,
    source_locator: str | None = None,
    source_commit: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    command = [
        sys.executable,
        ".agents/_tools/agent_os_lifecycle.py",
        "build-manifest",
        "--release-id",
        release_id,
    ]
    if source_locator is not None:
        command.extend(["--source-locator", source_locator])
    if source_commit is not None:
        command.extend(["--source-commit", source_commit])
    command.append("--confirm")
    process = run(command, repo)
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = {}
    return process, payload


def manifest_path(repo: Path) -> Path:
    return repo / ".agents" / "_manifest" / "base-release-manifest.json"


def reset_fixture(repo: Path, baseline: str) -> None:
    reset = git(repo, "reset", "--hard", baseline)
    clean = git(repo, "clean", "-fdx")
    if reset.returncode != 0 or clean.returncode != 0:
        raise RuntimeError(f"fixture reset failed: {reset.stderr}{clean.stderr}")


def rejected_without_manifest_mutation(
    repo: Path,
    expected_reason: str,
    *,
    release_id: str,
    source_locator: str | None = None,
    source_commit: str | None = None,
    forbidden_output: str | None = None,
) -> bool:
    before = manifest_path(repo).read_bytes()
    process, payload = lifecycle_command(
        repo,
        release_id,
        source_locator=source_locator,
        source_commit=source_commit,
    )
    after = manifest_path(repo).read_bytes()
    return bool(
        process.returncode == 2
        and payload.get("ok") is False
        and expected_reason in payload.get("reason_codes", [])
        and before == after
        and (
            forbidden_output is None
            or forbidden_output not in process.stdout + process.stderr
        )
    )


def prepare_seed(destination: Path) -> tuple[Path, str]:
    repo = destination / "fixture"
    shutil.copytree(
        PROJECT_ROOT,
        repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git",
            "_runtime",
            "__pycache__",
            "*.pyc",
            ".DS_Store",
        ),
    )
    attributes = repo / ".agents" / ".gitattributes"
    attributes.write_bytes(
        attributes.read_bytes()
        + b"\ncore/export-ignored-fixture.txt export-ignore\n"
        + b"core/export-substituted-fixture.txt export-subst\n"
    )
    (repo / ".agents" / "core" / "export-ignored-fixture.txt").write_bytes(
        b"exact committed bytes remain release-owned\n"
    )
    (repo / ".agents" / "core" / "export-substituted-fixture.txt").write_bytes(
        b"literal archive placeholder: $Format:%H$\n"
    )
    commands = [
        ["init", "--quiet"],
        ["config", "user.name", "Agent OS Fixture"],
        ["config", "user.email", "fixture@agent-os.invalid"],
        ["remote", "add", "origin", VERIFIED_LOCATOR],
        ["add", ".agents"],
        ["commit", "--quiet", "-m", "fixture baseline"],
    ]
    for command in commands:
        process = git(repo, *command)
        if process.returncode != 0:
            raise RuntimeError(f"fixture setup failed: {process.stderr}")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, head


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-release-provenance-") as temporary:
        repo, baseline = prepare_seed(Path(temporary))

        process, payload = lifecycle_command(
            repo,
            "fixture-verified-release",
            source_locator=VERIFIED_LOCATOR,
            source_commit=baseline,
        )
        manifest = json.loads(manifest_path(repo).read_text(encoding="utf-8"))
        provenance = manifest.get("provenance", {})
        results.append(
            {
                "id": "verified-release-uses-exact-head-git-blobs",
                "passed": bool(
                    process.returncode == 0
                    and payload.get("ok") is True
                    and provenance.get("status") == "verified-release"
                    and provenance.get("source_locator") == VERIFIED_LOCATOR
                    and provenance.get("source_commit") == baseline
                    and provenance.get("created_from_repository_head") == baseline
                ),
            }
        )

        reset_fixture(repo, baseline)
        results.append(
            {
                "id": "locator-without-commit-is-rejected-atomically",
                "passed": rejected_without_manifest_mutation(
                    repo,
                    "SOURCE_PROVENANCE_ARGUMENTS_INCOMPLETE",
                    release_id="fixture-locator-only",
                    source_locator=VERIFIED_LOCATOR,
                ),
            }
        )

        reset_fixture(repo, baseline)
        results.append(
            {
                "id": "commit-without-locator-is-rejected-atomically",
                "passed": rejected_without_manifest_mutation(
                    repo,
                    "SOURCE_PROVENANCE_ARGUMENTS_INCOMPLETE",
                    release_id="fixture-commit-only",
                    source_commit=baseline,
                ),
            }
        )

        reset_fixture(repo, baseline)
        results.append(
            {
                "id": "nonexistent-commit-is-rejected-atomically",
                "passed": rejected_without_manifest_mutation(
                    repo,
                    "SOURCE_COMMIT_NOT_FOUND",
                    release_id="fixture-missing-commit",
                    source_locator=VERIFIED_LOCATOR,
                    source_commit="f" * 40,
                ),
            }
        )

        reset_fixture(repo, baseline)
        application_file = repo / ".agents" / "project" / "fixture-head-advance.txt"
        application_file.write_text("application-owned fixture\n", encoding="utf-8")
        git(repo, "add", application_file.relative_to(repo).as_posix())
        advanced = git(repo, "commit", "--quiet", "-m", "advance fixture head")
        results.append(
            {
                "id": "existing-ancestor-is-not-current-head",
                "passed": bool(
                    advanced.returncode == 0
                    and rejected_without_manifest_mutation(
                        repo,
                        "SOURCE_COMMIT_NOT_HEAD",
                        release_id="fixture-ancestor",
                        source_locator=VERIFIED_LOCATOR,
                        source_commit=baseline,
                    )
                ),
            }
        )

        reset_fixture(repo, baseline)
        results.append(
            {
                "id": "unconfigured-locator-is-rejected-atomically",
                "passed": rejected_without_manifest_mutation(
                    repo,
                    "SOURCE_LOCATOR_NOT_CONFIGURED_REMOTE",
                    release_id="fixture-wrong-locator",
                    source_locator="fixture://not-configured",
                    source_commit=baseline,
                    forbidden_output=VERIFIED_LOCATOR,
                ),
            }
        )

        reset_fixture(repo, baseline)
        readme = repo / ".agents" / "README.md"
        readme.write_bytes(readme.read_bytes() + b"\ntracked release drift\n")
        results.append(
            {
                "id": "tracked-release-drift-is-rejected-atomically",
                "passed": rejected_without_manifest_mutation(
                    repo,
                    "RELEASE_TREE_NOT_EXACT_HEAD",
                    release_id="fixture-tracked-drift",
                    source_locator=VERIFIED_LOCATOR,
                    source_commit=baseline,
                ),
            }
        )

        reset_fixture(repo, baseline)
        untracked = repo / ".agents" / "core" / "fixture-untracked.txt"
        untracked.write_text("untracked release-owned bytes\n", encoding="utf-8")
        results.append(
            {
                "id": "untracked-release-drift-is-rejected-atomically",
                "passed": rejected_without_manifest_mutation(
                    repo,
                    "RELEASE_TREE_NOT_EXACT_HEAD",
                    release_id="fixture-untracked-drift",
                    source_locator=VERIFIED_LOCATOR,
                    source_commit=baseline,
                ),
            }
        )

        reset_fixture(repo, baseline)
        readme = repo / ".agents" / "README.md"
        readme.write_bytes(readme.read_bytes() + b"\nworking baseline drift\n")
        process, payload = lifecycle_command(repo, "fixture-working-baseline")
        manifest = json.loads(manifest_path(repo).read_text(encoding="utf-8"))
        results.append(
            {
                "id": "dirty-release-tree-remains-available-as-working-baseline",
                "passed": bool(
                    process.returncode == 0
                    and payload.get("ok") is True
                    and manifest.get("provenance", {}).get("status") == "working-baseline"
                    and manifest.get("provenance", {}).get("source_commit") is None
                ),
            }
        )

        reset_fixture(repo, baseline)
        process, _ = lifecycle_command(
            repo,
            "fixture-consumer-check",
            source_locator=VERIFIED_LOCATOR,
            source_commit=baseline,
        )
        manifest = json.loads(manifest_path(repo).read_text(encoding="utf-8"))
        manifest["provenance"]["created_from_repository_head"] = "0" * 40
        manifest_path(repo).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        source_check = lifecycle.verify_release_tree(repo / ".agents")
        results.append(
            {
                "id": "consumer-rejects-mismatched-created-from-head",
                "passed": bool(
                    process.returncode == 0
                    and source_check.get("ok") is False
                    and source_check.get("trusted_for_apply") is False
                    and "SOURCE_PROVENANCE_INVALID"
                    in source_check.get("reason_codes", [])
                ),
            }
        )

    passed = sum(1 for result in results if result["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
