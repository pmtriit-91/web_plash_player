#!/usr/bin/env python3
"""Focused P1a2a checks for export portable-path collision admission."""

from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity_portability import (
    ContinuityPortabilityService,
    artifact_entry_id,
)
from agent_os_continuity_portability_export import ContinuityExportMixin
from continuity_portability.test_support import (
    prepare_fixture,
    rehash_export_inventory,
)


class InventoryHarness:
    export_inventory = ContinuityExportMixin.export_inventory

    @staticmethod
    def document(_relative: str) -> dict[str, list[Any]]:
        return {"types": []}

    @staticmethod
    def add_inventory_source(
        inventory: dict[str, dict[str, Any]],
        path: str,
        *,
        privacy_class: str,
        retention_class: str,
        reference_id: str,
        required: bool,
        force_verify_only: bool = False,
    ) -> list[dict[str, Any]]:
        del required
        item = inventory.setdefault(
            path,
            {
                "content": path.encode("utf-8"),
                "privacy_class": privacy_class,
                "retention_class": retention_class,
                "canonical_owner": "core" if force_verify_only else "application",
                "restore_mode": "verify-only" if force_verify_only else "replace",
                "reference_ids": set(),
            },
        )
        item["reference_ids"].add(reference_id)
        return []

    @staticmethod
    def context_closure(
        _inventory: dict[str, dict[str, Any]], _reference_id: str
    ) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def recovery_closure(
        _inventory: dict[str, dict[str, Any]], _maximum: int
    ) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def privacy_error(_content: bytes, _path: str) -> None:
        return None


def producer_issues(paths: tuple[str, str]) -> list[dict[str, Any]]:
    references = [
        {
            "source": {"path": path},
            "requirement": "required",
            "record_type": "context-manifest" if index == 0 else "task-ledger",
            "privacy_class": "project-internal",
            "retention_class": "critical-active",
            "reference_id": f"fixture-{index}",
        }
        for index, path in enumerate(paths)
    ]
    preflight = {
        "catalog": {"references": references},
        "policy": {
            "bounds": {
                "max_entries": 64,
                "max_file_bytes": 4096,
                "max_total_bytes": 65536,
            }
        },
    }
    _entries, issues = InventoryHarness().export_inventory(preflight)
    return issues


def manifest_with_paths(
    manifest: dict[str, Any], paths: tuple[str, str]
) -> dict[str, Any]:
    forged = deepcopy(manifest)
    template = next(
        item
        for item in forged["entries"]
        if item["canonical_path"] == "docs/roadmap.md"
    )
    forged["entries"] = [
        item
        for item in forged["entries"]
        if item["canonical_path"] != "docs/roadmap.md"
    ]
    for path in paths:
        entry = deepcopy(template)
        entry["canonical_path"] = path
        entry["entry_id"] = artifact_entry_id(path, entry["present"], entry["sha256"])
        entry["storage_path"] = (
            f"files/{entry['entry_id']}.bin" if entry["present"] else None
        )
        forged["entries"].append(entry)
    rehash_export_inventory(forged)
    return forged


def add_result(
    results: list[dict[str, Any]], identifier: str, passed: bool, **details: Any
) -> None:
    results.append({"id": identifier, "passed": passed, **details})


def main() -> None:
    results: list[dict[str, Any]] = []
    collision_code = "PORTABILITY_SOURCE_PATH_COLLISION"
    for identifier, paths in (
        ("producer-rejects-case-only-collision", ("docs/Guide.md", "docs/guide.md")),
        (
            "producer-rejects-nfc-nfd-collision",
            ("docs/café.md", "docs/cafe\u0301.md"),
        ),
    ):
        issues = producer_issues(paths)
        add_result(
            results,
            identifier,
            any(item.get("code") == collision_code for item in issues),
            issues=issues,
        )
    distinct_issues = producer_issues(("docs/alpha.md", "docs/beta.md"))
    add_result(
        results,
        "producer-preserves-distinct-paths",
        all(item.get("code") != collision_code for item in distinct_issues),
        issues=distinct_issues,
    )
    with tempfile.TemporaryDirectory(prefix="aos15-w6-p1a2a-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        built = service.build_export_manifest()
        manifest = built.get("manifest", {})
        add_result(
            results,
            "current-export-manifest-remains-valid",
            built.get("ok") is True
            and service.validate_export_manifest(manifest) == [],
        )
        for identifier, paths in (
            (
                "manifest-rejects-case-only-collision",
                ("docs/Guide.md", "docs/guide.md"),
            ),
            (
                "manifest-rejects-nfc-nfd-collision",
                ("docs/café.md", "docs/cafe\u0301.md"),
            ),
        ):
            errors = service.validate_export_manifest(
                manifest_with_paths(manifest, paths)
            )
            add_result(
                results,
                identifier,
                errors == ["PORTABILITY_MANIFEST_ENTRY_PATH_COLLISION"],
                errors=errors,
            )
        errors = service.validate_export_manifest(
            manifest_with_paths(manifest, ("docs/alpha.md", "docs/beta.md"))
        )
        add_result(
            results,
            "manifest-preserves-distinct-paths",
            errors == [],
            errors=errors,
        )
    passed = sum(1 for item in results if item["passed"])
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
