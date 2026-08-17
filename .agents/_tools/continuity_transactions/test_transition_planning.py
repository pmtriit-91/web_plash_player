#!/usr/bin/env python3
"""Ten focused checks for continuity transition planning and generation-two plans."""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_continuity_transactions")
owner = importlib.import_module("continuity_transactions.transition_planning")
from agent_os_context_memory import canonical_hash
from continuity_transactions.test_support import W3, make_fixture, write_json

METHODS = (
    "refresh_catalog",
    "migration_target",
    "migrate_catalog",
    "change_set",
    "create_plan",
    "plan_initialize",
    "plan_refresh",
    "plan_migrate",
)
METHOD_HASHES = {
    "refresh_catalog": "c7f19417b096d293473dbf7c5ffe6a6dece54f71d9c7a6f7140848e45d30a160",
    "migration_target": "ad6ad5411e8b832591dbbd9eca544d8fb4f3988ca0543b9707fe689965886a27",
    "migrate_catalog": "d3673e537faca24e9da3f8db3f4cef1dff7de780a0b2a18f2fbc0e743e15a108",
    "change_set": "a8baa3331f166d6d947aa7edc022e24a76725c4e40964580e64266122e3baeee",
    "create_plan": "f163cae6dbb63ba7daf22d6a0a3c4b02c601f22578e74ad51f36d6c55847d43d",
    "plan_initialize": "7d5f66973f648935867506012a4c9db439b4e2dbf6a8b97db9cc502909a4ce90",
    "plan_refresh": "947628a00b91ab9e162e5413eef42bebc74d2ce6ddb21b0f30d7e6428aa8a292",
    "plan_migrate": "b066aee67763407cbd86118820cb5217ec497acb0f2186982d3056a424653174",
}
SIGNATURES = {
    "refresh_catalog": "(self, catalog: 'dict[str, Any]') -> 'tuple[dict[str, Any] | None, list[str]]'",
    "migration_target": "(self, source: 'dict[str, Any]') -> 'tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]'",
    "migrate_catalog": "(self, source: 'dict[str, Any]') -> 'tuple[dict[str, Any] | None, list[str]]'",
    "change_set": "(self, desired: 'dict[str, bytes | None]') -> 'tuple[list[dict[str, Any]], str]'",
    "create_plan": "(self, operation: 'str', desired: 'dict[str, bytes | None]', *, before_catalog: 'Any', after_catalog: 'Any', source_paths: 'set[str]', metadata: 'dict[str, Any] | None' = None, expiry_seconds: 'int' = 900) -> 'dict[str, Any]'",
    "plan_initialize": "(self) -> 'dict[str, Any]'",
    "plan_refresh": "(self, operation: 'str' = 'refresh') -> 'dict[str, Any]'",
    "plan_migrate": "(self) -> 'dict[str, Any]'",
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
    owner_path = "_tools/continuity_transactions/transition_planning.py"
    required = {"_tools/continuity_transactions/contracts.py", "_tools/agent_os_continuity.py",
                "_tools/agent_os_context_memory.py", "self:catalog-inventory-initialization-validation-contracts"}
    check("topology-routes-transition-planning-and-self-dependencies",
          owner_path in entries[topology["public_facade"]]["depends_on"]
          and entries[owner_path]["focused_shard"] == "_tools/continuity_transactions/test_transition_planning.py"
          and required <= set(entries[owner_path]["depends_on"]))
    owner_source = (TOOLS_ROOT / "continuity_transactions/transition_planning.py").read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    nodes = method_nodes(owner_source, "TransitionPlanningMixin")
    check("eight-method-family-has-one-one-way-source-owner",
          "agent_os_continuity_transactions" not in owner_source and tuple(nodes) == METHODS
          and method_nodes(facade_source, "ContinuityTransactionService") == {})
    service, mixin = facade.ContinuityTransactionService, owner.TransitionPlanningMixin
    check("public-identities-and-mro-are-preserved",
          service.__mro__[0] is service and mixin in service.__mro__[1:] and service.__mro__[-1] is object
          and all(getattr(service, name) is getattr(mixin, name) for name in METHODS))
    hashes = {name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
              for name, node in nodes.items()}
    check("method-ast-and-signatures-are-preserved", hashes == METHOD_HASHES
          and all(str(inspect.signature(getattr(mixin, name))) == SIGNATURES[name] for name in METHODS))
    calls = {item.func.attr for node in nodes.values() for item in ast.walk(node)
             if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
             and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"}
    required_calls = {"source_descriptor", "migration_chain", "migration_target", "critical_set",
                      "render_exact_diff", "source_inventory", "initial_catalog", "projection_for",
                      "create_plan"}
    instance = service.__new__(service)
    instance.target_bytes = lambda relative: b"before"
    instance.render_exact_diff = lambda changes: "patched"
    check("self-dispatch-and-instance-monkeypatch-remain-open", required_calls <= calls
          and instance.change_set({"x": b"after"})[1] == "patched")
    instance.migration_chain = lambda source, target: (None, ["CONTINUITY_MIGRATION_CHAIN_NOT_FOUND"])
    check("migration-chain-failure-is-preserved-by-compatibility-entrypoint",
          instance.migrate_catalog({"schema_version": 0})
          == (None, ["CONTINUITY_MIGRATION_CHAIN_NOT_FOUND"]))
    instance.target_bytes = lambda relative: None
    check("plan-entrypoints-preserve-missing-catalog-precedence",
          instance.plan_refresh() == {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_MISSING"]}
          and instance.plan_migrate() == {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_MISSING"]})

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3a2b-v0-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        source = json.loads((root / facade.CATALOG_REL).read_text(encoding="utf-8"))
        source["schema_version"] = 0
        source.pop("catalog_revision")
        source.pop("migration_extensions")
        write_json(root / facade.CATALOG_REL, source)
        before_bytes = (root / facade.CATALOG_REL).read_bytes()
        service_instance = service(root)
        planned = service_instance.plan_migrate()
        plan = planned.get("plan", {})
        catalog_change = next(
            (item for item in plan.get("changes", []) if item["path"] == facade.CATALOG_REL),
            None,
        )
        target = (
            json.loads(base64.b64decode(catalog_change["after_base64"]))
            if catalog_change is not None
            else {}
        )
        path = plan.get("metadata", {}).get("migration_path", [])
        check("draft-plan-runs-full-chain-in-memory-and-binds-ordered-evidence",
              planned.get("ok") is True
              and [(item["source_generation"], item["target_generation"]) for item in path]
              == [(0, 1), (1, 2)]
              and plan["metadata"]["migration_path_sha256"] == canonical_hash(path)
              and plan["metadata"]["unknown_fields_sha256"]
              == canonical_hash([item["unknown_fields_sha256"] for item in path])
              and target.get("schema_version") == 2
              and target.get("catalog_revision") == 1
              and target.get("references") == source["references"]
              and len(target.get("migration_extensions", [])) == 2
              and service_instance.validate_plan(plan, plan["plan_id"]) == []
              and (root / facade.CATALOG_REL).read_bytes() == before_bytes)

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3a2b-v1-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        source = json.loads((root / facade.CATALOG_REL).read_text(encoding="utf-8"))
        source["schema_version"] = 1
        source.pop("migration_extensions")
        write_json(root / facade.CATALOG_REL, source)
        service_instance = service(root)
        direct = service_instance.plan_migrate()
        direct_path = direct.get("plan", {}).get("metadata", {}).get("migration_path", [])
        plan_count = len(list(service_instance.plans.glob("*.json")))
        rejected_source = deepcopy(source)
        rejected_source["future_unknown"] = True
        write_json(root / facade.CATALOG_REL, rejected_source)
        rejected_service = service(root)
        rejected = rejected_service.plan_migrate()
        check("generation-one-uses-one-hop-and-unknown-fields-fail-before-plan-write",
              direct.get("ok") is True and len(direct_path) == 1
              and direct_path[0]["source_generation"] == 1
              and direct_path[0]["target_generation"] == 2
              and rejected.get("reason_codes")
              == ["CONTINUITY_MIGRATION_UNKNOWN_FIELDS_UNSUPPORTED"]
              and len(list(rejected_service.plans.glob("*.json"))) == plan_count)

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3c1-refresh-v2-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        source = json.loads((root / facade.CATALOG_REL).read_text(encoding="utf-8"))
        source["schema_version"] = 2
        source["migration_extensions"] = []
        write_json(root / facade.CATALOG_REL, source)
        roadmap = root.parent / "docs/roadmap.md"
        roadmap.write_text("# Generation-two refresh\n", encoding="utf-8")
        W3.commit_all(root.parent, "update roadmap for generation-two refresh")
        refresh_service = service(root)
        refreshed, refresh_errors = refresh_service.refresh_catalog(source)
        check("refresh-accepts-generation-two-and-rejects-future-generation",
              refresh_errors == [] and refreshed is not None
              and refreshed.get("schema_version") == 2
              and refreshed.get("catalog_revision") == source["catalog_revision"] + 1
              and refreshed.get("migration_extensions") == []
              and refresh_service.refresh_catalog({"schema_version": 3})
              == (None, ["CONTINUITY_GENERATION_UNSUPPORTED"]))
    result = {"ok": all(item["passed"] for item in cases),
              "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
