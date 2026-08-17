#!/usr/bin/env python3
"""Ten focused checks for continuity transaction plan and path validation."""

from __future__ import annotations

import ast
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
owner = importlib.import_module("continuity_transactions.plan_validation")
from agent_os_context_memory import canonical_hash, json_bytes, receipt_hash
from continuity_transactions.test_support import make_fixture, write_json

METHODS = (
    "valid_time",
    "valid_hash",
    "valid_generation",
    "valid_critical_set",
    "valid_migration_path",
    "render_exact_diff",
    "validate_plan",
)
METHOD_HASHES = {
    "valid_time": "0649338eede280cc56667fc9e7b6b93027b5fd68e8774c6934a3aae59ee00094",
    "valid_hash": "bdcc29820e5c66fd7c139c75386bb8c57a2cb85acd2861faada43c0e06c94387",
    "valid_generation": "13243fd42c4503deccf713d63d5f5449f6c14a62aac90d48966e380db1ecc6d2",
    "valid_critical_set": "b0c33fd1b286d5e4b520cd2880c600b06516da24a0c4ee287a32a1af2d88920a",
    "valid_migration_path": "34d95ed0962f0d13e160dd52d1e9043fa09faf19586295c49b0e9bb3f6e4a895",
    "render_exact_diff": "a3593e7286af69aba3f82a540187517b6655465a3f425559dc154478d403c37f",
    "validate_plan": "ff7f474fdaaa85ae65c21ace54fb851018caf8cfb18aee82dd022a60f6d3ef6f",
}
SIGNATURES = {
    "valid_time": "(value: 'Any') -> 'bool'",
    "valid_hash": "(value: 'Any', *, nullable: 'bool' = False) -> 'bool'",
    "valid_generation": "(value: 'Any') -> 'bool'",
    "valid_critical_set": "(value: 'Any') -> 'bool'",
    "valid_migration_path": "(value: 'Any') -> 'bool'",
    "render_exact_diff": "(changes: 'list[dict[str, Any]]') -> 'str'",
    "validate_plan": "(self, plan: 'Any', plan_id: 'str') -> 'list[str]'",
}
REASON_SEQUENCE = tuple(
    {
        "F": "CONTINUITY_PLAN_FIELDS_INVALID",
        "I": "CONTINUITY_PLAN_INVALID",
        "V": "CONTINUITY_PLAN_INVENTORY_INVALID",
        "C": "CONTINUITY_PLAN_CHANGES_INVALID",
        "M": "CONTINUITY_PLAN_METADATA_INVALID",
    }[code]
    for code in "FIVVCIMMMMMMIIVVVCCCMMMVCCM"
)


def method_nodes(source: str, class_name: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(source)
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name: node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name in METHODS
    }


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    topology = json.loads(
        (TOOLS_ROOT / "continuity_transactions/topology.json").read_text()
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    owner_path = "_tools/continuity_transactions/plan_validation.py"
    owner_entry = entries[owner_path]
    check(
        "topology-routes-plan-validation-and-self-dependencies",
        owner_path in entries[topology["public_facade"]]["depends_on"]
        and owner_entry["focused_shard"]
        == "_tools/continuity_transactions/test_plan_validation.py"
        and "self:binding-project_path-target_bytes-critical_set-catalog_source_paths"
        in owner_entry["depends_on"],
    )
    owner_source = (
        TOOLS_ROOT / "continuity_transactions/plan_validation.py"
    ).read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    check(
        "owner-imports-are-one-way",
        "agent_os_continuity_transactions" not in owner_source
        and ast.parse(owner_source).body[-1].bases == [],
    )
    owner_nodes = method_nodes(owner_source, "PlanValidationMixin")
    facade_nodes = method_nodes(facade_source, "ContinuityTransactionService")
    check(
        "seven-method-family-has-one-source-owner",
        tuple(owner_nodes) == METHODS and facade_nodes == {},
    )
    service = facade.ContinuityTransactionService
    mixin = owner.PlanValidationMixin
    check(
        "public-identities-and-mro-are-preserved",
        service.__mro__[0] is service
        and mixin in service.__mro__[1:]
        and service.__mro__[-1] is object
        and all(getattr(service, name) is getattr(mixin, name) for name in METHODS),
    )
    check(
        "signatures-and-static-descriptors-are-preserved",
        all(
            str(inspect.signature(getattr(mixin, name))) == SIGNATURES[name]
            for name in METHODS
        )
        and all(isinstance(mixin.__dict__[name], staticmethod) for name in METHODS[:-1])
        and not isinstance(mixin.__dict__["validate_plan"], staticmethod),
    )
    hashes = {
        name: hashlib.sha256(
            ast.dump(node, include_attributes=False).encode()
        ).hexdigest()
        for name, node in owner_nodes.items()
    }
    check("ordered-method-ast-is-preserved", hashes == METHOD_HASHES)
    validate_node = owner_nodes["validate_plan"]
    reasons = tuple(
        node.value.elts[0].value
        for node in ast.walk(validate_node)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.List)
        and len(node.value.elts) == 1
        and isinstance(node.value.elts[0], ast.Constant)
    )
    check("reason-code-precedence-is-preserved", reasons == REASON_SEQUENCE)
    calls = {
        node.func.attr
        for node in ast.walk(validate_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    }
    instance = service.__new__(service)
    instance.valid_hash = lambda value, **kwargs: value == "patched"
    check(
        "self-dispatch-and-instance-monkeypatch-remain-open",
        {
            "binding",
            "project_path",
            "target_bytes",
            "critical_set",
            "catalog_source_paths",
            "valid_time",
            "valid_hash",
            "valid_generation",
            "valid_critical_set",
            "valid_migration_path",
            "render_exact_diff",
        }
        <= calls
        and instance.valid_hash("patched")
        and not instance.valid_hash("other"),
    )
    empty_hash = canonical_hash({})
    path = [
        {"migration_id": "v0-v1", "provider": "builtin:v0-v1", "source_generation": 0,
         "target_generation": 1, "unknown_fields_sha256": empty_hash},
        {"migration_id": "v1-v2", "provider": "builtin:v1-v2", "source_generation": 1,
         "target_generation": 2, "unknown_fields_sha256": empty_hash},
    ]
    check(
        "migration-path-is-bounded-contiguous-and-provider-typed",
        mixin.valid_migration_path(path)
        and not mixin.valid_migration_path(list(reversed(path)))
        and not mixin.valid_migration_path([dict(path[0], provider="external:v0-v1")]),
    )
    with tempfile.TemporaryDirectory(prefix="aos15-p2a3a2a-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        service_instance = service(root)
        before = json.loads((root / facade.CATALOG_REL).read_text(encoding="utf-8"))
        before["schema_version"] = 1
        before.pop("migration_extensions", None)
        write_json(root / facade.CATALOG_REL, before)
        after = deepcopy(before)
        after["schema_version"] = 2
        after["migration_extensions"] = [
            {"source_generation": 1, "migration_id": "continuity-catalog-v1-to-v2",
             "unknown_fields_sha256": empty_hash, "fields": {}}
        ]
        evidence = [
            {"migration_id": "continuity-catalog-v1-to-v2",
             "provider": "builtin:continuity-catalog-v1-to-v2", "source_generation": 1,
             "target_generation": 2, "unknown_fields_sha256": empty_hash}
        ]
        planned = service_instance.create_plan(
            "migrate", {facade.CATALOG_REL: json_bytes(after)}, before_catalog=before,
            after_catalog=after, source_paths=service_instance.catalog_source_paths(after),
            metadata={"migration_path": evidence,
                      "migration_path_sha256": canonical_hash(evidence)},
        )["plan"]
        def seal(plan: dict[str, Any]) -> None:
            plan["plan_id"], plan["content_sha256"] = "", ""
            plan["plan_id"] = canonical_hash(
                {key: value for key, value in plan.items()
                 if key not in {"plan_id", "content_sha256"}}
            )[:24]
            plan["content_sha256"] = receipt_hash(plan)
        planned["metadata"]["unknown_fields_sha256"] = canonical_hash([empty_hash])
        seal(planned)
        valid = service_instance.validate_plan(planned, planned["plan_id"])
        tampered = deepcopy(planned)
        tampered["metadata"]["migration_path"][0]["migration_id"] = "tampered"
        tampered["metadata"]["migration_path_sha256"] = canonical_hash(
            tampered["metadata"]["migration_path"]
        )
        seal(tampered)
        check(
            "generation-two-plan-binds-path-order-hashes-and-target-extensions",
            valid == []
            and service_instance.validate_plan(tampered, tampered["plan_id"])
            == ["CONTINUITY_PLAN_METADATA_INVALID"],
        )
    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
