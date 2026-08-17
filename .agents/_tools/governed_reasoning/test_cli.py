#!/usr/bin/env python3
"""Focused acceptance for the governed-reasoning CLI adapter."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import agent_os_cli as cli  # noqa: E402


class StubService:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self.roots: list[Path] = []

    def bind(self, root: Path) -> StubService:
        self.roots.append(root)
        return self

    def record(self, name: str, *values: Any) -> dict[str, Any]:
        call = [name, *values]
        self.calls.append(call)
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
        return self.record(
            "plan_receipt",
            kind,
            receipt,
            source_receipt_ids,
            expiry_seconds,
        )

    def apply_receipt(self, plan_id: str, *, confirm: bool = False) -> dict[str, Any]:
        self.calls.append(["apply_receipt", plan_id, confirm])
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        return {"ok": True, "plan_id": plan_id, "confirmed": True}

    def recover_receipt(
        self,
        transaction_id: str,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(["recover_receipt", transaction_id, confirm])
        if transaction_id == "terminal":
            return {"ok": False, "reason_codes": ["TRANSACTION_ALREADY_TERMINAL"]}
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        return {"ok": True, "transaction_id": transaction_id, "confirmed": True}


def write_json(directory: Path, name: str, value: Any) -> Path:
    path = directory / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def invoke(
    directory: Path,
    service: StubService,
    *arguments: str,
) -> tuple[int, dict[str, Any] | None]:
    previous_argv = sys.argv
    previous_cwd = Path.cwd()
    original = getattr(cli, "GovernedReasoningService", None)
    setattr(cli, "GovernedReasoningService", service.bind)
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        os.chdir(directory)
        sys.argv = ["agent-os", *arguments]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                cli.main()
            except SystemExit as error:
                code = int(error.code or 0)
            else:
                code = 0
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)
        if original is None:
            delattr(cli, "GovernedReasoningService")
        else:
            setattr(cli, "GovernedReasoningService", original)
    try:
        return code, json.loads(stdout.getvalue())
    except json.JSONDecodeError:
        return code, None


def main() -> None:
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )
    service = StubService()
    with tempfile.TemporaryDirectory(prefix="governed-cli-") as holder:
        root = Path(holder)
        agent = root / ".agents"
        agent.mkdir()
        artifact = {"artifact": "value"}
        artifact_path = write_json(root, "artifact.json", artifact)

        code, result = invoke(
            root,
            service,
            "reasoning",
            "validate",
            "request",
            str(artifact_path),
        )
        check(
            "validate-forwards-exact-artifact",
            code == 0
            and result == {
                "ok": True,
                "method": "validate_artifact",
                "arguments": ["request", artifact],
            },
        )
        check(
            "working-project-agent-root-is-selected",
            [path.resolve() for path in service.roots[-1:]] == [agent.resolve()],
        )

        authority = {"current_intent_sha256": "0" * 64}
        plan_document = {
            "request": {"request": 1},
            "policy": {"policy": 1},
            "snapshot": {"snapshot": 1},
            "draft": {"draft": 1},
            "authority": authority,
        }
        plan_path = write_json(root, "plan.json", plan_document)
        code, result = invoke(root, service, "reasoning", "plan", str(plan_path))
        check(
            "plan-forwards-one-bounded-envelope",
            code == 0
            and result is not None
            and result.get("method") == "normalize_plan"
            and service.calls[-1]
            == [
                "normalize_plan",
                plan_document["request"],
                plan_document["policy"],
                plan_document["snapshot"],
                plan_document["draft"],
                authority,
            ],
        )

        challenge_document = {
            "request": {"request": 1},
            "plan": {"plan": 1},
            "policy": {"policy": 1},
            "draft": {"draft": 1},
            "authority": {"expected_authority_sha256": "a" * 64},
        }
        challenge_path = write_json(root, "challenge.json", challenge_document)
        code, result = invoke(
            root,
            service,
            "reasoning",
            "challenge",
            str(challenge_path),
        )
        check(
            "challenge-preserves-service-semantics",
            code == 0
            and result is not None
            and result.get("method") == "normalize_challenge"
            and service.calls[-1][-1] == challenge_document["authority"],
        )

        decision_document = {
            "request": {"request": 1},
            "plan": {"plan": 1},
            "challenge": {"challenge": 1},
            "policy": {"policy": 1},
            "draft": {"draft": 1},
            "snapshot": {"snapshot": 1},
            "authority": authority,
        }
        decision_path = write_json(root, "decision.json", decision_document)
        code, result = invoke(
            root,
            service,
            "reasoning",
            "decide",
            str(decision_path),
        )
        check(
            "decision-preserves-service-semantics",
            code == 0
            and result is not None
            and result.get("method") == "normalize_decision"
            and service.calls[-1][-1] == authority,
        )

        code, result = invoke(
            root,
            service,
            "reasoning",
            "persist",
            "plan",
            str(artifact_path),
            "--source-receipt-id",
            "source-a",
            "--source-receipt-id",
            "source-b",
            "--expiry-seconds",
            "60",
        )
        check(
            "persist-only-plans-bounded-receipt-write",
            code == 0
            and result is not None
            and result.get("method") == "plan_receipt"
            and service.calls[-1]
            == ["plan_receipt", "plan", artifact, ["source-a", "source-b"], 60],
        )

        code, result = invoke(
            root,
            service,
            "reasoning",
            "apply",
            "--plan",
            "plan-id",
        )
        check(
            "apply-does-not-infer-confirmation",
            code == 2
            and result == {
                "ok": False,
                "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"],
            }
            and service.calls[-1] == ["apply_receipt", "plan-id", False],
        )
        code, result = invoke(
            root,
            service,
            "reasoning",
            "apply",
            "--plan",
            "plan-id",
            "--confirm",
        )
        check(
            "apply-forwards-explicit-confirmation",
            code == 0
            and result is not None
            and result.get("confirmed") is True
            and service.calls[-1] == ["apply_receipt", "plan-id", True],
        )

        code, result = invoke(
            root,
            service,
            "reasoning",
            "recover",
            "--transaction",
            "interrupted",
        )
        check(
            "recovery-does-not-infer-confirmation",
            code == 2
            and result is not None
            and result.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"]
            and service.calls[-1] == ["recover_receipt", "interrupted", False],
        )
        code, result = invoke(
            root,
            service,
            "reasoning",
            "recover",
            "--transaction",
            "interrupted",
            "--confirm",
        )
        check(
            "recovery-forwards-explicit-confirmation",
            code == 0
            and result is not None
            and result.get("confirmed") is True
            and service.calls[-1] == ["recover_receipt", "interrupted", True],
        )
        code, result = invoke(
            root,
            service,
            "reasoning",
            "recover",
            "--transaction",
            "terminal",
            "--confirm",
        )
        check(
            "terminal-transaction-refusal-is-not-rewritten",
            code == 2
            and result is not None
            and result.get("reason_codes") == ["TRANSACTION_ALREADY_TERMINAL"],
        )

        invalid_path = write_json(root, "invalid.json", {"request": {}})
        calls_before = len(service.calls)
        code, result = invoke(root, service, "reasoning", "plan", str(invalid_path))
        check(
            "malformed-command-envelope-fails-before-service",
            code == 2
            and result is not None
            and result.get("error", {}).get("code") == "GOVERNED_REASONING_INPUT_INVALID"
            and len(service.calls) == calls_before,
        )

        symlink = root / "linked.json"
        symlink.symlink_to(artifact_path)
        code, result = invoke(
            root,
            service,
            "reasoning",
            "validate",
            "request",
            str(symlink),
        )
        check(
            "symlink-input-is-rejected",
            code == 2
            and result is not None
            and result.get("error", {}).get("code") == "GOVERNED_REASONING_INPUT_INVALID",
        )

        oversized = root / "oversized.json"
        oversized.write_bytes(b" " * (cli.JSON_INPUT_MAX_BYTES + 1))
        code, result = invoke(
            root,
            service,
            "reasoning",
            "validate",
            "request",
            str(oversized),
        )
        check(
            "oversized-input-is-rejected",
            code == 2
            and result is not None
            and result.get("error", {}).get("code") == "GOVERNED_REASONING_INPUT_INVALID",
        )

        calls_before = len(service.calls)
        invalid_authority_results = []
        for index, authority_value in enumerate(([], {"unexpected": True})):
            invalid_path = write_json(root, f"invalid-authority-{index}.json", {**plan_document, "authority": authority_value})
            invalid_authority_results.append(invoke(root, service, "reasoning", "plan", str(invalid_path)))
        check(
            "invalid-authority-shape-or-key-fails-before-service",
            all(code == 2 and result is not None and result.get("error", {}).get("code") == "GOVERNED_REASONING_INPUT_INVALID" for code, result in invalid_authority_results)
            and len(service.calls) == calls_before,
        )

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
