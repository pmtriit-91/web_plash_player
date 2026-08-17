#!/usr/bin/env python3
"""Focused acceptance for the adapter-neutral governed-reasoning service."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.challenge import normalize_challenge  # noqa: E402
from governed_reasoning.contracts import validate_artifact  # noqa: E402
from governed_reasoning.decision import normalize_decision  # noqa: E402
from governed_reasoning.planning import normalize_plan  # noqa: E402
from governed_reasoning.service import GovernedReasoningService  # noqa: E402
from governed_reasoning.test_planning import fixtures  # noqa: E402
from governed_reasoning.test_transactions import (  # noqa: E402
    plan_receipt,
    setup,
)

INTENT = "0" * 64


def invoke(service: GovernedReasoningService, name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(service, name, None)
    return method(*args, **kwargs) if callable(method) else None


def main() -> None:
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )
    snapshot, policy, request, plan_draft = fixtures()
    clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]

    with tempfile.TemporaryDirectory(prefix="governed-service-pure-") as holder:
        agent = Path(holder) / ".agents"
        service = GovernedReasoningService(
            agent,
            authority_inspector=lambda _: copy.deepcopy(snapshot),
            now=lambda: clock[0],
        )
        required = {
            "validate_artifact",
            "normalize_plan",
            "normalize_challenge",
            "normalize_decision",
            "plan_receipt",
            "apply_receipt",
            "recover_receipt",
        }
        check(
            "surface-is-complete-and-adapter-neutral",
            required <= {name for name in dir(service) if not name.startswith("_")},
        )
        before = sorted(path.relative_to(agent).as_posix() for path in agent.rglob("*"))
        validated = invoke(service, "validate_artifact", "request", request)
        invalid = copy.deepcopy(request)
        invalid["goal"] = "Tampered without rehash."
        rejected = invoke(service, "validate_artifact", "request", invalid)
        check(
            "validation-envelope-preserves-canonical-contract",
            validated == {"ok": True, "reason_codes": []}
            and rejected == {
                "ok": False,
                "reason_codes": validate_artifact("request", invalid),
            },
        )

        direct_plan = normalize_plan(
            request,
            policy,
            snapshot,
            plan_draft,
            current_intent_sha256=INTENT,
        )
        served_plan = invoke(
            service,
            "normalize_plan",
            request,
            policy,
            snapshot,
            plan_draft,
            current_intent_sha256=INTENT,
        )
        check("plan-normalization-has-exact-domain-parity", served_plan == direct_plan)

        challenge_draft = {
            "critic_relation": "independent",
            "findings": [],
            "counterexamples": ["A stale source could invalidate the plan."],
            "limitations": [],
            "recommended_disposition": "proceed",
        }
        plan = direct_plan["plan"]
        direct_challenge = normalize_challenge(
            request,
            plan,
            policy,
            challenge_draft,
            expected_authority_sha256=plan["authority_sha256"],
        )
        served_challenge = invoke(
            service,
            "normalize_challenge",
            request,
            plan,
            policy,
            challenge_draft,
            expected_authority_sha256=plan["authority_sha256"],
        )
        check(
            "challenge-normalization-has-exact-domain-parity",
            served_challenge == direct_challenge,
        )

        decision_draft = {
            "assessments": [
                {
                    "option_id": "option-a",
                    "evidence_score": 40,
                    "constraint_score": 30,
                    "risk_penalty": 5,
                    "evidence_refs": ["source-1"],
                }
            ],
            "confidence": "high",
            "retry_budget": 0,
        }
        challenge = direct_challenge["challenge"]
        direct_decision = normalize_decision(
            request,
            plan,
            challenge,
            policy,
            decision_draft,
            snapshot,
            current_intent_sha256=INTENT,
        )
        served_decision = invoke(
            service,
            "normalize_decision",
            request,
            plan,
            challenge,
            policy,
            decision_draft,
            snapshot,
            current_intent_sha256=INTENT,
        )
        check(
            "decision-normalization-has-exact-domain-parity",
            served_decision == direct_decision,
        )
        after = sorted(path.relative_to(agent).as_posix() for path in agent.rglob("*"))
        check("validate-and-normalize-are-no-write", after == before == [])

    with tempfile.TemporaryDirectory(prefix="governed-service-write-") as holder:
        agent, _authority, service = setup(Path(holder), clock)
        receipt = plan_receipt()
        planned = service.plan_receipt("plan", receipt)
        target = agent / f"project/reasoning/receipts/{receipt['receipt_id']}.json"
        check(
            "persistence-plan-is-bounded-and-no-write",
            planned["ok"] and planned["plan"]["status"] == "pending-approval" and not target.exists(),
        )
        plan_id = planned["plan"]["plan_id"]
        refused = service.apply_receipt(plan_id)
        check(
            "persistence-apply-requires-confirmation",
            refused.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"] and not target.exists(),
        )
        applied = service.apply_receipt(plan_id, confirm=True)
        transaction_id = applied["receipt"]["transaction_id"]
        check("confirmed-persistence-applies-exact-receipt", applied["ok"] and target.is_file())
        terminal_recovery = invoke(
            service,
            "recover_receipt",
            transaction_id,
            confirm=True,
        )
        check(
            "applied-receipt-is-never-recovered-or-deleted",
            isinstance(terminal_recovery, dict)
            and not terminal_recovery.get("ok")
            and target.is_file(),
        )

    with tempfile.TemporaryDirectory(prefix="governed-service-recovery-") as holder:
        agent, _authority, service = setup(Path(holder), clock)
        receipt = plan_receipt("plan-" + "4" * 24)
        plan = service.plan_receipt("plan", receipt)["plan"]
        os.environ["AGENT_OS_TEST_MODE"] = "1"
        try:
            service.transactions.apply(
                plan["plan_id"],
                True,
                test_crash_after_write=True,
            )
        except KeyboardInterrupt:
            pass
        finally:
            os.environ.pop("AGENT_OS_TEST_MODE", None)
        directory = next(
            path
            for path in (agent / "_runtime/governed-reasoning/transactions").iterdir()
            if not (path / "receipt.json").exists()
        )
        target = agent / plan["input"]["target"]
        refused = invoke(service, "recover_receipt", directory.name)
        check(
            "interrupted-create-recovery-requires-confirmation",
            isinstance(refused, dict)
            and refused.get("reason_codes") == ["WRITE_CONFIRMATION_REQUIRED"]
            and target.is_file(),
        )
        recovered = invoke(
            service,
            "recover_receipt",
            directory.name,
            confirm=True,
        )
        terminal = json.loads((directory / "receipt.json").read_text())
        check(
            "confirmed-interrupted-create-recovery-is-terminal",
            isinstance(recovered, dict)
            and recovered.get("ok")
            and not target.exists()
            and terminal.get("status") == "recovered-rolled-back",
        )
        check(
            "recovery-replay-fails-closed",
            not invoke(
                service,
                "recover_receipt",
                directory.name,
                confirm=True,
            ).get("ok"),
        )

    topology = json.loads((PACKAGE / "topology.json").read_text(encoding="utf-8"))
    entry = next(
        item
        for item in topology["entries"]
        if item["entrypoint"] == "_tools/governed_reasoning/service.py"
    )
    check(
        "topology-binds-service-owner-dependencies-and-focused-shard",
        entry["focused_shard"] == "_tools/governed_reasoning/test_service.py"
        and {
            "_tools/governed_reasoning/contracts.py",
            "_tools/governed_reasoning/planning.py",
            "_tools/governed_reasoning/challenge.py",
            "_tools/governed_reasoning/decision.py",
            "_tools/governed_reasoning/transactions.py",
            "_tools/governed_reasoning/recovery.py",
        }
        <= set(entry["depends_on"]),
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
