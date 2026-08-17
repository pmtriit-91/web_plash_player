#!/usr/bin/env python3
"""Eight focused checks for continuity recovery planning extraction."""

from __future__ import annotations

import ast
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
owner = importlib.import_module("continuity_transactions.recovery_planning")
memory = importlib.import_module("agent_os_context_memory")
METHODS = (
    "backup_index",
    "backup_contents",
    "plan_repair",
    "transaction_receipt",
    "plan_rollback",
    "create_backup",
)
METHOD_HASHES = {
    "backup_index": "331dec94e10605aee611ab74b225fc38d686580ac0f4ba2a867c83a05c99bcd7",
    "backup_contents": "9fdcc9eaff3d81f4ed21b2d3cbd1fcff94af238dbd64cfcad3aa9b810c52469f",
    "plan_repair": "dd24b22e0f4185c5adb1dcaf5fe678874980e95be48828e160e35bececd27653",
    "transaction_receipt": "5514640134c4e42a343309f2c64a9f73c9566fc8dd8e50f4b829b043f5d4504c",
    "plan_rollback": "17c524abf46c776a622c1a8a71bf32dc2e9e4d8e1dfcb71c8f4cb9064117d2e4",
    "create_backup": "d00e800b5ea23c83ead733794a3247b86bdeb0002295645d745da4fa9d8b142d",
}
SIGNATURES = {
    "backup_index": "(self, backup_id: 'str') -> 'tuple[dict[str, Any] | None, list[str]]'",
    "backup_contents": "(self, backup_id: 'str') -> 'tuple[dict[str, bytes | None] | None, list[str]]'",
    "plan_repair": "(self, backup_id: 'str | None' = None) -> 'dict[str, Any]'",
    "transaction_receipt": "(self, transaction_id: 'str') -> 'tuple[dict[str, Any] | None, list[str]]'",
    "plan_rollback": "(self, transaction_id: 'str') -> 'dict[str, Any]'",
    "create_backup": "(self, plan: 'dict[str, Any]') -> 'tuple[dict[str, Any] | None, list[str]]'",
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
    owner_path = "_tools/continuity_transactions/recovery_planning.py"
    required = {"_tools/continuity_transactions/contracts.py", "_tools/agent_os_continuity.py",
                "_tools/agent_os_context_memory.py", "self:receipt-validation-transition-planning-and-facade-paths"}
    check("topology-routes-recovery-planning-and-self-dependencies",
          owner_path in entries[topology["public_facade"]]["depends_on"]
          and entries[owner_path]["focused_shard"] == "_tools/continuity_transactions/test_recovery_planning.py"
          and required <= set(entries[owner_path]["depends_on"]))
    owner_source = (TOOLS_ROOT / "continuity_transactions/recovery_planning.py").read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    nodes = method_nodes(owner_source, "RecoveryPlanningMixin")
    check("six-method-family-has-one-one-way-source-owner",
          "agent_os_continuity_transactions" not in owner_source and tuple(nodes) == METHODS
          and method_nodes(facade_source, "ContinuityTransactionService") == {})
    service, mixin = facade.ContinuityTransactionService, owner.RecoveryPlanningMixin
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
    instance = service.__new__(service)
    instance.backup_index = lambda backup_id: ({"files": []}, [])
    check("self-dispatch-and-instance-monkeypatch-remain-open",
          {"backup_index", "backup_contents", "create_plan", "validate_backup_index",
           "validate_transaction_receipt"} <= calls and instance.backup_contents("patched") == ({}, []))
    check("invalid-backup-id-precedes-filesystem-read",
          mixin.backup_index(instance, "invalid") == (None, ["CONTINUITY_BACKUP_ID_INVALID"]))
    check("invalid-transaction-id-precedes-filesystem-read",
          instance.transaction_receipt("invalid") == (None, ["CONTINUITY_TRANSACTION_ID_INVALID"]))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / ".agents"
        root.mkdir()
        instance = service(root, now=lambda: datetime(2026, 1, 2, tzinfo=timezone.utc))
        instance.binding = lambda: {"project_id": "project-a"}
        instance.contract_hashes = lambda: {"binding_sha256": "a" * 64}
        desired = {facade.CATALOG_REL: b'{"schema_version":1}', facade.PROJECTION_REL: None}
        instance.target_bytes = lambda relative: desired[relative]
        backup_id = "continuity-backup-" + "b" * 24
        plan = {"metadata": {"backup_id": backup_id}, "project_id": "project-a", "operation": "repair",
                "git_head": "c" * 40, "binding_sha256": "a" * 64}
        reference, errors = instance.create_backup(plan)
        restored, restore_errors = instance.backup_contents(backup_id)
        index_path = root / str(reference["index_path"])
        index = json.loads(index_path.read_text())
        catalog_item = next(item for item in index["files"] if item["path"] == facade.CATALOG_REL)
        catalog_item["storage_path"] = "project/context/redirected.bin"
        index["content_sha256"] = memory.receipt_hash(index)
        index_path.write_bytes(memory.json_bytes(index))
        redirected = instance.backup_contents(backup_id)
        catalog_item["storage_path"] = f"project/context/continuity-backups/{backup_id}/catalog.bin"
        index["project_id"] = "project-b"
        index["content_sha256"] = memory.receipt_hash(index)
        index_path.write_bytes(memory.json_bytes(index))
        wrong_project = instance.backup_contents(backup_id)
    check("backup-roundtrip-rejects-rehashed-redirect-and-wrong-project",
          errors == [] and reference is not None and restored == desired and restore_errors == []
          and redirected == (None, ["CONTINUITY_BACKUP_INDEX_INVALID"])
          and wrong_project == (None, ["CONTINUITY_BACKUP_INDEX_INVALID"]))
    result = {"ok": all(item["passed"] for item in cases),
              "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
