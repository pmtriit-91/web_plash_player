#!/usr/bin/env python3
"""Ten focused checks for continuity receipt validation extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_continuity_transactions")
owner = importlib.import_module("continuity_transactions.receipt_validation")
METHODS = ("validate_backup_index", "validate_transaction_receipt")
METHOD_HASHES = {
    "validate_backup_index": "2579043c877c5b8efffa11e5597120b639372e563e70c66b597764f7bb26da05",
    "validate_transaction_receipt": "3dba92e540fe829d4cea5c746b66b36c0987a7984801363fb78b460176c27f45",
}
SIGNATURES = {
    "validate_backup_index": "(self, index: 'Any', backup_id: 'str') -> 'list[str]'",
    "validate_transaction_receipt": "(self, receipt: 'Any', transaction_id: 'str') -> 'list[str]'",
}


# fmt: off
def method_nodes(source: str, class_name: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(source)
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name in METHODS}

def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    topology = json.loads((TOOLS_ROOT / "continuity_transactions/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    owner_path = "_tools/continuity_transactions/receipt_validation.py"
    owner_entry = entries[owner_path]
    required_dependencies = {
        "_tools/continuity_transactions/contracts.py",
        "_tools/agent_os_context_memory.py",
        "self:contract_hashes-binding-valid_time-valid_hash-path-backup_index-valid_generation-valid_critical_set-valid_migration_path",
    }
    check("topology-routes-receipt-validation-and-self-dependencies",
          owner_path in entries[topology["public_facade"]]["depends_on"]
          and owner_entry["focused_shard"] == "_tools/continuity_transactions/test_receipt_validation.py"
          and required_dependencies <= set(owner_entry["depends_on"]))
    owner_source = (TOOLS_ROOT / "continuity_transactions/receipt_validation.py").read_text()
    facade_source = (TOOLS_ROOT / "agent_os_continuity_transactions.py").read_text()
    owner_nodes = method_nodes(owner_source, "ReceiptValidationMixin")
    check("two-method-family-has-one-one-way-source-owner",
          "agent_os_continuity_transactions" not in owner_source
          and tuple(owner_nodes) == METHODS
          and method_nodes(facade_source, "ContinuityTransactionService") == {})
    service_class, mixin = facade.ContinuityTransactionService, owner.ReceiptValidationMixin
    check("public-identities-and-required-mro-are-preserved",
          service_class.__mro__[0] is service_class and mixin in service_class.__mro__[1:]
          and all(getattr(service_class, name) is getattr(mixin, name) for name in METHODS))
    check("signatures-and-instance-descriptors-are-preserved",
          all(str(inspect.signature(getattr(mixin, name))) == SIGNATURES[name]
              and not isinstance(mixin.__dict__[name], staticmethod) for name in METHODS))
    hashes = {name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
              for name, node in owner_nodes.items()}
    reasons = {
        name: tuple(item.value.elts[0].value for item in ast.walk(node)
                    if isinstance(item, ast.Return) and isinstance(item.value, ast.List)
                    and len(item.value.elts) == 1 and isinstance(item.value.elts[0], ast.Constant))
        for name, node in owner_nodes.items()
    }
    check("method-ast-and-reason-precedence-are-preserved",
          hashes == METHOD_HASHES
          and reasons[METHODS[0]] == ("CONTINUITY_BACKUP_INDEX_INVALID",) * 8
          and reasons[METHODS[1]] == ("CONTINUITY_TRANSACTION_RECEIPT_INVALID",) * 9)
    calls = {
        item.func.attr for node in owner_nodes.values() for item in ast.walk(node)
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
        and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"
    }
    instance = service_class.__new__(service_class)
    instance.valid_hash = lambda value, **kwargs: value == "patched"
    check("self-dispatch-and-instance-monkeypatch-remain-open",
          {"contract_hashes", "binding", "path", "backup_index", "valid_hash",
           "valid_migration_path"} <= calls
          and instance.valid_hash("patched") and not instance.valid_hash("other"))

    digest, backup_id = "a" * 64, "continuity-backup-" + "1" * 24
    instance.contract_hashes = lambda: {"binding_sha256": digest}
    instance.binding = lambda: {"project_id": "universal-agent-os"}
    instance.valid_time = lambda value: True
    instance.valid_hash = lambda value, *, nullable=False: (
        nullable and value is None
    ) or (
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
    files = [
        {"path": facade.CATALOG_REL, "present": True, "sha256": digest, "bytes": 1,
         "storage_path": f"{facade.BACKUP_DIR_REL}/{backup_id}/catalog.bin"},
        {"path": facade.PROJECTION_REL, "present": False, "sha256": None, "bytes": 0, "storage_path": None},
    ]
    index = {field: None for field in facade.BACKUP_INDEX_FIELDS}
    index.update(schema_version=1, backup_id=backup_id, project_id="universal-agent-os",
                 operation="refresh", created_at="valid", git_head="b" * 40,
                 binding_sha256=digest, files=files, raw_conversation_stored=False)
    index["content_sha256"] = owner.receipt_hash(index)
    wrong_index, redirected = deepcopy(index), deepcopy(index)
    wrong_index["project_id"] = "wrong-project"
    wrong_index["content_sha256"] = owner.receipt_hash(wrong_index)
    redirected["files"][0]["storage_path"] = "project/context/active-tasks.json"
    redirected["content_sha256"] = owner.receipt_hash(redirected)
    check("backup-index-valid-and-rehashed-tampering-fails-closed",
          instance.validate_backup_index(index, backup_id) == []
          and instance.validate_backup_index(wrong_index, backup_id) == ["CONTINUITY_BACKUP_INDEX_INVALID"]
          and instance.validate_backup_index(redirected, backup_id) == ["CONTINUITY_BACKUP_INDEX_INVALID"])

    transaction_id = "continuity-tx-" + "2" * 24
    receipt = {field: None for field in facade.TRANSACTION_RECEIPT_FIELDS}
    receipt.update(schema_version=1, transaction_id=transaction_id, operation="refresh",
                   status="applied", project_id="universal-agent-os", base_commit="b" * 40,
                   applied_at="valid", source_generation=0, target_generation=1,
                   critical_set_before=[], critical_set_after=[], rollback_verified=True,
                   source_deleted=False, owner_confirmation_performed=False,
                   raw_conversation_stored=False, commit_created=False, push_performed=False,
                   backup={"backup_id": backup_id,
                           "index_path": f"{facade.BACKUP_DIR_REL}/{backup_id}/index.json",
                           "index_sha256": digest},
                   semantic_completeness={"topology_state": "complete",
                                          "authority_state": "available", "reason_codes": []})
    for field in ("binding_sha256", "adapter_fingerprint_sha256", "record_type_registry_sha256",
                  "recovery_profile_sha256", "migration_registry_sha256", "source_inventory_sha256"):
        receipt[field] = digest
    receipt["content_sha256"] = owner.receipt_hash(receipt)
    instance.valid_generation = lambda value: True
    instance.valid_critical_set = lambda value: True
    instance.path, instance.backup_index = lambda relative: Path(relative), lambda value: ({}, [])
    owner.read_bytes, owner.sha256_bytes = lambda path: b"index", lambda value: digest
    migration_required_receipt = deepcopy(receipt)
    migration_required_receipt["semantic_completeness"] = {
        "topology_state": "migration-required",
        "authority_state": "unavailable",
        "reason_codes": ["CONTINUITY_MIGRATION_REQUIRED"],
    }
    migration_required_receipt["content_sha256"] = owner.receipt_hash(migration_required_receipt)
    extra_receipt, wrong_receipt = deepcopy(receipt), deepcopy(receipt)
    extra_receipt["unexpected_authority"] = "fail-closed"
    extra_receipt["content_sha256"] = owner.receipt_hash(extra_receipt)
    wrong_receipt["project_id"] = "wrong-project"
    wrong_receipt["content_sha256"] = owner.receipt_hash(wrong_receipt)
    check("receipt-valid-and-rehashed-tampering-fails-closed",
          instance.validate_transaction_receipt(receipt, transaction_id) == []
          and instance.validate_transaction_receipt(migration_required_receipt, transaction_id) == []
          and instance.validate_transaction_receipt(extra_receipt, transaction_id)
          == ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
          and instance.validate_transaction_receipt(wrong_receipt, transaction_id)
          == ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"])
    legacy_migration, missing_ordered_evidence = deepcopy(receipt), deepcopy(receipt)
    legacy_migration.update(operation="migrate", source_generation=0, target_generation=1)
    legacy_migration["content_sha256"] = owner.receipt_hash(legacy_migration)
    missing_ordered_evidence.update(operation="migrate", source_generation=0, target_generation=2)
    missing_ordered_evidence["content_sha256"] = owner.receipt_hash(missing_ordered_evidence)
    check("legacy-receipt-remains-valid-and-generation-two-requires-ordered-evidence",
          instance.validate_transaction_receipt(legacy_migration, transaction_id) == []
          and instance.validate_transaction_receipt(missing_ordered_evidence, transaction_id)
          == ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"])

    second_digest = "c" * 64
    migration_path = [
        {"migration_id": "generation-zero-to-one", "provider": "builtin:zero-to-one",
         "source_generation": 0, "target_generation": 1,
         "unknown_fields_sha256": digest},
        {"migration_id": "generation-one-to-two", "provider": "builtin:one-to-two",
         "source_generation": 1, "target_generation": 2,
         "unknown_fields_sha256": second_digest},
    ]
    ordered_receipt = deepcopy(missing_ordered_evidence)
    ordered_receipt.update(
        migration_path=migration_path,
        migration_path_sha256=owner.canonical_hash(migration_path),
        unknown_fields_sha256=owner.canonical_hash([digest, second_digest]),
    )
    ordered_receipt["content_sha256"] = owner.receipt_hash(ordered_receipt)
    reversed_path = deepcopy(ordered_receipt)
    reversed_path["migration_path"] = list(reversed(reversed_path["migration_path"]))
    reversed_path["migration_path_sha256"] = owner.canonical_hash(reversed_path["migration_path"])
    reversed_path["content_sha256"] = owner.receipt_hash(reversed_path)
    wrong_endpoint = deepcopy(ordered_receipt)
    wrong_endpoint["source_generation"] = 1
    wrong_endpoint["content_sha256"] = owner.receipt_hash(wrong_endpoint)
    wrong_path_hash = deepcopy(ordered_receipt)
    wrong_path_hash["migration_path_sha256"] = digest
    wrong_path_hash["content_sha256"] = owner.receipt_hash(wrong_path_hash)
    fields_on_refresh = deepcopy(ordered_receipt)
    fields_on_refresh["operation"] = "refresh"
    fields_on_refresh["content_sha256"] = owner.receipt_hash(fields_on_refresh)
    check("ordered-generation-two-receipt-valid-and-tampering-fails-closed",
          instance.validate_transaction_receipt(ordered_receipt, transaction_id) == []
          and all(instance.validate_transaction_receipt(candidate, transaction_id)
                  == ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
                  for candidate in (reversed_path, wrong_endpoint, wrong_path_hash,
                                    fields_on_refresh)))
    result = {"ok": all(item["passed"] for item in cases),
              "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
