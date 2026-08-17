#!/usr/bin/env python3
"""Eight focused RS2b1 checks for restore-plan validation extraction."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_continuity_portability_restore import ContinuityRestoreMixin
from continuity_portability_restore.plan_validation import RestorePlanValidationMixin

BASELINE_METHOD_AST_SHA256 = (
    "34e9dd6acf211739773e0134fd2d02c1fc69827803f84c243a33a5e74151bfaa"
)


def method_node(source: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "validate_restore_plan"
    )


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    topology = json.loads(
        (TOOLS_ROOT / "continuity_portability_restore/topology.json").read_text()
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    module = "_tools/continuity_portability_restore/plan_validation.py"
    check(
        "topology-routes-plan-validation-and-nested-shard",
        module in entries[topology["public_facade"]]["depends_on"]
        and entries[module]["focused_shard"]
        == "_tools/continuity_portability_restore/test_plan_validation.py",
    )
    source = (
        TOOLS_ROOT / "continuity_portability_restore/plan_validation.py"
    ).read_text()
    check(
        "plan-validation-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in source,
    )
    check(
        "public-method-identity-and-mro-are-preserved",
        ContinuityRestoreMixin.validate_restore_plan
        is RestorePlanValidationMixin.validate_restore_plan
        and RestorePlanValidationMixin in ContinuityRestoreMixin.__mro__,
    )
    service = ContinuityRestoreMixin()
    with patch.object(service, "validate_restore_plan", return_value=["PATCHED"]):
        patched = service.validate_restore_plan({}, "unused")
    facade = (TOOLS_ROOT / "agent_os_continuity_portability_restore.py").read_text()
    apply_source = (
        TOOLS_ROOT / "continuity_portability_restore/apply_orchestration.py"
    ).read_text()
    check(
        "instance-monkeypatch-and-apply-caller-remain-compatible",
        patched == ["PATCHED"]
        and "errors = self.validate_restore_plan(plan, plan_id)" in apply_source,
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
        and isinstance(node.value.elts[0].value, str)
    ]
    check(
        "reason-code-set-remains-exact",
        set(reasons)
        == {
            "PORTABILITY_RESTORE_PLAN_FIELDS_INVALID",
            "PORTABILITY_RESTORE_PLAN_INVALID",
            "PORTABILITY_RESTORE_PLAN_BUNDLE_INVALID",
            "PORTABILITY_RESTORE_TARGETS_INVALID",
            "PORTABILITY_RESTORE_TARGET_PATH_COLLISION",
            "PORTABILITY_RESTORE_DEPENDENCY_ORDER_INVALID",
        },
    )
    call_lines = {
        node.func.attr: node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    check(
        "diff-and-order-calls-retain-sequence",
        call_lines["render_restore_diff"]
        < call_lines["restore_target_execution_order"],
    )
    check(
        "module-and-facade-line-ratchets-hold",
        len(source.splitlines()) <= 190 and len(facade.splitlines()) < 1162,
    )
    failed = [item for item in cases if not item["passed"]]
    print(
        json.dumps(
            {"ok": not failed, "passed": 8 - len(failed), "total": 8, "cases": cases},
            indent=2,
        )
    )
    raise SystemExit(2 if failed else 0)


if __name__ == "__main__":
    main()
