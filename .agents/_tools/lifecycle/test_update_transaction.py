#!/usr/bin/env python3
"""Eight focused checks for lifecycle update-transaction extraction."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_lifecycle")
owner = importlib.import_module("lifecycle.update_transaction")
# fmt: off
NAMES = ("update_relative_path", "remove_update_path", "copy_update_path", "atomic_json", "backup_update_paths", "restore_update_backup", "current_entry_digest", "apply_update", "rollback_update")
ORDERED_AST_SHA256 = "22097a7bcf08f6644a97e2269a4599a99a7853e0a40ff0629ad3d277f5e918b3"


def main() -> None:
    cases: list[dict[str, object]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/update_transaction.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-update-transaction-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    check("facade-reexports-exact-identities", all(getattr(facade, name) is getattr(owner, name) for name in NAMES) and facade.UPDATE_RUNTIME_ROOT is owner.UPDATE_RUNTIME_ROOT)
    signatures = {name: inspect.signature(getattr(owner, name)) for name in NAMES}
    check("signatures-remain-stable", str(signatures["update_relative_path"]) == "(root: 'Path', relative: 'str') -> 'Path'" and str(signatures["backup_update_paths"]) == "(transaction_root: 'Path', paths: 'list[str]') -> 'list[dict[str, Any]]'" and str(signatures["apply_update"]) == "(args: 'argparse.Namespace') -> 'dict[str, Any]'" and str(signatures["rollback_update"]) == "(args: 'argparse.Namespace') -> 'dict[str, Any]'")
    check("owner-has-no-reverse-facade-import", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source)
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    entry = entries["_tools/lifecycle/update_transaction.py"]
    check("topology-routes-update-transaction-owner", entry["focused_shard"] == "_tools/lifecycle/test_update_transaction.py" and entry["depends_on"] == ["_tools/lifecycle/shared.py", "_tools/lifecycle/update_planning.py", "_tools/agent_os_paths.py"] and "_tools/lifecycle/update_transaction.py" in entries["_tools/agent_os_lifecycle.py"]["depends_on"])
    original_callback, original_facade_verify = owner._core_verifier, facade.verify_core
    owner._core_verifier = None
    try:
        owner.verify_core()
        fail_closed = False
    except RuntimeError:
        fail_closed = True
    owner._core_verifier = original_callback
    marker = {"ok": True, "source": "facade-binding"}
    facade.verify_core = lambda: marker
    live_binding = owner.verify_core()
    facade.verify_core = original_facade_verify
    check("core-verifier-binding-is-fail-closed-and-live", fail_closed and live_binding is marker)
    with tempfile.TemporaryDirectory(prefix="lifecycle-update-transaction-") as temporary:
        root = Path(temporary)
        current = root / "core/state.txt"
        current.parent.mkdir(parents=True)
        current.write_text("before", encoding="utf-8")
        transaction = root / "transactions/one"
        original_root = owner.ROOT
        owner.ROOT = root
        before = owner.current_entry_digest("core/state.txt")
        index = owner.backup_update_paths(transaction, ["core/state.txt", "core/missing.txt"])
        current.write_text("after", encoding="utf-8")
        owner.restore_update_backup(transaction, index)
        after = owner.current_entry_digest("core/state.txt")
        payload = json.loads((transaction / "backup-index.json").read_text())
        owner.ROOT = original_root
        check("backup-restore-digest-and-atomic-json-contracts-hold", current.read_text() == "before" and before == after and payload == {"entries": index} and index[1] == {"path": "core/missing.txt", "existed": False})
    apply_blocked = owner.apply_update(argparse.Namespace(confirm=False))
    rollback_blocked = owner.rollback_update(argparse.Namespace(confirm=False, transaction_id=None))
    invalid = owner.rollback_update(argparse.Namespace(confirm=True, transaction_id="bad"))
    check("confirmation-and-transaction-id-precedence-remain-stable", apply_blocked["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and rollback_blocked["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and invalid["reason_codes"] == ["TRANSACTION_ID_INVALID"] and not any(item["writes_performed"] for item in (apply_blocked, rollback_blocked, invalid)))
    result = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
