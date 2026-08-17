#!/usr/bin/env python3
"""Ten focused checks for continuity apply-engine extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
from agent_os_context_memory import encoded, sha256_bytes
from continuity_transactions.test_support import make_fixture, write_json

facade = importlib.import_module("agent_os_continuity_transactions")
owner = importlib.import_module("continuity_transactions.apply_engine")
METHODS = (
    "acquire_lock",
    "release_lock",
    "verify_change_hashes",
    "restore_changes",
    "apply",
    "list_transactions",
)
METHOD_HASHES = {
    "acquire_lock": "63b954da762f53c7be089be9d89c60aff8a0e6d5932d24c2baa8c0b911485c71",
    "release_lock": "03fc17aa164b368df49eaa4f9e5c23dab81df04cfb8c8e872bfccc905a89f130",
    "verify_change_hashes": "d0f6372fbaded282e7a14bdfaeed84a34ab0d21ede4879e34bba4ff7937b6ab4",
    "restore_changes": "aa1210c71b87d8d388d248bda0af1db05db48202a2ffdf3f021bda72288babdd",
    "apply": "f45a3138ce329e6030485ecc6d004a06647e55cc24691344579d87a3e7d1f4bf",
    "list_transactions": "033daeef4395463bcb1934e5afddad10a33f940b42b4389c1f31108c6a6f244d",
}
SIGNATURES = {
    "acquire_lock": "(self) -> 'TransactionLockHandle'",
    "release_lock": "(self, handle: 'TransactionLockHandle') -> 'None'",
    "verify_change_hashes": "(self, changes: 'list[dict[str, Any]]', *, after: 'bool') -> 'bool'",
    "restore_changes": "(self, changes: 'list[dict[str, Any]]') -> 'bool'",
    "apply": "(self, plan_id: 'str', confirm: 'bool', *, test_fail_after: 'int' = 0) -> 'dict[str, Any]'",
    "list_transactions": "(self) -> 'dict[str, Any]'",
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
    owner_path = "_tools/continuity_transactions/apply_engine.py"
    required = {"_tools/continuity_transactions/contracts.py", "_tools/agent_os_continuity.py",
                "_tools/agent_os_context_memory.py", "_tools/agent_os_transaction_lock.py",
                "self:validation-inventory-recovery-receipt-and-facade-paths"}
    check("topology-routes-apply-engine-and-self-dependencies",
          owner_path in entries[topology["public_facade"]]["depends_on"]
          and entries[owner_path]["focused_shard"] == "_tools/continuity_transactions/test_apply_engine.py"
          and required <= set(entries[owner_path]["depends_on"]))

    owner_source = (TOOLS_ROOT / "continuity_transactions/apply_engine.py").read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    nodes = method_nodes(owner_source, "ApplyEngineMixin")
    check("six-method-family-has-one-one-way-source-owner",
          "agent_os_continuity_transactions" not in owner_source and tuple(nodes) == METHODS
          and method_nodes(facade_source, "ContinuityTransactionService") == {})

    service, mixin = facade.ContinuityTransactionService, owner.ApplyEngineMixin
    check("public-identities-and-mro-are-preserved",
          service.__mro__[0] is service and service.__mro__[1] is mixin and service.__mro__[-1] is object
          and all(getattr(service, name) is getattr(mixin, name) for name in METHODS))

    hashes = {name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
              for name, node in nodes.items()}
    check("method-ast-and-signatures-are-preserved", hashes == METHOD_HASHES
          and all(str(inspect.signature(getattr(mixin, name))) == SIGNATURES[name] for name in METHODS))

    calls = {item.func.attr for node in nodes.values() for item in ast.walk(node)
             if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
             and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"}
    instance = service.__new__(service)
    instance.verify_change_hashes = lambda changes, *, after: after is False
    check("self-dispatch-and-instance-monkeypatch-remain-open",
          {"acquire_lock", "release_lock", "validate_plan", "source_inventory", "create_backup",
           "backup_contents", "transaction_receipt", "restore_changes", "verify_change_hashes"} <= calls
          and mixin.restore_changes(instance, []))

    confirmation_precedence = (
        mixin.apply(instance, "invalid", False)
        == {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        and mixin.apply(instance, "invalid", True)
        == {"ok": False, "reason_codes": ["CONTINUITY_PLAN_ID_INVALID"]}
    )

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / ".agents"
        root.mkdir()
        instance = service(root)
        old, new, created = b"old-bytes", b"new-bytes", b"created-bytes"
        existing, added = root / "project/existing.bin", root / "project/added.bin"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(new)
        added.write_bytes(created)
        changes = [
            {"path": "project/existing.bin", "before_base64": encoded(old),
             "before_sha256": sha256_bytes(old), "after_sha256": sha256_bytes(new)},
            {"path": "project/added.bin", "before_base64": None,
             "before_sha256": None, "after_sha256": sha256_bytes(created)},
        ]
        after_ok = instance.verify_change_hashes(changes, after=True)
        restored = instance.restore_changes(changes)
        restore_ok = existing.read_bytes() == old and not added.exists()
    check("hash-verification-and-byte-exact-restore-remain-stable", after_ok and restored and restore_ok)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / ".agents"
        root.mkdir()
        instance = service(root)
        released: list[object] = []
        token = object()
        instance.acquire_lock = lambda: token
        instance.release_lock = lambda handle: released.append(handle)
        instance.validate_plan = lambda plan, plan_id: ["SENTINEL_INVALID_PLAN"]
        early = instance.apply("a" * 24, True)
        transaction_dir = root / facade.TRANSACTION_DIR_REL
        transaction_dir.mkdir(parents=True)
        good = "continuity-tx-" + "a" * 24
        bad = "continuity-tx-" + "b" * 24
        (transaction_dir / f"{good}.json").touch()
        (transaction_dir / f"{bad}.json").touch()
        instance.transaction_receipt = lambda tx: ({"transaction_id": tx}, []) if tx == good else (None, ["BROKEN"])
        listed = instance.list_transactions()
    check("apply-precedence-lock-release-and-receipt-listing-remain-stable",
          confirmation_precedence
          and early == {"ok": False, "reason_codes": ["SENTINEL_INVALID_PLAN"]} and released == [token]
          and listed["transactions"] == [{"transaction_id": good}]
          and listed["errors"] == [{"transaction_id": bad, "code": "BROKEN"}])

    def generation_two_plan(root: Path) -> tuple[Any, dict[str, Any], bytes]:
        source = json.loads((root / facade.CATALOG_REL).read_text(encoding="utf-8"))
        source["schema_version"] = 0
        source.pop("catalog_revision")
        source.pop("migration_extensions")
        write_json(root / facade.CATALOG_REL, source)
        source_bytes = (root / facade.CATALOG_REL).read_bytes()
        service_instance = service(root)
        planned = service_instance.plan_migrate()
        return service_instance, planned, source_bytes

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3c2-v1-rollback-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        catalog_path = root / facade.CATALOG_REL
        source = json.loads(catalog_path.read_text(encoding="utf-8"))
        source["schema_version"] = 1
        source.pop("migration_extensions", None)
        write_json(catalog_path, source)
        source_bytes = catalog_path.read_bytes()
        service_instance = service(root)
        migrated_plan = service_instance.plan_migrate()
        migrated = service_instance.apply(migrated_plan.get("plan", {}).get("plan_id", ""), True)
        migrated_receipt = migrated.get("receipt", {})
        rollback_plan = service_instance.plan_rollback(migrated_receipt.get("transaction_id", ""))
        rolled_back = service_instance.apply(rollback_plan.get("plan", {}).get("plan_id", ""), True)
        rollback_receipt = rolled_back.get("receipt", {})
        rollback_health = rolled_back.get("health", {})
        generation_one_restored_exactly = catalog_path.read_bytes() == source_bytes

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3c2-v0-rollback-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        service_instance, migrated_plan, _source_bytes = generation_two_plan(root)
        migrated = service_instance.apply(migrated_plan.get("plan", {}).get("plan_id", ""), True)
        generation_two_bytes = (root / facade.CATALOG_REL).read_bytes()
        rollback_plan = service_instance.plan_rollback(
            migrated.get("receipt", {}).get("transaction_id", "")
        )
        rejected = service_instance.apply(rollback_plan.get("plan", {}).get("plan_id", ""), True)
        generation_zero_recovered_to_two = (root / facade.CATALOG_REL).read_bytes() == generation_two_bytes
    check("rollback-admits-exact-v1-predecessor-and-still-rejects-v0",
          migrated_plan.get("ok") is True
          and rolled_back.get("ok") is True
          and generation_one_restored_exactly
          and rollback_health.get("state") == "MIGRATION_REQUIRED"
          and rollback_health.get("topology_state") == "migration-required"
          and rollback_health.get("reason_codes") == ["CONTINUITY_MIGRATION_REQUIRED"]
          and rollback_receipt.get("operation") == "rollback"
          and rollback_receipt.get("source_generation") == 2
          and rollback_receipt.get("target_generation") == 1
          and rollback_receipt.get("semantic_completeness", {}).get("topology_state") == "migration-required"
          and rejected.get("reason_codes") == ["CONTINUITY_APPLY_FAILED_ROLLED_BACK"]
          and rejected.get("rollback_verified") is True
          and generation_zero_recovered_to_two)

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3b2-receipt-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        service_instance, planned, _source_bytes = generation_two_plan(root)
        plan = planned.get("plan", {})
        metadata = plan.get("metadata", {})
        applied = service_instance.apply(plan.get("plan_id", ""), True)
        receipt = applied.get("receipt", {})
        durable_path = root / facade.TRANSACTION_DIR_REL / f"{receipt.get('transaction_id')}.json"
        durable = json.loads(durable_path.read_text(encoding="utf-8")) if durable_path.is_file() else {}
    check("generation-two-migration-emits-exact-reviewed-evidence",
          planned.get("ok") is True and applied.get("ok") is True
          and metadata.get("target_generation") == 2
          and len(metadata.get("migration_path", [])) == 2
          and receipt.get("migration_path") == metadata.get("migration_path")
          and receipt.get("migration_path_sha256") == metadata.get("migration_path_sha256")
          and receipt.get("unknown_fields_sha256") == metadata.get("unknown_fields_sha256")
          and durable == receipt)

    with tempfile.TemporaryDirectory(prefix="aos15-p2a3b2-failure-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        service_instance, planned, source_bytes = generation_two_plan(root)
        plan = planned.get("plan", {})
        transaction_id = plan.get("metadata", {}).get("transaction_id", "")
        with patch.dict("os.environ", {"AGENT_OS_TEST_MODE": "1"}, clear=False):
            failed = service_instance.apply(
                plan.get("plan_id", ""),
                True,
                test_fail_after=len(plan.get("changes", [])) + 1,
            )
        receipt_path = root / facade.TRANSACTION_DIR_REL / f"{transaction_id}.json"
        failure_contract = (
            planned.get("ok") is True
            and failed.get("reason_codes")
            == ["CONTINUITY_APPLY_FAILED_ROLLED_BACK"]
            and failed.get("rollback_verified") is True
            and failed.get("receipt_cleanup_verified") is True
            and (root / facade.CATALOG_REL).read_bytes() == source_bytes
            and not receipt_path.exists()
        )
    check("generation-two-receipt-failure-rolls-back-and-cleans-up",
          failure_contract)

    result = {"ok": all(item["passed"] for item in cases),
              "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
