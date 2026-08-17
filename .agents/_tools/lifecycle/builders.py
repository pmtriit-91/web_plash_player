#!/usr/bin/env python3
"""Manifest, adapter-fingerprint, and lifecycle CLI builders."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from lifecycle.binding_validation import (
    adapter_reason_codes,
    expected_adapter_digests,
    validate_binding,
)
from lifecycle.core_validation import validate_skills, verify_core, verify_vendors
from lifecycle.health import doctor, verify_adapter
from lifecycle.release_tree import (
    FULL_COMMIT,
    collect_release_entries,
    ownership_policy,
    verified_release_provenance,
)
from lifecycle.shared import dump, git_output, load_json, utc_now
from lifecycle.update_planning import plan_update
from lifecycle.update_transaction import apply_update, rollback_update

ROOT = Path(__file__).resolve().parents[2]
VERSION = "9.1.0"
MANIFEST_PATH = ROOT / "_manifest" / "base-release-manifest.json"
BINDING_PATH = ROOT / "project" / "project-binding.json"
FINGERPRINT_PATH = ROOT / "project" / "adapter-fingerprint.json"
TEXT_SUFFIXES = {"", ".css", ".html", ".js", ".json", ".jsx", ".md", ".mjs", ".py", ".sh", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"}  # fmt: skip


# fmt: off
def purity_scan(entries: dict[str, dict[str, Any]], forbidden_tokens: list[str]) -> list[dict[str, str]]:
    tokens = sorted({token.strip().lower() for token in forbidden_tokens if token.strip()})
    if not tokens:
        return []
    findings: list[dict[str, str]] = []
    for relative, entry in entries.items():
        if entry.get("type") != "file":
            continue
        path = ROOT / relative
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 1024 * 1024:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for token in tokens:
            if token in content:
                findings.append({"path": relative, "token": token})
    return findings


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm:
        return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
    has_source_locator = bool(args.source_locator)
    has_source_commit = bool(args.source_commit)
    if has_source_locator != has_source_commit:
        return {
            "ok": False,
            "reason_codes": ["SOURCE_PROVENANCE_ARGUMENTS_INCOMPLETE"],
        }
    entries, unclassified = collect_release_entries()
    if unclassified:
        return {
            "ok": False,
            "reason_codes": ["UNCLASSIFIED_STABLE_PATH"],
            "unclassified": unclassified,
        }
    unsafe_symlinks = sorted(
        path
        for path, entry in entries.items()
        if entry.get("type") == "symlink" and entry.get("target_within_release") is not True
    )
    if unsafe_symlinks:
        return {
            "ok": False,
            "reason_codes": ["CORE_SYMLINK_OUTSIDE_RELEASE"],
            "unsafe_symlinks": unsafe_symlinks,
        }
    findings = purity_scan(entries, args.forbid_token or [])
    if findings:
        return {
            "ok": False,
            "reason_codes": ["RELEASE_PURITY_FAILED"],
            "findings": findings,
        }
    policy = ownership_policy()
    repository_head = git_output("rev-parse", "HEAD")
    provenance_status = "verified-release" if has_source_locator else "working-baseline"
    if provenance_status == "verified-release":
        provenance_check = verified_release_provenance(
            args.source_locator,
            args.source_commit,
            entries,
        )
        if not provenance_check["ok"]:
            return {
                "ok": False,
                "reason_codes": provenance_check["reason_codes"],
                "provenance_check": provenance_check,
            }
        repository_head = provenance_check["repository_head"]
    manifest = {
        "schema_version": 1,
        "agent_os_version": VERSION,
        "release_id": args.release_id,
        "created_at": utc_now(),
        "hash_algorithm": "sha256",
        "provenance": {
            "status": provenance_status,
            "source_locator": args.source_locator,
            "source_commit": args.source_commit,
            "created_from_repository_head": (
                args.source_commit
                if provenance_status == "verified-release"
                else repository_head
            ),
        },
        "excluded_scopes": [
            *policy.get("application_owned_scopes", []),
            *policy.get("runtime_scopes", []),
        ],
        "vendor_lock": "vendor/vendor-lock.json",
        "entries": [entries[path] for path in sorted(entries)],
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=MANIFEST_PATH.parent,
        prefix=".base-release-manifest.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(MANIFEST_PATH)
    return {
        "ok": True,
        "manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        "release_id": args.release_id,
        "provenance_status": provenance_status,
        "entries": len(entries),
    }


def build_adapter_fingerprint(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm:
        return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
    binding = load_json(BINDING_PATH, None)
    if not isinstance(binding, dict):
        return {"ok": False, "reason_codes": ["BINDING_SCHEMA_INVALID"]}
    errors, warnings = validate_binding(binding)
    if errors:
        return {
            "ok": False,
            "reason_codes": adapter_reason_codes(errors),
            "errors": errors,
            "warnings": warnings,
        }
    fingerprint = {
        "schema_version": 1,
        "project_id": binding.get("project_id"),
        "binding_schema_version": binding.get("schema_version"),
        "algorithm": "sha256",
        "digests": expected_adapter_digests(binding),
        "verified_at": binding.get("last_verified_at"),
        "verified_commit": binding.get("last_verified_commit"),
    }
    FINGERPRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=FINGERPRINT_PATH.parent,
        prefix=".adapter-fingerprint.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(fingerprint, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(FINGERPRINT_PATH)
    return {
        "ok": True,
        "fingerprint": FINGERPRINT_PATH.relative_to(ROOT).as_posix(),
        "project_id": binding.get("project_id"),
        "digests": fingerprint["digests"],
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS lifecycle engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    subparsers.add_parser("verify-core")
    subparsers.add_parser("verify-adapter")
    subparsers.add_parser("verify-vendors")
    subparsers.add_parser("validate-skills")

    update_parser = subparsers.add_parser("plan-update")
    update_parser.add_argument("--source", required=True)

    apply_parser = subparsers.add_parser("apply-update")
    apply_parser.add_argument("--source", required=True)
    apply_parser.add_argument("--plan-id", required=True)
    apply_parser.add_argument("--confirm", action="store_true")
    apply_parser.add_argument("--test-fail-after", type=int, default=0, help=argparse.SUPPRESS)

    rollback_parser = subparsers.add_parser("rollback-update")
    rollback_parser.add_argument("--transaction-id", required=True)
    rollback_parser.add_argument("--confirm", action="store_true")

    fingerprint_parser = subparsers.add_parser("build-adapter-fingerprint")
    fingerprint_parser.add_argument("--confirm", action="store_true")

    manifest_parser = subparsers.add_parser("build-manifest")
    manifest_parser.add_argument("--release-id", required=True)
    manifest_parser.add_argument("--source-locator")
    manifest_parser.add_argument("--source-commit")
    manifest_parser.add_argument("--forbid-token", action="append", default=[])
    manifest_parser.add_argument("--confirm", action="store_true")

    args = parser.parse_args()
    if args.command == "doctor":
        result = doctor()
    elif args.command == "verify-core":
        result = verify_core()
    elif args.command == "verify-adapter":
        result = verify_adapter()
    elif args.command == "verify-vendors":
        result = verify_vendors()
    elif args.command == "validate-skills":
        result = validate_skills()
    elif args.command == "plan-update":
        result = plan_update(args)
    elif args.command == "apply-update":
        result = apply_update(args)
    elif args.command == "rollback-update":
        result = rollback_update(args)
    elif args.command == "build-adapter-fingerprint":
        result = build_adapter_fingerprint(args)
    elif args.command == "build-manifest":
        if args.source_commit and not FULL_COMMIT.fullmatch(args.source_commit):
            result = {"ok": False, "reason_codes": ["SOURCE_COMMIT_INVALID"]}
        else:
            result = build_manifest(args)
    else:
        result = {"ok": False, "reason_codes": ["COMMAND_NOT_IMPLEMENTED"]}
    dump(result)
    sys.exit(0 if result.get("ok") else 2)
# fmt: on
