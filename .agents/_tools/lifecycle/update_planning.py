"""Read-only release update inventory and planning contracts."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Any

from lifecycle.release_tree import (
    classify,
    manifest_entries,
    matches_scope,
    ownership_policy,
    verify_release_tree,
)
from lifecycle.shared import (
    canonical_sha256,
    git_output,
    load_json,
    sha256_bytes,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent
MANIFEST_PATH = ROOT / "_manifest" / "base-release-manifest.json"
PROTECTED_APPLICATION_SCOPES = (
    "project/**",
    "skills/project-memory/**",
    "skills/project-local/**",
)


# fmt: off
def collect_application_entries(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(root).as_posix()
        if not any(matches_scope(relative, scope) for scope in PROTECTED_APPLICATION_SCOPES):
            continue
        if path.is_symlink():
            target = os.readlink(path)
            entries[relative] = {
                "path": relative,
                "type": "symlink",
                "sha256": sha256_bytes(target.encode("utf-8")),
                "target": target,
            }
        else:
            entries[relative] = {
                "path": relative,
                "type": "file",
                "sha256": sha256_file(path),
            }
    return entries


def dirty_agent_paths() -> dict[str, list[str]]:
    try:
        process = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", ".agents"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = process.stdout if process.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        output = ""
    policy = ownership_policy()
    grouped: dict[str, list[str]] = {"release": [], "application": [], "runtime": [], "unclassified": []}
    for line in output.splitlines():
        raw = line[3:] if len(line) >= 4 else line
        candidates = raw.split(" -> ") if " -> " in raw else [raw]
        for candidate in candidates:
            normalized = candidate.strip().strip('"').replace("\\", "/")
            if normalized.startswith(".agents/"):
                normalized = normalized[len(".agents/") :]
            owner = classify(normalized, policy)
            if owner == "manifest":
                owner = "release"
            grouped.setdefault(owner, []).append(normalized)
    return {name: sorted(set(paths)) for name, paths in grouped.items()}


def plan_update(args: argparse.Namespace) -> dict[str, Any]:
    source = verify_release_tree(Path(args.source))
    source_entries = source.pop("manifest_entries", {})
    if not source.get("ok"):
        return {
            "ok": False,
            "reason_codes": ["SOURCE_RELEASE_INVALID", *source.get("reason_codes", [])],
            "source": source,
            "writes_performed": False,
        }

    current_manifest = load_json(MANIFEST_PATH, None)
    if not isinstance(current_manifest, dict):
        return {
            "ok": False,
            "reason_codes": ["CURRENT_MANIFEST_MISSING"],
            "source": source,
            "writes_performed": False,
        }
    current_entries, schema_errors = manifest_entries(current_manifest)
    if schema_errors:
        return {
            "ok": False,
            "reason_codes": ["CURRENT_MANIFEST_SCHEMA_INVALID"],
            "schema_errors": schema_errors,
            "source": source,
            "writes_performed": False,
        }

    added = sorted(set(source_entries) - set(current_entries))
    removed = sorted(set(current_entries) - set(source_entries))
    modified = sorted(
        path
        for path in set(source_entries) & set(current_entries)
        if source_entries[path].get("type") != current_entries[path].get("type")
        or source_entries[path].get("sha256") != current_entries[path].get("sha256")
        or source_entries[path].get("target") != current_entries[path].get("target")
    )
    dirty = dirty_agent_paths()
    application_entries = collect_application_entries()
    blockers: list[str] = []
    if not source.get("trusted_for_apply"):
        blockers.append("SOURCE_PROVENANCE_UNVERIFIED")
    if dirty.get("release"):
        blockers.append("DIRTY_RELEASE_PATHS")
    if dirty.get("unclassified"):
        blockers.append("UNCLASSIFIED_DIRTY_PATHS")

    protected_inventory = canonical_sha256(
        [application_entries[path] for path in sorted(application_entries)]
    )
    source_manifest_path = Path(source["root"]) / "_manifest" / "base-release-manifest.json"
    plan_inputs = {
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "target_manifest_sha256": sha256_file(MANIFEST_PATH),
        "target_git_head": git_output("rev-parse", "HEAD"),
        "release_diff": {"added": added, "modified": modified, "removed": removed},
        "protected_inventory_sha256": protected_inventory,
    }
    plan_id = canonical_sha256(plan_inputs)[:24]
    return {
        "ok": True,
        "mode": "read-only-plan",
        "plan_id": plan_id,
        "plan_inputs": plan_inputs,
        "ready_to_apply": not blockers,
        "apply_supported": True,
        "reason_codes": blockers,
        "source": source,
        "target": {
            "agent_os_version": current_manifest.get("agent_os_version"),
            "release_id": current_manifest.get("release_id"),
            "entries": len(current_entries),
        },
        "release_diff": {"added": added, "modified": modified, "removed": removed},
        "dirty_paths": dirty,
        "protected_application": {
            "scopes": list(PROTECTED_APPLICATION_SCOPES),
            "entries": len(application_entries),
            "inventory_sha256": protected_inventory,
        },
        "writes_performed": False,
    }
# fmt: on
