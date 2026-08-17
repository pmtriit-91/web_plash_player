#!/usr/bin/env python3
"""Focused P1b2 checks for staged-catalog restore-plan dependency order."""

from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash, json_bytes, sha256_bytes
from agent_os_continuity_portability import (
    RESTORE_PLAN_FIELDS,
    ContinuityPortabilityService,
)
from continuity_portability.test_support import (
    export_bundle,
    initialize_w4,
    prepare_fixture,
    rehash_restore_plan,
)

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def staged_inputs(
    base: Path,
    catalog: dict[str, Any],
    mappings: list[tuple[str, str, list[str]]],
    identifier: str,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    payload = json_bytes(catalog)
    digest = sha256_bytes(payload)
    stage = base / identifier
    storage = stage / "files/catalog.bin"
    storage.parent.mkdir(parents=True)
    storage.write_bytes(payload)
    entries = [
        {
            "entry_id": entry_id,
            "canonical_path": path,
            "reference_ids": references,
        }
        for entry_id, path, references in mappings
    ]
    entries.append(
        {
            "entry_id": "catalog-entry",
            "canonical_path": ".agents/project/context/continuity.json",
            "present": True,
            "restore_mode": "verify-only",
            "bytes": len(payload),
            "sha256": digest,
            "storage_path": "files/catalog.bin",
            "reference_ids": ["continuity-catalog"],
        }
    )
    manifest = {
        "project_id": catalog["project_id"],
        "record_type_registry": deepcopy(catalog["record_type_registry"]),
        "recovery_profile": deepcopy(catalog["recovery_profile"]),
        "catalog": {
            "schema_version": catalog["schema_version"],
            "catalog_revision": catalog["catalog_revision"],
            "catalog_sha256": digest,
            "migration_extensions_sha256": canonical_hash(
                catalog.get("migration_extensions", [])
            ),
        },
        "entries": entries,
    }
    targets = [
        {"entry_id": entry_id, "path": path} for entry_id, path, _references in mappings
    ]
    return stage, manifest, targets


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": passed, **details})

    with tempfile.TemporaryDirectory(prefix="aos15-w6-p1b2-") as temporary:
        base = Path(temporary)
        root = prepare_fixture(base / "fixture")
        service = ContinuityPortabilityService(root)
        catalog = json.loads((root / "project/context/continuity.json").read_text())
        next(
            item
            for item in catalog["references"]
            if item["reference_id"] == "current-status"
        )["dependencies"] = [
            {"relation": "generated-from", "target_reference_id": "roadmap"}
        ]
        (root / "project/context/continuity.json").write_bytes(json_bytes(catalog))
        initialize_w4().W3.commit_all(root.parent, "bind dependency fixture")
        mappings = [
            ("current", "docs/context/current-status.md", ["current-status"]),
            ("roadmap", "docs/roadmap.md", ["roadmap"]),
        ]

        stage, manifest, targets = staged_inputs(base, catalog, mappings, "valid-stage")
        order, errors = service.restore_target_execution_order(stage, manifest, targets)
        check(
            "staged-catalog-projects-dependency-first-order",
            order == ["roadmap", "current"] and errors == [],
            order=order,
            errors=errors,
        )

        malformed = deepcopy(catalog)
        next(
            item
            for item in malformed["references"]
            if item["reference_id"] == "roadmap"
        ).pop("dependencies")
        stage, manifest, targets = staged_inputs(
            base, malformed, mappings, "malformed-stage"
        )
        order, errors = service.restore_target_execution_order(stage, manifest, targets)
        check(
            "malformed-staged-catalog-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_CATALOG_INVALID"],
        )

        stage, manifest, targets = staged_inputs(
            base, catalog, mappings, "hash-mismatch-stage"
        )
        manifest["catalog"]["catalog_sha256"] = "0" * 64
        order, errors = service.restore_target_execution_order(stage, manifest, targets)
        check(
            "unbound-staged-catalog-hash-fails-closed",
            order is None and errors == ["PORTABILITY_RESTORE_CATALOG_INVALID"],
        )

        dangling = deepcopy(catalog)
        next(
            item
            for item in dangling["references"]
            if item["reference_id"] == "current-status"
        )["dependencies"] = [
            {"relation": "generated-from", "target_reference_id": "missing-ref"}
        ]
        stage, manifest, targets = staged_inputs(
            base, dangling, mappings, "dangling-stage"
        )
        order, errors = service.restore_target_execution_order(stage, manifest, targets)
        check(
            "dangling-staged-dependency-fails-closed",
            order is None and errors == ["PORTABILITY_DEPENDENCY_REFERENCE_MISSING"],
        )

        cyclic = deepcopy(catalog)
        next(
            item for item in cyclic["references"] if item["reference_id"] == "roadmap"
        )["dependencies"].append(
            {"relation": "requires", "target_reference_id": "current-status"}
        )
        stage, manifest, targets = staged_inputs(base, cyclic, mappings, "cyclic-stage")
        order, errors = service.restore_target_execution_order(stage, manifest, targets)
        check(
            "cyclic-staged-dependency-fails-closed",
            order is None and errors == ["PORTABILITY_DEPENDENCY_CYCLE"],
        )

        ambiguous = [
            ("one", "docs/one.md", ["roadmap"]),
            ("two", "docs/two.md", ["roadmap"]),
        ]
        stage, manifest, targets = staged_inputs(
            base, catalog, ambiguous, "ambiguous-stage"
        )
        order, errors = service.restore_target_execution_order(stage, manifest, targets)
        check(
            "ambiguous-reference-target-mapping-fails-closed",
            order is None and errors == ["PORTABILITY_DEPENDENCY_TARGET_AMBIGUOUS"],
        )

        destination = base / "bundle"
        service, _applied = export_bundle(root, destination)
        roadmap = root.parent / "docs/roadmap.md"
        current = root.parent / "docs/context/current-status.md"
        roadmap.write_bytes(b"# drifted roadmap\n")
        current.write_bytes(b"# drifted current status\n")
        before = {roadmap: roadmap.read_bytes(), current: current.read_bytes()}
        planned = service.plan_restore(destination)
        plan = planned.get("plan", {})
        paths_by_id = {
            item["entry_id"]: item["path"] for item in plan.get("targets", [])
        }
        target_paths = [item["path"] for item in plan.get("targets", [])]
        execution_paths = [
            paths_by_id[item] for item in plan.get("target_execution_order", [])
        ]
        check(
            "plan-keeps-canonical-inventory-and-separate-execution-order",
            planned.get("ok") is True
            and target_paths == sorted(target_paths)
            and execution_paths
            == ["docs/roadmap.md", "docs/context/current-status.md"],
            target_paths=target_paths,
            execution_paths=execution_paths,
        )

        forged = deepcopy(plan)
        forged["target_execution_order"] = list(
            reversed(forged["target_execution_order"])
        )
        rehash_restore_plan(forged)
        check(
            "forged-execution-order-is-recomputed-and-rejected",
            service.validate_restore_plan(forged, forged["plan_id"])
            == ["PORTABILITY_RESTORE_DEPENDENCY_ORDER_INVALID"],
        )

        schema = json.loads(
            (
                SOURCE_ROOT / "core/contracts/continuity-restore-plan.schema.json"
            ).read_text()
        )
        missing = deepcopy(plan)
        missing.pop("target_execution_order")
        rehash_restore_plan(missing)
        check(
            "schema-runtime-field-parity-and-required-order",
            set(schema["required"]) == RESTORE_PLAN_FIELDS
            and schema["properties"]["target_execution_order"]["uniqueItems"] is True
            and service.validate_restore_plan(missing, missing["plan_id"])
            == ["PORTABILITY_RESTORE_PLAN_FIELDS_INVALID"],
        )

        plans_before = {item.name for item in service.plans.iterdir()}
        with patch.object(
            service,
            "restore_target_execution_order",
            return_value=(None, ["PORTABILITY_DEPENDENCY_CYCLE"]),
        ):
            rejected = service.plan_restore(destination)
        check(
            "dependency-preflight-rejects-before-plan-or-target-write",
            rejected.get("reason_codes") == ["PORTABILITY_DEPENDENCY_CYCLE"]
            and plans_before == {item.name for item in service.plans.iterdir()}
            and all(path.read_bytes() == content for path, content in before.items()),
        )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
