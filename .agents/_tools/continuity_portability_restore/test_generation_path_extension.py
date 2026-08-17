#!/usr/bin/env python3
"""Focused P2a4b0 checks for restore generation and migration evidence."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash, json_bytes, sha256_bytes
from continuity_portability.test_support import export_bundle, prepare_fixture

MANIFEST_NAME = "continuity-export-manifest.json"
CATALOG_PATH = ".agents/project/context/continuity.json"


def extension(source: int, migration_id: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    return {
        "source_generation": source,
        "migration_id": migration_id,
        "unknown_fields_sha256": canonical_hash(fields),
        "fields": fields,
    }


def staged_variant(
    base_bundle: Path,
    destination: Path,
    extensions: list[dict[str, Any]],
    *,
    catalog_generation: int = 2,
    bind_extensions: bool = True,
) -> tuple[Path, dict[str, Any]]:
    shutil.copytree(base_bundle, destination)
    manifest_path = destination / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog_entry = next(
        item for item in manifest["entries"] if item["canonical_path"] == CATALOG_PATH
    )
    catalog_path = destination / catalog_entry["storage_path"]
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["schema_version"] = catalog_generation
    catalog["migration_extensions"] = deepcopy(extensions)
    payload = json_bytes(catalog)
    digest = sha256_bytes(payload)
    catalog_path.write_bytes(payload)
    catalog_entry["bytes"] = len(payload)
    catalog_entry["sha256"] = digest
    manifest["catalog"]["catalog_sha256"] = digest
    if bind_extensions:
        manifest["catalog"]["migration_extensions_sha256"] = canonical_hash(extensions)
    return destination, manifest


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": passed, **details})

    with tempfile.TemporaryDirectory(prefix="aos15-w6-p2a4b0-") as temporary:
        base = Path(temporary)
        root = prepare_fixture(base / "fixture")
        bundle = base / "bundle"
        service, _applied = export_bundle(root, bundle)

        def analyze(
            identifier: str,
            extensions: list[dict[str, Any]],
            *,
            catalog_generation: int = 2,
            bind_extensions: bool = True,
        ) -> tuple[list[str] | None, list[str], dict[str, Any]]:
            staged, manifest = staged_variant(
                bundle,
                base / identifier,
                extensions,
                catalog_generation=catalog_generation,
                bind_extensions=bind_extensions,
            )
            order, errors = service.restore_target_execution_order(staged, manifest, [])
            return order, errors, manifest

        order, errors, _manifest = analyze("empty-history", [])
        check(
            "generation-two-empty-history-is-admitted",
            order == [] and errors == [],
            order=order,
            errors=errors,
        )

        one_hop = [extension(1, "continuity-catalog-v1-to-v2")]
        order, errors, _manifest = analyze("one-hop", one_hop)
        check(
            "registered-one-to-two-path-is-admitted",
            order == [] and errors == [],
            errors=errors,
        )

        two_hops = [
            extension(0, "continuity-catalog-draft-v0-to-v1"),
            extension(1, "continuity-catalog-v1-to-v2"),
        ]
        order, errors, _manifest = analyze("two-hops", two_hops)
        check(
            "registered-zero-to-one-to-two-path-is-admitted",
            order == [] and errors == [],
            errors=errors,
        )

        staged, manifest = staged_variant(
            bundle, base / "extension-hash-mismatch", one_hop
        )
        manifest["catalog"]["migration_extensions_sha256"] = "0" * 64
        order, errors = service.restore_target_execution_order(staged, manifest, [])
        check(
            "extension-envelope-hash-mismatch-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_EXTENSION_INVALID"],
            errors=errors,
        )

        order, errors, manifest = analyze(
            "generation-mismatch", [], catalog_generation=1
        )
        check(
            "payload-generation-mismatch-is-distinct",
            order is None and errors == ["PORTABILITY_RESTORE_GENERATION_INVALID"],
            errors=errors,
            descriptor_generation=manifest["catalog"]["schema_version"],
        )

        order, errors, _manifest = analyze(
            "unregistered-hop", [extension(1, "continuity-catalog-unknown")]
        )
        check(
            "unregistered-hop-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_MIGRATION_PATH_INVALID"],
            errors=errors,
        )

        order, errors, _manifest = analyze(
            "wrong-source",
            [extension(0, "continuity-catalog-v1-to-v2")],
        )
        check(
            "registered-id-with-wrong-source-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_MIGRATION_PATH_INVALID"],
            errors=errors,
        )

        order, errors, _manifest = analyze("reversed-path", list(reversed(two_hops)))
        check(
            "reversed-path-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_MIGRATION_PATH_INVALID"],
            errors=errors,
        )

        order, errors, _manifest = analyze(
            "truncated-path",
            [extension(0, "continuity-catalog-draft-v0-to-v1")],
        )
        check(
            "path-not-reaching-target-generation-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_MIGRATION_PATH_INVALID"],
            errors=errors,
        )

        registry_path = root / "memory/continuity-migrations.json"
        registry_path.write_text("{}\n", encoding="utf-8")
        order, errors, _manifest = analyze("invalid-registry", one_hop)
        check(
            "invalid-target-migration-registry-fails-closed",
            order is None
            and errors == ["PORTABILITY_RESTORE_MIGRATION_REGISTRY_INVALID"],
            errors=errors,
        )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
