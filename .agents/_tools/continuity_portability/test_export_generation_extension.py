#!/usr/bin/env python3
"""Focused P2a4a checks for export generation and extension admission."""

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

from agent_os_context_memory import canonical_hash, json_bytes
from agent_os_continuity_portability import ContinuityPortabilityService
from agent_os_continuity_portability_export import CATALOG_DESCRIPTOR_FIELDS
from continuity_portability.test_support import prepare_fixture, rehash_manifest


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    with tempfile.TemporaryDirectory(prefix="aos15-w6-p2a4a-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        first = service.build_export_manifest()
        second = service.build_export_manifest()
        manifest = first.get("manifest", {})
        descriptor = manifest.get("catalog", {})
        catalog = json.loads(
            (root / "project/context/continuity.json").read_text(encoding="utf-8")
        )

        check(
            "generation-two-export-builds",
            first.get("ok") is True and descriptor.get("schema_version") == 2,
        )
        check(
            "catalog-descriptor-field-set-is-exact",
            set(descriptor) == CATALOG_DESCRIPTOR_FIELDS,
        )
        check(
            "migration-extension-envelope-is-canonically-bound",
            descriptor.get("migration_extensions_sha256")
            == canonical_hash(catalog.get("migration_extensions", [])),
        )
        check(
            "generation-descriptor-is-deterministic",
            second.get("ok") is True
            and json_bytes(first["manifest"]) == json_bytes(second["manifest"]),
        )
        destination = Path(temporary) / "generation-two-export"
        check(
            "generation-two-export-plan-is-admitted",
            service.plan_export(destination).get("ok") is True
            and not destination.exists(),
        )

        generation_one = deepcopy(manifest)
        generation_one["catalog"]["schema_version"] = 1
        rehash_manifest(generation_one)
        check(
            "legacy-generation-descriptor-fails-closed",
            service.validate_export_manifest(generation_one)
            == ["PORTABILITY_MANIFEST_CONTRACTS_INVALID"],
        )

        missing_extension = deepcopy(manifest)
        del missing_extension["catalog"]["migration_extensions_sha256"]
        rehash_manifest(missing_extension)
        check(
            "missing-extension-binding-fails-closed",
            service.validate_export_manifest(missing_extension)
            == ["PORTABILITY_MANIFEST_CONTRACTS_INVALID"],
        )

        extra_extension = deepcopy(manifest)
        extra_extension["catalog"]["migration_extensions"] = []
        rehash_manifest(extra_extension)
        check(
            "inline-extension-payload-is-not-admitted",
            service.validate_export_manifest(extra_extension)
            == ["PORTABILITY_MANIFEST_CONTRACTS_INVALID"],
        )

        invalid_extension = deepcopy(manifest)
        invalid_extension["catalog"]["migration_extensions_sha256"] = "invalid"
        rehash_manifest(invalid_extension)
        check(
            "malformed-extension-binding-fails-closed",
            service.validate_export_manifest(invalid_extension)
            == ["PORTABILITY_MANIFEST_CONTRACTS_INVALID"],
        )

        forged_extension = deepcopy(manifest)
        forged_extension["catalog"]["migration_extensions_sha256"] = "0" * 64
        rehash_manifest(forged_extension)
        provenance_issues = service.validate_export_git_provenance(forged_extension)
        check(
            "rehash-cannot-forge-extension-provenance",
            service.validate_export_manifest(forged_extension) == []
            and {item["code"] for item in provenance_issues}
            == {"PORTABILITY_SOURCE_AUTHORITY_MISMATCH"},
        )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
