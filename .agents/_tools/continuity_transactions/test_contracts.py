#!/usr/bin/env python3
"""Eight focused checks for continuity transaction contract extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_continuity_transactions")
contracts = importlib.import_module("continuity_transactions.contracts")
STRICT_DOCUMENT_AST_SHA256 = (
    "d4323d74b54285d2c316743a5bc37467800bea5329c6218cce0ed807130c0c9e"
)
PUBLIC_SYMBOLS = {
    "BACKUP_DIR_REL",
    "BACKUP_FILE_FIELDS",
    "BACKUP_ID",
    "BACKUP_INDEX_FIELDS",
    "BACKUP_REFERENCE_FIELDS",
    "BINDING_REL",
    "CATALOG_REL",
    "CHANGE_FIELDS",
    "CORE_MANIFEST_REL",
    "DEFAULT_ROOT",
    "DEFAULT_SOURCE_PATHS",
    "FINGERPRINT_REL",
    "FULL_COMMIT",
    "INVENTORY_FIELDS",
    "MAX_PLAN_SECONDS",
    "MIGRATION_FIELDS",
    "MIGRATION_REGISTRY_FIELDS",
    "MIGRATION_REGISTRY_REL",
    "OPERATIONS",
    "PLAN_FIELDS",
    "PLAN_ID",
    "PLAN_METADATA_OPTIONAL",
    "PLAN_METADATA_REQUIRED",
    "PROFILE_REL",
    "PROJECTION_REL",
    "REGISTRY_REL",
    "SEMANTIC_FIELDS",
    "SHA256",
    "TARGETS",
    "TRANSACTION_DIR_REL",
    "TRANSACTION_ID",
    "TRANSACTION_RECEIPT_FIELDS",
    "strict_document",
}


def rejects(payload: bytes) -> bool:
    try:
        contracts.strict_document(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return True
    return False


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    index = json.loads((TOOLS_ROOT / "module-topology-index.json").read_text())
    domains = {item["domain"]: item for item in index["domains"]}
    check(
        "root-index-routes-transaction-domain",
        domains["continuity-transactions"]["topology"]
        == "_tools/continuity_transactions/topology.json",
    )
    topology = json.loads(
        (TOOLS_ROOT / "continuity_transactions/topology.json").read_text()
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    contract_path = "_tools/continuity_transactions/contracts.py"
    check(
        "domain-topology-routes-contract-and-shard",
        contract_path in entries[topology["public_facade"]]["depends_on"]
        and entries[contract_path]["focused_shard"]
        == "_tools/continuity_transactions/test_contracts.py",
    )
    source = (TOOLS_ROOT / "continuity_transactions/contracts.py").read_text()
    check(
        "contract-owner-is-one-way-and-root-is-stable",
        "import agent_os_continuity_transactions" not in source
        and "from agent_os_continuity_transactions" not in source
        and contracts.DEFAULT_ROOT == TOOLS_ROOT.parent,
    )
    check(
        "facade-reexports-public-symbol-identities",
        all(
            getattr(facade, name) is getattr(contracts, name) for name in PUBLIC_SYMBOLS
        ),
    )
    strict_node = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "strict_document"
    )
    strict_hash = hashlib.sha256(
        ast.dump(strict_node, include_attributes=False).encode()
    ).hexdigest()
    check("strict-document-ast-is-preserved", strict_hash == STRICT_DOCUMENT_AST_SHA256)
    check("duplicate-json-key-is-rejected", rejects(b'{"x":1,"x":2}'))
    check("non-finite-json-number-is-rejected", rejects(b'{"x":NaN}'))
    oversized = b" " * (contracts.MAX_JSON_BYTES + 1)
    check(
        "valid-json-parity-and-read-boundary",
        contracts.strict_document(b'{"x":1}') == {"x": 1} and rejects(oversized),
    )
    check(
        "receipt-migration-path-fields-are-additive",
        contracts.TRANSACTION_RECEIPT_MIGRATION_FIELDS
        == {"migration_path", "migration_path_sha256"}
        and contracts.TRANSACTION_RECEIPT_MIGRATION_FIELDS
        <= contracts.PLAN_METADATA_OPTIONAL
        and contracts.TRANSACTION_RECEIPT_MIGRATION_FIELDS.isdisjoint(
            contracts.TRANSACTION_RECEIPT_FIELDS
        ),
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
