#!/usr/bin/env python3
"""Executable AOS-15 W3 adversarial fixtures for the read-only continuity doctor."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_os_context_memory import ContextMemoryService
from agent_os_continuity import (
    CORE_REGISTRY_REL,
    PROFILE_REGISTRY_REL,
    doctor,
    sha256_file,
)
from agent_os_continuity import ROOT as SOURCE_ROOT

STAMP = "2026-07-27T00:00:00Z"
PROJECT_ID = "fixture-project"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def git(project: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def git_blob(project: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{path}"],
        cwd=project,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def commit_all(project: Path, message: str) -> str:
    git(project, "add", ".")
    git(
        project,
        "-c",
        "user.name=Agent OS Fixture",
        "-c",
        "user.email=fixture@agent-os.local",
        "commit",
        "-m",
        message,
    )
    return git(project, "rev-parse", "HEAD")


def source(reference_id: str, record_type: str, profile_role: str, record_id: str, path: str,
           digest: str | None, commit: str | None, schema_id: str | None,
           schema_version: int | None, *, revision: str | int | None = None,
           requirement: str = "required", load_policy: str = "boot",
           provider: str, retention: str = "critical-active") -> dict[str, Any]:
    return {
        "reference_id": reference_id,
        "record_type": record_type,
        "profile_role": profile_role,
        "record_id": record_id,
        "record_revision": revision,
        "requirement": requirement,
        "lifecycle": "active",
        "load_policy": load_policy,
        "authority_provider": provider,
        "source": {
            "path": path,
            "sha256": digest,
            "git_commit": commit,
            "schema_id": schema_id,
            "schema_version": schema_version,
        },
        "dependencies": [],
        "supersedes": [],
        "retention_class": retention,
        "privacy_class": "project-internal",
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def make_fixture(base: Path) -> tuple[Path, dict[str, Any]]:
    project = base / "fixture"
    root = project / ".agents"
    project.mkdir(parents=True)
    git(project, "init", "--initial-branch=main")
    root.joinpath("project/context/handoffs").mkdir(parents=True)
    root.joinpath("skills/project-memory").mkdir(parents=True)
    root.joinpath("_manifest").mkdir(parents=True)
    root.joinpath("memory").mkdir(parents=True)
    root.joinpath("core/contracts").mkdir(parents=True)
    project.joinpath("docs/context").mkdir(parents=True)
    project.joinpath("evidence").mkdir(parents=True)

    shutil.copy2(SOURCE_ROOT / CORE_REGISTRY_REL, root / CORE_REGISTRY_REL)
    shutil.copy2(SOURCE_ROOT / PROFILE_REGISTRY_REL, root / PROFILE_REGISTRY_REL)
    shutil.copy2(
        SOURCE_ROOT / "core/contracts/ownership-policy.json",
        root / "core/contracts/ownership-policy.json",
    )
    write_json(root / "project/project-binding.json", {"schema_version": 1, "project_id": PROJECT_ID})
    write_json(
        root / "_manifest/base-release-manifest.json",
        {
            "schema_version": 1,
            "agent_os_version": "9.1.0",
            "release_id": "fixture-release",
            "hash_algorithm": "sha256",
            "provenance": {
                "status": "working-baseline",
                "source_locator": None,
                "source_commit": None,
                "created_from_repository_head": None,
            },
            "entries": [
                {
                    "path": relative,
                    "type": "file",
                    "sha256": hashlib.sha256(root.joinpath(relative).read_bytes()).hexdigest(),
                }
                for relative in (
                    "core/contracts/ownership-policy.json",
                    CORE_REGISTRY_REL,
                    PROFILE_REGISTRY_REL,
                )
            ],
        },
    )
    stores: dict[str, bytes] = {}
    for tier in ("hot", "warm", "cold"):
        path = root / f"project/context/{tier}.json"
        write_json(path, {"schema_version": 1, "project_id": PROJECT_ID, "tier": tier, "records": []})
        stores[tier] = path.read_bytes()
    task_path = root / "project/context/active-tasks.json"
    write_json(task_path, {"schema_version": 1, "project_id": PROJECT_ID, "tasks": []})
    root.joinpath("skills/project-memory/SKILL.md").write_bytes(
        ContextMemoryService(root).render_projection(
            PROJECT_ID,
            {
                tier: json.loads(content.decode("utf-8"))
                for tier, content in stores.items()
            },
            json.loads(task_path.read_text(encoding="utf-8")),
            16384,
        )
    )
    manifest = {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "repository": {"remote_aliases": ["fixture/project"]},
        "authority_order": [
            "binding",
            "git-evidence",
            "user-confirmed",
            "project-decision",
            "research-only",
            "historical",
        ],
        "sources": [
            {
                "id": f"{tier}-context",
                "tier": tier,
                "path": f"project/context/{tier}.json",
                "owner": "application",
                "format": "context-store-json",
                "load_policy": "boot" if tier == "hot" else "just-in-time" if tier == "warm" else "explicit-only",
                "authority": "git-evidence" if tier == "hot" else "project-decision" if tier == "warm" else "research-only",
                "content_sha256": hashlib.sha256(stores[tier]).hexdigest(),
                "canonical_keys": ["fixture"],
            }
            for tier in ("hot", "warm", "cold")
        ],
        "active_task_ledger": "project/context/active-tasks.json",
        "active_task_ledger_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
        "handoff_directory": "project/context/handoffs",
        "projection": "skills/project-memory/SKILL.md",
        "budgets": {
            "hot_max_bytes": 32768,
            "warm_max_bytes": 131072,
            "cold_max_records": 5000,
            "projection_max_bytes": 16384,
        },
        "refreshed_at": STAMP,
        "refreshed_commit": None,
    }
    write_json(root / "project/context/context-manifest.json", manifest)
    project.joinpath("docs/roadmap.md").write_bytes(b"# Roadmap\n")
    project.joinpath("docs/context/current-status.md").write_bytes(
        b"# Current status\n"
    )
    write_json(
        project / "evidence/not-a-handoff.json",
        {
            "schema_version": 2,
            "id": "handoff-fixture",
            "to_owner": None,
            "verified_outcomes": ["Fixture outcome"],
        },
    )
    first_commit = commit_all(project, "fixture sources")

    def digest(relative: str) -> str:
        return hashlib.sha256(project.joinpath(relative).read_bytes()).hexdigest()

    references = [
        source(
            "binding",
            "project-binding",
            "project-binding",
            PROJECT_ID,
            ".agents/project/project-binding.json",
            digest(".agents/project/project-binding.json"),
            first_commit,
            "project-binding",
            1,
            provider="binding-doctor",
        ),
        source(
            "release",
            "agent-os-release",
            "agent-os-release",
            "fixture-release",
            ".agents/_manifest/base-release-manifest.json",
            digest(".agents/_manifest/base-release-manifest.json"),
            first_commit,
            "base-release-manifest",
            1,
            revision="9.1.0",
            provider="core-manifest-validator",
        ),
        source(
            "genesis",
            "project-genesis",
            "project-genesis",
            "genesis-fixture-project",
            ".agents/project/genesis.json",
            None,
            None,
            "project-genesis",
            1,
            revision=None,
            requirement="state-aware",
            provider="genesis-doctor",
        ),
        source(
            "context",
            "context-manifest",
            "context-manifest",
            PROJECT_ID,
            ".agents/project/context/context-manifest.json",
            digest(".agents/project/context/context-manifest.json"),
            first_commit,
            "context-manifest",
            1,
            provider="context-memory-doctor",
        ),
        source(
            "roadmap",
            "roadmap",
            "roadmap",
            "roadmap",
            "docs/roadmap.md",
            digest("docs/roadmap.md"),
            first_commit,
            None,
            None,
            load_policy="just-in-time",
            provider="governance-document-validator",
        ),
        source(
            "current-status",
            "current-status",
            "current-status",
            "current-status",
            "docs/context/current-status.md",
            digest("docs/context/current-status.md"),
            first_commit,
            None,
            None,
            provider="governance-document-validator",
        ),
        source(
            "tasks",
            "active-task-ledger",
            "active-task-ledger",
            PROJECT_ID,
            ".agents/project/context/active-tasks.json",
            digest(".agents/project/context/active-tasks.json"),
            first_commit,
            "active-task-ledger",
            1,
            provider="task-ledger-validator",
        ),
    ]
    catalog = {
        "schema_version": 2,
        "project_id": PROJECT_ID,
        "catalog_id": "continuity-fixture-project",
        "catalog_revision": 1,
        "record_type_registry": {
            "registry_id": "universal-continuity-record-types",
            "registry_version": 1,
            "registry_sha256": sha256_file(root / CORE_REGISTRY_REL),
        },
        "recovery_profile": {
            "profile_id": "universal-project-continuity",
            "profile_version": 1,
            "profile_sha256": sha256_file(root / PROFILE_REGISTRY_REL),
        },
        "migration_extensions": [],
        "references": references,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    write_json(root / "project/context/continuity.json", catalog)
    commit_all(project, "fixture catalog")
    return root, catalog


def derive(
    mutator: Callable[[Path, dict[str, Any]], None] | None = None,
    *,
    genesis_state: str | None = None,
    context_state: str | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent-os-continuity-") as temporary:
        root, catalog = make_fixture(Path(temporary))
        if mutator:
            mutator(root, catalog)
        write_json(root / "project/context/continuity.json", catalog)
        genesis_patch = (
            patch("agent_os_continuity.genesis_doctor", return_value={"state": genesis_state})
            if genesis_state
            else nullcontext()
        )
        context_patch = (
            patch.object(
                __import__("agent_os_continuity").ContextMemoryService,
                "doctor",
                return_value={"state": context_state},
            )
            if context_state
            else nullcontext()
        )
        with genesis_patch, context_patch:
            return doctor(root)


def reference(catalog: dict[str, Any], reference_id: str) -> dict[str, Any]:
    return next(item for item in catalog["references"] if item["reference_id"] == reference_id)


def has_code(result: dict[str, Any], code: str) -> bool:
    return code in result.get("reason_codes", [])


def file_snapshot(project: Path) -> dict[str, str]:
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(project).parts
    }
