#!/usr/bin/env python3
"""Focused acceptance for the governed-reasoning MCP adapter."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import agent_os_mcp_server as mcp  # noqa: E402


class StubService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self.roots: list[Path] = []

    def bind(self, root: Path) -> StubService:
        self.roots.append(root)
        return self

    def record(self, name: str, *values: Any) -> dict[str, Any]:
        self.calls.append([name, *values])
        return {"ok": True, "method": name, "arguments": list(values)}

    def validate_artifact(self, kind: str, artifact: Any) -> dict[str, Any]:
        return self.record("validate_artifact", kind, artifact)

    def normalize_plan(self, *values: Any, **authority: Any) -> dict[str, Any]:
        return self.record("normalize_plan", *values, authority)

    def normalize_challenge(self, *values: Any, **authority: Any) -> dict[str, Any]:
        return self.record("normalize_challenge", *values, authority)

    def normalize_decision(self, *values: Any, **authority: Any) -> dict[str, Any]:
        return self.record("normalize_decision", *values, authority)

    def plan_receipt(
        self,
        kind: str,
        receipt: Any,
        source_receipt_ids: list[str],
        *,
        expiry_seconds: int,
    ) -> dict[str, Any]:
        return self.record("plan_receipt", kind, receipt, source_receipt_ids, expiry_seconds)

    def apply_receipt(self, plan_id: str, *, confirm: bool = False) -> dict[str, Any]:
        self.calls.append(["apply_receipt", plan_id, confirm])
        return {"ok": True, "plan_id": plan_id, "confirmed": confirm}

    def recover_receipt(self, transaction_id: str, *, confirm: bool = False) -> dict[str, Any]:
        self.calls.append(["recover_receipt", transaction_id, confirm])
        if transaction_id == "terminal":
            return {"ok": False, "reason_codes": ["TRANSACTION_ALREADY_TERMINAL"]}
        return {"ok": True, "transaction_id": transaction_id, "confirmed": confirm}


def invoke(name: str, arguments: Any, service: StubService) -> dict[str, Any] | None:
    original = getattr(mcp, "GovernedReasoningService", None)
    setattr(mcp, "GovernedReasoningService", service.bind)
    try:
        handler = getattr(mcp, f"tool_reasoning_{name}", None)
        return handler(arguments) if callable(handler) else None
    finally:
        if original is None:
            delattr(mcp, "GovernedReasoningService")
        else:
            setattr(mcp, "GovernedReasoningService", original)


def main() -> None:
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )
    service = StubService()
    names = {
        "agent_os/reasoning_validate",
        "agent_os/reasoning_plan",
        "agent_os/reasoning_challenge",
        "agent_os/reasoning_decide",
        "agent_os/reasoning_persist",
        "agent_os/reasoning_apply",
        "agent_os/reasoning_recover",
    }
    declared = {
        item.get("name"): item
        for item in mcp.TOOLS
        if isinstance(item, dict) and item.get("name") in names
    }
    check(
        "seven-tools-have-handlers-and-closed-input-schemas",
        set(declared) == names
        and names <= set(mcp.HANDLERS)
        and all(item.get("inputSchema", {}).get("additionalProperties") is False for item in declared.values()),
    )

    artifact = {"artifact": "value"}
    result = invoke("validate", {"kind": "request", "artifact": artifact}, service)
    check(
        "validate-preserves-service-result",
        result == {
            "ok": True,
            "method": "validate_artifact",
            "arguments": ["request", artifact],
        },
    )
    check(
        "mcp-root-is-release-bound-not-cwd-derived",
        service.roots[-1:] == [mcp.ROOT],
    )

    authority = {"current_intent_sha256": "0" * 64}
    plan = {
        "request": {"request": 1},
        "policy": {"policy": 1},
        "snapshot": {"snapshot": 1},
        "draft": {"draft": 1},
        "authority": authority,
    }
    result = invoke("plan", plan, service)
    check(
        "plan-preserves-service-semantics",
        result is not None
        and result.get("method") == "normalize_plan"
        and service.calls[-1]
        == ["normalize_plan", plan["request"], plan["policy"], plan["snapshot"], plan["draft"], authority],
    )

    challenge = {
        "request": {"request": 1},
        "plan": {"plan": 1},
        "policy": {"policy": 1},
        "draft": {"draft": 1},
        "authority": {"expected_authority_sha256": "a" * 64},
    }
    result = invoke("challenge", challenge, service)
    check(
        "challenge-preserves-service-semantics",
        result is not None
        and result.get("method") == "normalize_challenge"
        and service.calls[-1][-1] == challenge["authority"],
    )

    decision = {
        "request": {"request": 1},
        "plan": {"plan": 1},
        "challenge": {"challenge": 1},
        "policy": {"policy": 1},
        "draft": {"draft": 1},
        "snapshot": {"snapshot": 1},
        "authority": authority,
    }
    result = invoke("decide", decision, service)
    check(
        "decision-preserves-service-semantics",
        result is not None
        and result.get("method") == "normalize_decision"
        and service.calls[-1][-1] == authority,
    )

    persist = {
        "kind": "plan",
        "receipt": artifact,
        "source_receipt_ids": ["source-a", "source-b"],
        "expiry_seconds": 60,
    }
    result = invoke("persist", persist, service)
    check(
        "persist-only-plans-bounded-receipt-write",
        result is not None
        and result.get("method") == "plan_receipt"
        and service.calls[-1] == ["plan_receipt", "plan", artifact, ["source-a", "source-b"], 60],
    )

    calls_before = len(service.calls)
    result = invoke("apply", {"plan": "plan-id", "confirm": False}, service)
    check(
        "apply-requires-literal-confirmation-before-service",
        result is not None
        and result.get("error", {}).get("code") == "WRITE_CONFIRMATION_REQUIRED"
        and len(service.calls) == calls_before,
    )
    result = invoke("apply", {"plan": "plan-id", "confirm": True}, service)
    check(
        "apply-forwards-explicit-confirmation",
        result == {"ok": True, "plan_id": "plan-id", "confirmed": True}
        and service.calls[-1] == ["apply_receipt", "plan-id", True],
    )

    calls_before = len(service.calls)
    result = invoke("recover", {"transaction": "interrupted"}, service)
    check(
        "recovery-requires-literal-confirmation-before-service",
        result is not None
        and result.get("error", {}).get("code") == "WRITE_CONFIRMATION_REQUIRED"
        and len(service.calls) == calls_before,
    )
    result = invoke("recover", {"transaction": "interrupted", "confirm": True}, service)
    check(
        "recovery-forwards-explicit-confirmation",
        result == {"ok": True, "transaction_id": "interrupted", "confirmed": True}
        and service.calls[-1] == ["recover_receipt", "interrupted", True],
    )
    result = invoke("recover", {"transaction": "terminal", "confirm": True}, service)
    check(
        "terminal-recovery-refusal-is-not-rewritten",
        result == {"ok": False, "reason_codes": ["TRANSACTION_ALREADY_TERMINAL"]},
    )

    calls_before = len(service.calls)
    invalid_normalizations = [
        {**plan, "authority": []},
        {**plan, "authority": {"unexpected": True}},
        {**plan, "unexpected": True},
    ]
    invalid_results = [invoke("plan", value, service) for value in invalid_normalizations]
    check(
        "invalid-normalization-envelopes-fail-before-service",
        all(item is not None and item.get("error", {}).get("code") == "INVALID_ARGUMENT" for item in invalid_results)
        and len(service.calls) == calls_before,
    )

    calls_before = len(service.calls)
    invalid_persist_results = [
        invoke("persist", {**persist, "source_receipt_ids": value}, service)
        for value in ("source-a", [f"plan-{index:024x}" for index in range(17)])
    ]
    check(
        "invalid-or-oversized-source-receipt-list-fails-before-service",
        all(result is not None and result.get("error", {}).get("code") == "INVALID_ARGUMENT" for result in invalid_persist_results)
        and len(service.calls) == calls_before,
    )

    original = getattr(mcp, "GovernedReasoningService", None)
    setattr(mcp, "GovernedReasoningService", service.bind)
    try:
        response = mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "agent_os/reasoning_recover",
                    "arguments": {"transaction": "terminal", "confirm": True},
                },
            }
        )
    finally:
        if original is None:
            delattr(mcp, "GovernedReasoningService")
        else:
            setattr(mcp, "GovernedReasoningService", original)
    payload = None
    try:
        payload = json.loads(response["result"]["content"][0]["text"]) if response else None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        pass
    check(
        "mcp-result-retains-reason-code-and-error-bit",
        response is not None
        and response.get("result", {}).get("isError") is True
        and payload == {"ok": False, "reason_codes": ["TRANSACTION_ALREADY_TERMINAL"]},
    )

    with tempfile.TemporaryDirectory(prefix="mcp-cwd-") as holder:
        previous = Path.cwd()
        try:
            os.chdir(holder)
            invoke("validate", {"kind": "policy", "artifact": artifact}, service)
        finally:
            os.chdir(previous)
    check("ambient-cwd-never-selects-authority-root", service.roots[-1:] == [mcp.ROOT])

    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
