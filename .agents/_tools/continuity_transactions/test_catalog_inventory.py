#!/usr/bin/env python3
"""Ten focused checks for continuity catalog inventory and migration chains."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_continuity_transactions")
owner = importlib.import_module("continuity_transactions.catalog_inventory")
METHODS = (
    "migration_registry",
    "migration_chain",
    "source_inventory",
    "critical_set",
    "catalog_source_paths",
    "head_document",
    "source_descriptor",
)
METHOD_HASHES = {
    "migration_registry": "619f43128bdc4657295db5a92c66ce1e8a779e096e80768d77a096c81eecbbdd",
    "migration_chain": "753b8b60ff541b2c3fcbd3df99bf5f349336a809dbc16f7920c5c2dd8cd10931",
    "source_inventory": "fc6b4c39dbb43a696925b29f5e83719bd998e96f68e299a40b5948f4714ee611",
    "critical_set": "c66b277c306359699486a43273d754d10926f85e2d9e9ee3bae48b580538a570",
    "catalog_source_paths": "ee9a90676337ed506e507df1864edb7ff6bcdb5317072c4892423af51d716a23",
    "head_document": "347c3c74b6d1e3f1ad58969d1d758e61cc53cb35e30ff29d63039c3915301e01",
    "source_descriptor": "429dfd53b6252b9ba9a176fc623b26d729ead48b4fa57d0f3c9ae042db102673",
}
SIGNATURES = {
    "migration_registry": "(self) -> 'tuple[dict[tuple[int, int], dict[str, Any]], list[str]]'",
    "migration_chain": "(self, source_generation: 'int', target_generation: 'int') -> 'tuple[list[dict[str, Any]] | None, list[str]]'",
    "source_inventory": "(self, paths: 'set[str]') -> 'tuple[list[dict[str, Any]], str]'",
    "critical_set": "(catalog: 'Any') -> 'list[str]'",
    "catalog_source_paths": "(catalog: 'Any') -> 'set[str]'",
    "head_document": "(self, relative: 'str') -> 'tuple[bytes | None, Any]'",
    "source_descriptor": "(self, relative: 'str', schema_id: 'str | None', schema_version: 'int | None', *, missing_allowed: 'bool' = False) -> 'tuple[dict[str, Any] | None, Any, list[str]]'",
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
    owner_path = "_tools/continuity_transactions/catalog_inventory.py"
    required = {"_tools/continuity_transactions/contracts.py", "_tools/agent_os_context_memory.py",
                "_tools/agent_os_continuity_migration_chain.py",
                "self:path-head-project_path-git_blob-git_path_clean"}
    check("topology-routes-catalog-inventory-and-self-dependencies",
          owner_path in entries[topology["public_facade"]]["depends_on"]
          and entries[owner_path]["focused_shard"] == "_tools/continuity_transactions/test_catalog_inventory.py"
          and required <= set(entries[owner_path]["depends_on"]))
    owner_source = (TOOLS_ROOT / "continuity_transactions/catalog_inventory.py").read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    nodes = method_nodes(owner_source, "CatalogInventoryMixin")
    check("seven-method-family-has-one-one-way-source-owner",
          "agent_os_continuity_transactions" not in owner_source and tuple(nodes) == METHODS
          and method_nodes(facade_source, "ContinuityTransactionService") == {})
    service, mixin = facade.ContinuityTransactionService, owner.CatalogInventoryMixin
    check("public-identities-and-mro-are-preserved",
          service.__mro__[0] is service and mixin in service.__mro__[1:] and service.__mro__[-1] is object
          and all(getattr(service, name) is getattr(mixin, name) for name in METHODS))
    hashes = {name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
              for name, node in nodes.items()}
    check("method-ast-signatures-and-static-descriptors-are-preserved",
          hashes == METHOD_HASHES
          and all(str(inspect.signature(getattr(mixin, name))) == SIGNATURES[name] for name in METHODS)
          and all(isinstance(mixin.__dict__[name], staticmethod)
                  for name in ("critical_set", "catalog_source_paths")))

    calls = {item.func.attr for node in nodes.values() for item in ast.walk(node)
             if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
             and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"}
    instance = service.__new__(service)
    instance.head = lambda: "a" * 40
    check("self-dispatch-and-instance-monkeypatch-remain-open",
          {"path", "head", "project_path", "git_blob", "git_path_clean", "head_document",
           "migration_registry"} <= calls
          and instance.head() == "a" * 40)

    valid_entry = {field: None for field in facade.MIGRATION_FIELDS}
    valid_entry.update(migration_id="v0-v1", source_generation=0, target_generation=1,
                       provider="builtin:continuity-catalog-draft-v0-to-v1", source_fields=["x"],
                       preserve_reference_bytes=True, reject_unknown_fields=True, requires_backup=True)
    generation_two = dict(valid_entry, migration_id="v1-v2", source_generation=1,
                          target_generation=2, provider="builtin:continuity-catalog-v1-to-v2")
    registry = {"schema_version": 1, "registry_id": "universal-continuity-migrations",
                "registry_version": 2, "migrations": [valid_entry, generation_two]}
    owner.load_json = lambda path: registry
    instance.path = lambda relative: Path(relative)
    duplicate = dict(registry, migrations=[valid_entry, valid_entry])
    ok_registry = instance.migration_registry()
    owner.load_json = lambda path: duplicate
    check("migration-registry-valid-and-duplicate-generation-fails-closed",
          ok_registry == ({(0, 1): valid_entry, (1, 2): generation_two}, [])
          and instance.migration_registry()[1] == ["CONTINUITY_MIGRATION_ENTRY_INVALID"])

    owner.load_json = lambda path: registry
    chain, chain_errors = instance.migration_chain(0, 2)
    check("registered-two-hop-chain-is-exposed-in-source-order",
          chain_errors == [] and chain is not None
          and [item["migration_id"] for item in chain] == ["v0-v1", "v1-v2"])
    wrong_provider = dict(generation_two, provider="builtin:unknown")
    owner.load_json = lambda path: dict(registry, migrations=[valid_entry, wrong_provider])
    invalid_provider = instance.migration_chain(0, 2)
    owner.load_json = lambda path: dict(registry, migrations=[valid_entry])
    missing_path = instance.migration_chain(0, 2)
    check("invalid-provider-and-missing-chain-fail-closed",
          invalid_provider == (None, ["CONTINUITY_MIGRATION_ENTRY_INVALID"])
          and missing_path == (None, ["CONTINUITY_MIGRATION_CHAIN_NOT_FOUND"]))

    catalog = {"references": [
        {"reference_id": "required", "requirement": "required", "lifecycle": "active",
         "source": {"path": "docs/required.md"}},
        {"reference_id": "advisory", "requirement": "advisory", "lifecycle": "active"}],
        "project_record_type_registry": {"path": ".agents/project/registry.json"}}
    check("critical-set-and-source-paths-preserve-policy",
          instance.critical_set(catalog) == ["required"]
          and {"docs/required.md", ".agents/project/registry.json"} <= instance.catalog_source_paths(catalog))

    instance.head_document = lambda relative: (b'{"schema_version":1}', {"schema_version": 1})
    descriptor, document, errors = instance.source_descriptor("source.json", "source", 1)
    instance.head_document = lambda relative: (None, None)
    missing = instance.source_descriptor("missing.json", None, None, missing_allowed=True)
    check("source-descriptor-committed-and-optional-missing-parity",
          descriptor == {"path": "source.json", "sha256": owner.sha256_bytes(b'{"schema_version":1}'),
                         "git_commit": "a" * 40, "schema_id": "source", "schema_version": 1}
          and document == {"schema_version": 1} and errors == []
          and missing == ({"path": "missing.json", "sha256": None, "git_commit": None,
                           "schema_id": None, "schema_version": None}, None, []))
    result = {"ok": all(item["passed"] for item in cases),
              "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
