#!/usr/bin/env python3
"""Nine focused checks for continuity catalog initialization extraction."""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_continuity_transactions")
owner = importlib.import_module("continuity_transactions.catalog_initialization")
support = importlib.import_module("continuity_transactions.test_support")
METHODS = ("initial_catalog", "validate_target", "projection_for")
METHOD_HASHES = {
    "initial_catalog": "daf1d8129c5e0c773e627f845adafe2eabf57dc3ef9e65cb55967cf4999c2eea",
    "validate_target": "84ea3cf3779339a4aee870a99ae1b593e6efd8bbb1f3e91301283b3ad37d8235",
    "projection_for": "29461ff43716e79309e5d2e91aa6b78550de61b01acaf8ddae6baa230bc7e69b",
}
SIGNATURES = {
    "initial_catalog": "(self) -> 'tuple[dict[str, Any] | None, list[str]]'",
    "validate_target": "(self, catalog: 'dict[str, Any]') -> 'tuple[dict[str, Any] | None, list[str]]'",
    "projection_for": "(self, catalog: 'dict[str, Any]') -> 'tuple[bytes | None, dict[str, Any] | None, list[str]]'",
}


# fmt: off
def method_nodes(source: str, class_name: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in METHODS}

def main() -> None:
    cases: list[dict[str, Any]] = []
    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    topology = json.loads((TOOLS_ROOT / "continuity_transactions/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    owner_path = "_tools/continuity_transactions/catalog_initialization.py"
    required = {"_tools/continuity_transactions/contracts.py", "_tools/continuity_transactions/catalog_inventory.py",
                "_tools/agent_os_continuity.py", "_tools/agent_os_context_memory.py",
                "self:binding-path-source_descriptor-validate_target"}
    check("topology-routes-catalog-initialization-and-self-dependencies",
          owner_path in entries[topology["public_facade"]]["depends_on"]
          and entries[owner_path]["focused_shard"] == "_tools/continuity_transactions/test_catalog_initialization.py"
          and required <= set(entries[owner_path]["depends_on"]))
    owner_source = (TOOLS_ROOT / "continuity_transactions/catalog_initialization.py").read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    nodes = method_nodes(owner_source, "CatalogInitializationMixin")
    check("three-method-family-has-one-one-way-source-owner",
          "agent_os_continuity_transactions" not in owner_source and tuple(nodes) == METHODS
          and method_nodes(facade_source, "ContinuityTransactionService") == {})
    service, mixin = facade.ContinuityTransactionService, owner.CatalogInitializationMixin
    check("public-identities-and-mro-are-preserved",
          service.__mro__[0] is service and mixin in service.__mro__[1:] and service.__mro__[-1] is object
          and all(getattr(service, name) is getattr(mixin, name) for name in METHODS))
    hashes = {name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
              for name, node in nodes.items()}
    check("method-ast-and-signatures-are-preserved",
          hashes == METHOD_HASHES
          and all(str(inspect.signature(getattr(mixin, name))) == SIGNATURES[name] for name in METHODS))
    calls = {item.func.attr for node in nodes.values() for item in ast.walk(node)
             if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
             and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"}
    instance = service.__new__(service)
    instance.validate_target = lambda catalog: ({"projection_preview": {"project_id": "patched"}}, [])
    check("self-dispatch-and-instance-monkeypatch-remain-open",
          {"binding", "path", "source_descriptor", "validate_target"} <= calls
          and json.loads(instance.projection_for({})[0]) == {"project_id": "patched"})
    instance.validate_target = mixin.validate_target.__get__(instance, service)

    instance.binding = dict
    check("initial-catalog-rejects-missing-binding",
          instance.initial_catalog() == (None, ["PROJECT_BINDING_REQUIRED"]))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        registry, profile = root / "registry.json", root / "profile.json"
        registry.write_bytes(b"registry")
        profile.write_bytes(b"profile")
        instance.binding = lambda: {"project_id": "project-a"}
        instance.now = lambda: datetime(2026, 1, 2, tzinfo=timezone.utc)
        instance.path = lambda relative: registry if relative == facade.REGISTRY_REL else profile
        instance.source_descriptor = lambda relative, schema_id, schema_version, missing_allowed=False: (
            {"path": relative, "sha256": "a" * 64, "git_commit": "b" * 40,
             "schema_id": schema_id, "schema_version": schema_version},
            {"release_id": "release-a", "agent_os_version": "9.1.0", "project_id": "project-a",
             "refreshed_commit": "c" * 40}, [])
        catalog, errors = instance.initial_catalog()
    check("initial-catalog-preserves-seven-reference-contract",
          errors == [] and catalog is not None and catalog["project_id"] == "project-a"
          and catalog["schema_version"] == 2 and catalog["migration_extensions"] == []
          and len(catalog["references"]) == 7 and catalog["catalog_revision"] == 1)

    with tempfile.TemporaryDirectory() as directory:
        root = support.make_fixture(Path(directory), configured=False)
        service = facade.ContinuityTransactionService(root)
        plan = service.plan_initialize()
        changes = {change["path"]: change for change in plan.get("plan", {}).get("changes", [])}
        catalog_change = changes.get(facade.CATALOG_REL, {})
        planned_catalog = json.loads(base64.b64decode(catalog_change.get("after_base64", "e30=")))
        check("generation-two-initialize-plan-is-valid-and-does-not-write-canonical-targets",
              plan.get("ok") is True and plan["plan"]["operation"] == "initialize"
              and plan["plan"]["metadata"]["source_generation"] is None
              and plan["plan"]["metadata"]["target_generation"] == 2
              and planned_catalog.get("schema_version") == 2
              and planned_catalog.get("migration_extensions") == []
              and not (root / facade.CATALOG_REL).exists()
              and not (root / facade.PROJECTION_REL).exists())

    owner.validate_catalog_shape = lambda catalog: [{"code": "SHAPE"}, {"code": "SHAPE"}]
    owner.validate_reference_shape = lambda reference, index: [{"code": "REFERENCE"}]
    check("target-validation-preserves-deduplicated-reason-order",
          instance.validate_target({"references": [{}]}) == (None, ["SHAPE", "REFERENCE"]))
    result = {"ok": all(item["passed"] for item in cases),
              "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
