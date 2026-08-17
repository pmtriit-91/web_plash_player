#!/usr/bin/env python3
"""Eight bounded RS5a contracts for restore apply orchestration extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_continuity_portability_restore import ContinuityRestoreMixin

BASELINE_METHOD_AST_SHA256 = (
    "637093cff24e3b1a4cc6dded2d1a8ba88a5274a4f4a394c2be9ed47e38236ac4"
)
EXPECTED_SIGNATURE = (
    "(self, plan_id: 'str', confirm: 'bool', *, test_fail_after: 'int' = 0, "
    "test_fail_stage: 'str | None' = None, test_fail_receipt_cleanup: 'bool' = "
    "False) -> 'dict[str, Any]'"
)
FACADE = TOOLS_ROOT / "agent_os_continuity_portability_restore.py"
NESTED = TOOLS_ROOT / "continuity_portability_restore/apply_orchestration.py"
TOPOLOGY = TOOLS_ROOT / "continuity_portability_restore/topology.json"


def method_node() -> ast.FunctionDef:
    source = textwrap.dedent(inspect.getsource(ContinuityRestoreMixin.apply_restore))
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "apply_restore"
    )


def ordered(source: str, tokens: list[str]) -> bool:
    positions = [source.find(token) for token in tokens]
    return all(position >= 0 for position in positions) and positions == sorted(
        positions
    )


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": bool(passed), **details})

    method = ContinuityRestoreMixin.apply_restore
    method_source = textwrap.dedent(inspect.getsource(method))
    method_hash = hashlib.sha256(
        ast.dump(method_node(), include_attributes=False).encode()
    ).hexdigest()
    check(
        "signature-and-method-ast-match-pre-extraction-baseline",
        str(inspect.signature(method)) == EXPECTED_SIGNATURE
        and method_hash == BASELINE_METHOD_AST_SHA256,
        method_ast_sha256=method_hash,
    )

    owner = Path(inspect.getsourcefile(method) or "").resolve()
    topology = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    nested_key = "_tools/continuity_portability_restore/apply_orchestration.py"
    if NESTED.exists():
        module = importlib.import_module(
            "continuity_portability_restore.apply_orchestration"
        )
        mixin = module.RestoreApplyOrchestrationMixin
        nested_entry = entries.get(nested_key, {})
        required_dependencies = {
            "_tools/agent_os_context_memory.py",
            "_tools/agent_os_continuity.py",
            "_tools/agent_os_continuity_portability.py",
            "_tools/agent_os_continuity_portability_export.py",
            "_tools/agent_os_continuity_portability_foundation.py",
            "_tools/agent_os_continuity_transactions.py",
            "_tools/agent_os_paths.py",
            "_tools/continuity_portability_restore/contracts.py",
            "_tools/continuity_portability_restore/backup_lifecycle.py",
            "_tools/continuity_portability_restore/receipt_builder.py",
            "_tools/continuity_portability_restore/plan_validation.py",
            "_tools/continuity_portability_restore/target_analysis.py",
        }
        owner_ok = (
            method is mixin.apply_restore
            and mixin in ContinuityRestoreMixin.__mro__
            and owner == NESTED.resolve()
            and nested_key in entries[topology["public_facade"]]["depends_on"]
            and nested_entry.get("focused_shard")
            == "_tools/continuity_portability_restore/test_apply_orchestration.py"
            and required_dependencies <= set(nested_entry.get("depends_on", []))
            and "agent_os_continuity_portability_restore" not in NESTED.read_text()
        )
    else:
        owner_ok = owner == FACADE.resolve() and nested_key not in entries
    check("current-or-exact-future-owner-topology-contract", owner_ok, owner=str(owner))

    service = ContinuityRestoreMixin()
    with patch.object(service, "apply_restore", return_value={"patched": True}):
        patched = service.apply_restore("1" * 24, True)
    check(
        "instance-monkeypatch-contract-remains-compatible", patched == {"patched": True}
    )

    with patch.object(service, "acquire_domain_locks", create=True) as acquire:
        confirmation = service.apply_restore("1" * 24, False)
        invalid = service.apply_restore("not-a-plan", True)
    check(
        "confirmation-and-plan-id-fail-before-lock",
        confirmation.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"]
        and invalid.get("reason_codes") == ["PORTABILITY__PLAN_ID_INVALID"]
        and acquire.call_count == 0,
    )

    with (
        patch.object(
            service,
            "acquire_domain_locks",
            return_value=(None, "PORTABILITY_TRANSACTION_BUSY"),
            create=True,
        ),
        patch.object(service, "release_domain_locks", create=True) as release,
    ):
        busy = service.apply_restore("1" * 24, True)
    check(
        "busy-lock-fails-closed-without-release",
        busy.get("reason_codes") == ["PORTABILITY_TRANSACTION_BUSY"]
        and release.call_count == 0,
    )

    check(
        "admission-precedes-backup-and-writes",
        ordered(
            method_source,
            [
                "self.validate_restore_plan(",
                "self.restore_compatibility(",
                "self.create_restore_backup(",
                "self._atomic_scoped_bytes(\n                self.project_root",
            ],
        ),
    )
    check(
        "ordered-success-prepares-plan-and-finalizes-receipt",
        ordered(
            method_source,
            [
                'prepared_receipt["status"] = "prepared"',
                'plan["status"] = "applied"',
                "self._commit_scoped_bytes(",
                '"ok": True',
            ],
        ),
    )
    check(
        "rollback-complete-incomplete-and-final-lock-contract",
        all(
            token in method_source
            for token in (
                "self.restore_backup(plan, backup_index)",
                'plan["status"] = "failed"',
                "receipt_removed and bytes_restored and plan_failed_recorded",
                '"PORTABILITY_RESTORE_FAILED_ROLLED_BACK"',
                '"PORTABILITY_RESTORE_ROLLBACK_INCOMPLETE"',
                "finally:\n        self.release_domain_locks(acquired)",
            )
        ),
    )

    failed = [item for item in cases if not item["passed"]]
    payload = {"ok": not failed, "passed": 8 - len(failed), "total": 8, "cases": cases}
    print(json.dumps(payload, indent=2))
    raise SystemExit(2 if failed else 0)


if __name__ == "__main__":
    main()
