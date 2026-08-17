#!/usr/bin/env python3
"""Shared fixtures for the AOS-15 W5 continuity portability test shards."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_os_context_memory import canonical_hash, json_bytes, receipt_hash
from agent_os_continuity_portability import (
    POLICY_AGENT_REL,
    ContinuityPortabilityService,
    artifact_id,
)
from continuity_transactions import test_support as transaction_support

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def initialize_w4() -> Any:
    """Return the directly imported transaction fixture compatibility module."""
    return transaction_support


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def create_directory_redirect(link: Path, target: Path) -> bool:
    """Create a real directory redirect; inability to do so is not a passing test."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        if os.name != "nt":
            return False
    result = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/s",
            "/c",
            f'mklink /J "{link}" "{target}"',
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0 and link.exists()


def remove_directory_redirect(link: Path) -> None:
    try:
        if link.is_symlink():
            link.unlink()
        elif os.name == "nt" and link.exists():
            os.rmdir(link)
    except OSError:
        pass


class ReparseStat:
    """Portable stand-in for a Windows stat result carrying the reparse bit."""

    def __init__(self, original: os.stat_result):
        self._original = original
        self.st_file_attributes = getattr(original, "st_file_attributes", 0) | 0x400

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def prepare_fixture(
    base: Path,
    *,
    historical: bool = False,
    payload_mode: str | None = None,
) -> Path:
    root = transaction_support.make_fixture(base, configured=True)
    shutil.copy2(SOURCE_ROOT / POLICY_AGENT_REL, root / POLICY_AGENT_REL)
    manifest_path = root / "_manifest/base-release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"] = [
        item for item in manifest["entries"] if item["path"] != POLICY_AGENT_REL
    ]
    manifest["entries"].append(
        {
            "path": POLICY_AGENT_REL,
            "type": "file",
            "sha256": digest(root / POLICY_AGENT_REL),
        }
    )
    manifest["entries"] = sorted(manifest["entries"], key=lambda item: item["path"])
    write_json(manifest_path, manifest)
    release_commit = transaction_support.W3.commit_all(
        root.parent, "add W5 retention policy"
    )

    catalog_path = root / "project/context/continuity.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    release = next(
        item
        for item in catalog["references"]
        if item["record_type"] == "agent-os-release"
    )
    release["source"]["sha256"] = digest(manifest_path)
    release["source"]["git_commit"] = release_commit

    changed_sources: list[tuple[str, bytes]] = []
    if payload_mode == "portable-bytes":
        changed_sources = [
            ("docs/roadmap.md", b"# Roadmap\r\n\r\nCRLF stays exact.\r\n"),
            (
                "docs/context/current-status.md",
                b"\x00\x01\x02portable-binary\xff\xfe\n",
            ),
        ]
    elif payload_mode == "secret":
        changed_sources = [
            (
                "docs/roadmap.md",
                b"# Roadmap\n\nsk-1234567890abcdefghijklmnop\n",
            )
        ]
    elif payload_mode == "reasoning":
        changed_sources = [
            (
                "docs/roadmap.md",
                b"# Roadmap\n\nchain of thought: private trace\n",
            )
        ]
    elif payload_mode == "raw-field":
        changed_sources = [
            (
                "docs/roadmap.md",
                b"# Roadmap\n\nraw_prompt: private prompt payload\n",
            )
        ]
    if historical:
        changed_sources.append(("docs/roadmap-history.md", b"# Historical roadmap\n"))
    if changed_sources:
        (root.parent / ".gitattributes").write_text(
            "docs/roadmap.md -text\n"
            "docs/context/current-status.md -text\n"
            "docs/roadmap-history.md -text\n",
            encoding="utf-8",
        )
    for relative, content in changed_sources:
        path = root.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    source_commit = (
        transaction_support.W3.commit_all(root.parent, "add W5 source fixtures")
        if changed_sources
        else release_commit
    )
    by_id = {item["reference_id"]: item for item in catalog["references"]}
    for reference_id, relative in (
        ("roadmap", "docs/roadmap.md"),
        ("current-status", "docs/context/current-status.md"),
    ):
        reference = by_id[reference_id]
        reference["source"]["sha256"] = digest(root.parent / relative)
        reference["source"]["git_commit"] = source_commit
        reference["record_revision"] = digest(root.parent / relative)
    if historical:
        active = by_id["roadmap"]
        previous = deepcopy(active)
        previous["reference_id"] = "roadmap-history"
        previous["record_id"] = "roadmap-history"
        previous["record_revision"] = digest(root.parent / "docs/roadmap-history.md")
        previous["lifecycle"] = "superseded"
        previous["source"]["path"] = "docs/roadmap-history.md"
        previous["source"]["sha256"] = digest(root.parent / "docs/roadmap-history.md")
        previous["source"]["git_commit"] = source_commit
        previous["retention_class"] = "critical-history"
        previous["supersedes"] = []
        active["supersedes"] = ["roadmap-history"]
        catalog["references"].append(previous)
        catalog["references"] = sorted(
            catalog["references"], key=lambda item: item["reference_id"]
        )
    write_json(catalog_path, catalog)
    transaction_support.W3.commit_all(root.parent, "bind W5 fixture catalog")
    return root


def export_bundle(
    root: Path, destination: Path
) -> tuple[ContinuityPortabilityService, dict[str, Any]]:
    service = ContinuityPortabilityService(root)
    planned = service.plan_export(destination)
    if not planned.get("ok"):
        raise RuntimeError(f"export plan failed: {planned}")
    applied = service.apply_portability(
        planned["plan"]["plan_id"],
        True,
        expected_operation="export",
    )
    if not applied.get("ok"):
        raise RuntimeError(f"export apply failed: {applied}")
    return service, applied


def rehash_manifest(manifest: dict[str, Any]) -> None:
    manifest["bundle_id"] = artifact_id(
        manifest,
        "continuity-export-",
        "bundle_id",
    )
    manifest["content_sha256"] = receipt_hash(manifest)


def rehash_export_inventory(manifest: dict[str, Any]) -> None:
    manifest["entries"] = sorted(
        manifest["entries"],
        key=lambda item: item["canonical_path"],
    )
    manifest["entry_count"] = len(manifest["entries"])
    manifest["total_bytes"] = sum(item["bytes"] for item in manifest["entries"])
    manifest["inventory_sha256"] = canonical_hash(manifest["entries"])
    rehash_manifest(manifest)


def rehash_restore_plan(plan: dict[str, Any]) -> None:
    plan["plan_id"] = canonical_hash(
        {
            key: value
            for key, value in plan.items()
            if key not in {"plan_id", "content_sha256"}
        }
    )[:24]
    plan["content_sha256"] = receipt_hash(plan)


def run_cli(arguments: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(SOURCE_ROOT / "_tools/agent_os_cli.py"), *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(result.stderr or str(exc)) from exc
