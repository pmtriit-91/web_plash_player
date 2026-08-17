#!/usr/bin/env python3
"""Eight focused RS4a checks for restore receipt-validation extraction."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import agent_os_continuity_portability_restore as facade_module
from agent_os_continuity_portability_restore import ContinuityRestoreMixin
from continuity_portability_restore import contracts
from continuity_portability_restore.receipt_validation import (
    RestoreReceiptValidationMixin,
)

BASELINE_METHOD_AST_SHA256 = (
    "f42c99d4d71839080443aec61dbb0540eacbaef1a665316c33ad8495a63d9004"
)


def method_node(source: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "validate_restore_receipt"
    )


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    module = "_tools/continuity_portability_restore/receipt_validation.py"
    shard = "_tools/continuity_portability_restore/test_receipt_validation.py"
    topology_path = TOOLS_ROOT / "continuity_portability_restore/topology.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    expected_dependencies = {
        "_tools/agent_os_context_memory.py",
        "_tools/agent_os_continuity_portability_export.py",
        "_tools/agent_os_continuity_portability_foundation.py",
        "_tools/agent_os_continuity_transactions.py",
        "_tools/agent_os_paths.py",
        "_tools/continuity_portability_restore/contracts.py",
        "_tools/continuity_portability_restore/backup_validation.py",
    }
    check(
        "topology-routes-receipt-validation-and-focused-shard",
        module in entries[topology["public_facade"]]["depends_on"]
        and entries[module]["focused_shard"] == shard
        and set(entries[module]["depends_on"]) == expected_dependencies,
    )
    source_path = TOOLS_ROOT / "continuity_portability_restore/receipt_validation.py"
    source = source_path.read_text(encoding="utf-8")
    facade_path = TOOLS_ROOT / "agent_os_continuity_portability_restore.py"
    facade_source = facade_path.read_text(encoding="utf-8")
    check(
        "receipt-validation-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in source
        and "from agent_os_continuity_portability_restore" not in source,
    )
    check(
        "public-method-identity-mro-and-reexports-are-preserved",
        ContinuityRestoreMixin.validate_restore_receipt
        is RestoreReceiptValidationMixin.validate_restore_receipt
        and RestoreReceiptValidationMixin in ContinuityRestoreMixin.__mro__
        and facade_module.RESTORE_RECEIPT_FIELDS is contracts.RESTORE_RECEIPT_FIELDS
        and facade_module.RESTORE_RECEIPT_ID is contracts.RESTORE_RECEIPT_ID
        and facade_module.RESTORE_TARGET_FIELDS is contracts.RESTORE_TARGET_FIELDS,
    )
    method = method_node(source)
    method_hash = hashlib.sha256(
        ast.dump(method, include_attributes=False).encode()
    ).hexdigest()
    check(
        "method-ast-matches-pre-extraction-baseline",
        method_hash == BASELINE_METHOD_AST_SHA256,
    )
    reasons = [
        node.value.elts[0].value
        for node in ast.walk(method)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.List)
        and len(node.value.elts) == 1
        and isinstance(node.value.elts[0], ast.Constant)
    ]
    check(
        "reason-code-contract-remains-exact",
        Counter(reasons)
        == Counter(
            {
                "PORTABILITY_RESTORE_RECEIPT_INVALID": 10,
                "PORTABILITY_RESTORE_RECEIPT_PROVENANCE_UNVERIFIABLE": 1,
                "PORTABILITY_RESTORE_RECEIPT_TARGET_PATH_COLLISION": 1,
                "PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE": 6,
            }
        ),
    )
    method_source = ast.unparse(method)
    check(
        "provenance-path-byte-order-and-backup-guards-remain-present",
        all(
            token in method_source
            for token in (
                "validate_git_contract_provenance",
                "_has_portable_path_collision",
                "max_file_bytes",
                "max_total_bytes",
                "target_execution_order",
                "validate_restore_backup_index",
                "sha256_bytes",
            )
        ),
    )

    class PolicyProbe(ContinuityRestoreMixin):
        def policy(self) -> tuple[None, list[str]]:
            return None, ["POLICY_UNAVAILABLE"]

    check(
        "policy-failure-remains-first-and-fail-closed",
        PolicyProbe().validate_restore_receipt({}) == ["POLICY_UNAVAILABLE"],
    )
    shard_source = Path(__file__).read_text(encoding="utf-8")
    check(
        "module-shard-facade-and-topology-ratchets-hold",
        len(source.splitlines()) <= 275
        and len(shard_source.splitlines()) <= 190
        and len(facade_source.splitlines()) <= 450
        and len(topology_path.read_text().splitlines()) <= 112,
    )
    failed = [item for item in cases if not item["passed"]]
    payload = {"ok": not failed, "passed": 8 - len(failed), "total": 8, "cases": cases}
    print(json.dumps(payload, indent=2))
    raise SystemExit(2 if failed else 0)


if __name__ == "__main__":
    main()
