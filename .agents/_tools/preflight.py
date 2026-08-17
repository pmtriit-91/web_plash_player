#!/usr/bin/env python3
"""Dependency-free preflight and routing-path validation for Agent OS V9."""

from __future__ import annotations

import argparse
import fnmatch
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_os_capabilities import validate_catalog
from agent_os_capacity import INPUT_MAX_BYTES, check_growth
from agent_os_domain import settings_snapshot
from agent_os_research import validate_registry as validate_research_registry

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
VERSION = "9.1.0"
IDE_POLICY = ROOT / "_ide" / "ide-policy.json"
CAPABILITY_REGISTRY = ROOT / "routing" / "capability-registry.json"
WORKFLOW_REGISTRY = ROOT / "routing" / "workflow-registry.json"
AGENTIGNORE = ROOT / ".agentignore"
REQUIRED_AGENTIGNORE = {
    "_runtime/",
    "_telemetry/*.jsonl",
    "__pycache__/",
    "*.pyc",
    "*.zip",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def git_staged() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line for line in result.stdout.splitlines() if line]


def validate_paths() -> dict[str, Any]:
    capabilities = load_json(CAPABILITY_REGISTRY, {})
    workflows = load_json(WORKFLOW_REGISTRY, {})
    ide_policy = load_json(IDE_POLICY, {})
    errors: list[dict[str, Any]] = []

    for source, data in (
        ("capability-registry", capabilities),
        ("workflow-registry", workflows),
        ("ide-policy", ide_policy),
    ):
        if data.get("version") != VERSION:
            errors.append(
                {
                    "code": "VERSION_MISMATCH",
                    "source": source,
                    "expected": VERSION,
                    "actual": data.get("version"),
                }
            )

    for capability_id, capability in capabilities.get("capabilities", {}).items():
        for relative in capability.get("load", []):
            if not (ROOT / relative).exists():
                errors.append({"code": "CAPABILITY_PATH_MISSING", "id": capability_id, "path": relative})

    for skill_id, skill in capabilities.get("vendor_skills", {}).items():
        relative = skill.get("path", "")
        if not relative or not (ROOT / relative / "SKILL.md").is_file():
            errors.append({"code": "VENDOR_SKILL_MISSING", "id": skill_id, "path": relative})

    registered: set[str] = set()
    for workflow_id, workflow in workflows.get("workflows", {}).items():
        relative = workflow.get("path", "")
        registered.add(relative)
        required = {"path", "mode", "triggers", "load_conditions", "forbidden_when"}
        missing_fields = sorted(required - set(workflow))
        if missing_fields:
            errors.append({"code": "WORKFLOW_SCHEMA_INVALID", "id": workflow_id, "missing": missing_fields})
        if not relative or not (ROOT / relative).is_file():
            errors.append({"code": "WORKFLOW_PATH_MISSING", "id": workflow_id, "path": relative})
    physical = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "workflows").glob("*.md")
    }
    for relative in sorted(physical - registered):
        errors.append({"code": "WORKFLOW_UNREGISTERED", "path": relative})
    for relative in sorted(registered - physical):
        errors.append({"code": "WORKFLOW_STALE", "path": relative})

    patterns = {
        line.strip()
        for line in AGENTIGNORE.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    } if AGENTIGNORE.is_file() else set()
    missing_patterns = sorted(REQUIRED_AGENTIGNORE - patterns)
    if missing_patterns:
        errors.append({"code": "AGENTIGNORE_INCOMPLETE", "missing": missing_patterns})

    required_files = [
        "core/contracts/ownership-policy.json",
        "core/contracts/project-binding.schema.json",
        "core/contracts/adapter-fingerprint.schema.json",
        "core/contracts/project-genesis.schema.json",
        "core/contracts/project-genesis-confirmation-receipt.schema.json",
        "core/contracts/project-genesis-projection.schema.json",
        "_tools/agent_os_lifecycle.py",
        "_tools/agent_os_genesis.py",
        "_tools/agent_os_genesis_transactions.py",
        "project-template/genesis.json",
        "vendor/vendor-lock.json",
    ]
    for relative in required_files:
        if not (ROOT / relative).is_file():
            errors.append({"code": "LIFECYCLE_FILE_MISSING", "path": relative})
    catalog = validate_catalog()
    if not catalog.get("ok"):
        errors.append({"code": "CAPABILITY_CATALOG_INVALID", "details": catalog.get("errors", [])})
    research = validate_research_registry()
    if not research.get("ok"):
        errors.append({"code": "RESEARCH_REGISTRY_INVALID", "details": research.get("errors", [])})
    settings = settings_snapshot()
    if not settings.get("ok"):
        errors.append({"code": "PROJECT_SETTINGS_INVALID", "details": settings.get("errors", [])})
    return {"ok": not errors, "version": VERSION, "errors": errors}


def check_mode(args: argparse.Namespace) -> dict[str, Any]:
    policy = load_json(IDE_POLICY, {})
    mode_policy = policy.get("modes", {}).get(args.mode, {})
    max_files = int(mode_policy.get("max_files", 0) or 0)
    files = list(dict.fromkeys([*(args.files or []), *(git_staged() if args.scan_git_staged else [])]))
    errors: list[str] = []
    warnings: list[str] = []
    if max_files and len(files) > max_files:
        errors.append(f"{args.mode} allows at most {max_files} target files; received {len(files)}")
    blocked_patterns = policy.get("blocked_generic_scan_paths", [])
    for relative in files:
        normalized = relative.replace("\\", "/").lstrip("./")
        for pattern in blocked_patterns:
            clean = pattern.lstrip("./")
            if clean.endswith("/") and normalized.startswith(clean):
                errors.append(f"blocked path: {relative}")
            elif fnmatch.fnmatch(normalized, clean):
                errors.append(f"blocked path: {relative}")
    if not files:
        warnings.append("No target files were supplied; file-boundary validation was limited.")
    return {
        "ok": not errors,
        "version": VERSION,
        "mode": args.mode,
        "file_count": len(files),
        "max_files": max_files,
        "errors": errors,
        "warnings": warnings,
    }


def check_capacity_envelope(path: Path) -> dict[str, Any]:
    """Run the canonical growth primitive against a caller-supplied envelope."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > INPUT_MAX_BYTES:
            raise OSError("capacity envelope must be a bounded regular file")
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "ok": False,
            "state": "BLOCKED",
            "reason_codes": ["CAPACITY_ENVELOPE_INVALID"],
            "offending_paths": [],
            "measurements": [],
            "generated": [],
        }
    return check_growth(PROJECT_ROOT, envelope)


def merge_capacity_admission(result: dict[str, Any], capacity: dict[str, Any]) -> dict[str, Any]:
    """Attach primitive admission without changing its reason/path semantics."""
    result["capacity_admission"] = capacity
    result["ok"] = bool(result.get("ok")) and bool(capacity.get("ok"))
    if not capacity.get("ok"):
        result["reason_codes"] = list(capacity.get("reason_codes", []))
        result["offending_paths"] = list(capacity.get("offending_paths", []))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS preflight")
    parser.add_argument("--mode", choices=["FAST", "STANDARD", "DEEP"])
    parser.add_argument("--files", nargs="*", default=[])
    parser.add_argument("--capability", default="")
    parser.add_argument("--scan-git-staged", action="store_true")
    parser.add_argument("--validate-paths", action="store_true")
    parser.add_argument("--capacity-envelope", type=Path)
    args = parser.parse_args()
    if args.validate_paths:
        result = validate_paths()
    elif args.mode:
        result = check_mode(args)
    elif args.capacity_envelope:
        result = {"ok": True, "version": VERSION, "errors": [], "warnings": []}
    else:
        result = {"ok": False, "version": VERSION, "errors": ["--mode or --validate-paths is required"]}
    if args.capacity_envelope:
        result = merge_capacity_admission(
            result, check_capacity_envelope(args.capacity_envelope)
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
