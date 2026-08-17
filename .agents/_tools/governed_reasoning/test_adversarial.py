"""Integrated adversarial acceptance for governed reasoning."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
AGENT_ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.authority import evaluate_authority
from governed_reasoning.challenge import normalize_challenge
from governed_reasoning.contracts import validate_artifact
from governed_reasoning.decision import normalize_decision
from governed_reasoning.planning import normalize_plan
from governed_reasoning.policy import escalation_metrics
from governed_reasoning.test_planning import fixtures, hashed

HEX = "0" * 64
INTEGRATION_CASE_IDS = {
    "mission-drift-blocker",
    "correlated-critic-clear",
    "circular-success-score",
    "constitution-conflict",
    "stale-intent",
    "irreversible-without-approval",
    "invalid-transaction-gate",
    "matching-authority-proceed",
    "raw-private-payload",
    "privacy-attestation",
    "false-negative-escalation",
    "excessive-escalation",
}


def build_pipeline() -> tuple[dict[str, Any], ...]:
    snapshot, policy, request, plan_draft = fixtures()
    request["options"].append(
        {
            "option_id": "option-b",
            "summary": "Use a weaker alternative.",
            "reversibility": "reversible",
            "evidence_refs": ["source-1"],
            "risks": ["Lower confidence."],
        }
    )
    hashed(request)
    plan_draft["alternatives"].append(
        {
            "option_id": "option-b",
            "status": "candidate",
            "rationale": "Retained for adversarial comparison.",
        }
    )
    planned = normalize_plan(
        request,
        policy,
        snapshot,
        plan_draft,
        current_intent_sha256=HEX,
    )
    plan = planned["plan"]
    challenge_draft = {
        "critic_relation": "independent",
        "findings": [],
        "counterexamples": ["A stale source could invalidate the plan."],
        "limitations": [],
        "recommended_disposition": "proceed",
    }
    challenged = normalize_challenge(
        request,
        plan,
        policy,
        challenge_draft,
        expected_authority_sha256=plan["authority_sha256"],
    )
    decision_draft = {
        "assessments": [
            {
                "option_id": "option-a",
                "evidence_score": 100,
                "constraint_score": 100,
                "risk_penalty": 0,
                "evidence_refs": ["source-1"],
            },
            {
                "option_id": "option-b",
                "evidence_score": -100,
                "constraint_score": -100,
                "risk_penalty": 100,
                "evidence_refs": ["source-1"],
            },
        ],
        "confidence": "high",
        "retry_budget": 0,
    }
    return (
        snapshot,
        policy,
        request,
        plan,
        challenge_draft,
        challenged["challenge"],
        decision_draft,
    )


def finding(category: str, severity: str, claim: str) -> dict[str, Any]:
    return {
        "finding_id": "finding-1",
        "category": category,
        "severity": severity,
        "claim": claim,
        "evidence_refs": ["source-1"],
        "remediation": "Stop and reconcile with confirmed authority.",
    }


def main() -> None:
    (
        snapshot,
        policy,
        request,
        plan,
        clean_challenge_draft,
        clean_challenge,
        decision_draft,
    ) = build_pipeline()
    suite = json.loads(
        (AGENT_ROOT / "evals/governed-reasoning-adversarial.json").read_text(
            encoding="utf-8"
        )
    )
    evidence_path = (
        AGENT_ROOT.parent
        / "docs/evolution/aos-16/evidence/w5-adversarial-verification.json"
    )
    evidence = (
        json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence_path.is_file()
        else {}
    )
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )

    check(
        "legacy-plan-fixture-remains-bounded",
        suite.get("authority") == "test-fixture-only"
        and len(suite.get("cases", [])) == 8,
    )
    integration = suite.get("integration_envelope", {})
    integration_ids = {
        item.get("id")
        for item in integration.get("cases", [])
        if isinstance(item, dict)
    }
    check(
        "integration-envelope-declares-exact-adversarial-cases",
        integration.get("authority") == "test-fixture-only"
        and integration.get("execution") == "local-only"
        and integration_ids == INTEGRATION_CASE_IDS,
    )

    mission_draft = copy.deepcopy(clean_challenge_draft)
    mission_draft.update(
        findings=[
            finding(
                "mission-drift",
                "blocker",
                "The option conflicts with the confirmed mission.",
            )
        ],
        recommended_disposition="block",
    )
    mission = normalize_challenge(
        request,
        plan,
        policy,
        mission_draft,
        expected_authority_sha256=plan["authority_sha256"],
    )
    check(
        "mission-drift-blocker-stops",
        mission["disposition"] == "block"
        and mission["challenge"]["findings"][0]["category"] == "mission-drift",
    )

    correlated = copy.deepcopy(clean_challenge_draft)
    correlated.update(
        critic_relation="correlated",
        limitations=["The critic reused the same model and evidence context."],
    )
    check(
        "correlated-critic-cannot-clear",
        "CORRELATED_CRITIC_CANNOT_CLEAR"
        in normalize_challenge(
            request,
            plan,
            policy,
            correlated,
            expected_authority_sha256=plan["authority_sha256"],
        )["reason_codes"],
    )

    circular_draft = copy.deepcopy(clean_challenge_draft)
    circular_draft.update(
        findings=[
            finding(
                "completion",
                "material",
                "The success score only repeats the selected option.",
            )
        ],
        recommended_disposition="escalate",
    )
    circular = normalize_challenge(
        request,
        plan,
        policy,
        circular_draft,
        expected_authority_sha256=plan["authority_sha256"],
    )
    circular_decision = normalize_decision(
        request,
        plan,
        circular["challenge"],
        policy,
        decision_draft,
        snapshot,
        current_intent_sha256=HEX,
    )["decision"]
    check("circular-success-criterion-escalates", circular["disposition"] == "escalate")
    check(
        "high-score-cannot-override-challenge",
        circular_decision["disposition"] == "escalate"
        and circular_decision["selected_option_id"] is None,
    )

    authority_kwargs = {
        "current_intent_sha256": HEX,
        "confidence": "high",
    }
    constitution = evaluate_authority(
        request,
        policy,
        snapshot,
        constitution_conflict=True,
        **authority_kwargs,
    )
    stale = evaluate_authority(
        request,
        policy,
        snapshot,
        current_intent_sha256="f" * 64,
        confidence="high",
    )
    irreversible = copy.deepcopy(request)
    irreversible["options"][0]["reversibility"] = "irreversible"
    hashed(irreversible)
    approval = evaluate_authority(
        irreversible,
        policy,
        snapshot,
        **authority_kwargs,
    )
    transaction = evaluate_authority(
        request,
        policy,
        snapshot,
        transaction_gates_valid=False,
        **authority_kwargs,
    )
    valid = evaluate_authority(request, policy, snapshot, **authority_kwargs)
    check(
        "constitution-conflict-blocks",
        constitution["disposition"] == "block"
        and "CONSTITUTION_CONFLICT" in constitution["reason_codes"],
    )
    check(
        "stale-intent-blocks",
        stale["disposition"] == "block"
        and "INTENT_AUTHORITY_MISMATCH" in stale["reason_codes"],
    )
    check(
        "irreversible-without-approval-blocks",
        approval["disposition"] == "block"
        and "APPROVAL_REQUIRED" in approval["reason_codes"],
    )
    check(
        "invalid-transaction-gate-blocks",
        transaction["disposition"] == "block"
        and "TRANSACTION_GATE_INVALID" in transaction["reason_codes"],
    )
    check("matching-authority-proceeds", valid["disposition"] == "proceed")

    raw_payload = copy.deepcopy(request)
    raw_payload["raw_prompt"] = "SECRET-PAYLOAD"
    hashed(raw_payload)
    check(
        "raw-private-payload-is-rejected",
        "GOVERNED_ARTIFACT_INVALID" in validate_artifact("request", raw_payload),
    )
    private_attestation = copy.deepcopy(request)
    private_attestation["privacy"]["chain_of_thought_stored"] = True
    hashed(private_attestation)
    check(
        "private-attestation-fails-closed",
        "GOVERNED_ARTIFACT_INVALID"
        in validate_artifact("request", private_attestation),
    )
    clean_decision = normalize_decision(
        request,
        plan,
        clean_challenge,
        policy,
        decision_draft,
        snapshot,
        current_intent_sha256=HEX,
    )["decision"]
    serialized = json.dumps([plan, clean_challenge, clean_decision])
    check(
        "normalized-receipts-do-not-disclose-private-payload",
        "SECRET-PAYLOAD" not in serialized
        and all(not value for value in clean_decision["privacy"].values()),
    )

    unknown = copy.deepcopy(request)
    unknown["options"][0]["reversibility"] = "unknown"
    hashed(unknown)
    low_confidence = evaluate_authority(
        request,
        policy,
        snapshot,
        current_intent_sha256=HEX,
        confidence="low",
    )
    observed = [
        valid["disposition"],
        stale["disposition"],
        evaluate_authority(unknown, policy, snapshot, **authority_kwargs)["disposition"],
        approval["disposition"],
        low_confidence["disposition"],
        transaction["disposition"],
    ]
    expected = ["proceed", "block", "escalate", "block", "escalate", "block"]
    metrics = escalation_metrics(expected, observed)
    check("fixture-policy-disposition-matrix-matches", observed == expected)
    check(
        "false-negative-escalation-is-zero-observed",
        metrics["false_negative_escalation_count"] == 0
        and metrics["false_negative_escalation_rate"] == 0.0,
    )
    check(
        "excessive-escalation-is-zero-observed",
        metrics["excessive_escalation_count"] == 0
        and metrics["excessive_escalation_rate"] == 0.0,
    )
    injected = escalation_metrics(
        ["block", "proceed", "escalate", "proceed"],
        ["proceed", "block", "escalate", "proceed"],
    )
    check(
        "false-negative-and-excessive-metrics-remain-separate",
        injected["false_negative_escalation_count"] == 1
        and injected["false_negative_escalation_rate"] == 0.5
        and injected["excessive_escalation_count"] == 1
        and injected["excessive_escalation_rate"] == 0.5,
    )

    claim = evidence.get("claims", {}).get("critical_failure", "")
    check(
        "evidence-uses-zero-observed-bounded-wording",
        evidence.get("status") == "verified"
        and evidence.get("result", {}).get("passed") == 19
        and evidence.get("result", {}).get("total") == 19
        and claim
        == "zero observed critical failure in the declared local adversarial envelope"
        and evidence.get("claims", {}).get("absolute_guarantee") is False
        and evidence.get("claims", {}).get("field_maturity") is False,
    )

    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "metrics": metrics,
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
