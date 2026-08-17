#!/usr/bin/env python3
"""Focused acceptance for deterministic governed decisions."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.challenge import normalize_challenge
from governed_reasoning.contracts import validate_artifact
from governed_reasoning.decision import normalize_decision
from governed_reasoning.planning import normalize_plan
from governed_reasoning.test_planning import fixtures, hashed


def main() -> None:
    snapshot, policy, request, plan_draft = fixtures()
    request["options"].append({"option_id": "option-b", "summary": "Use a weaker alternative.", "reversibility": "reversible", "evidence_refs": ["source-1"], "risks": ["Lower confidence."]}); hashed(request)
    plan_draft["alternatives"].append({"option_id": "option-b", "status": "candidate", "rationale": "Retained for comparison."})
    plan = normalize_plan(request, policy, snapshot, plan_draft, current_intent_sha256="0" * 64)["plan"]
    challenge_draft = {"critic_relation": "independent", "findings": [], "counterexamples": ["A stale source could invalidate the plan."], "limitations": [], "recommended_disposition": "proceed"}
    challenge = normalize_challenge(request, plan, policy, challenge_draft, expected_authority_sha256=plan["authority_sha256"])["challenge"]
    draft = {"assessments": [{"option_id": "option-b", "evidence_score": 20, "constraint_score": 20, "risk_penalty": 10, "evidence_refs": ["source-1"]}, {"option_id": "option-a", "evidence_score": 40, "constraint_score": 30, "risk_penalty": 5, "evidence_refs": ["source-1"]}], "confidence": "high", "retry_budget": 0}
    run = lambda value=draft, req=request, plan_value=plan, challenge_value=challenge, **kwargs: normalize_decision(req, plan_value, challenge_value, policy, value, snapshot, current_intent_sha256="0" * 64, **kwargs)
    first, second = run(), run(); cases = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("deterministic-repeat", first == second and first["ok"])
    check("receipt-contract-valid", validate_artifact("decision", first["decision"]) == [])
    check("highest-score-selected", first["decision"]["selected_option_id"] == "option-a")
    check("ranks-contiguous", [item["rank"] for item in first["decision"]["ranked_options"]] == [1, 2])
    check("rejection-rationale-present", first["decision"]["rejections"][0]["reason_code"] == "LOWER_DETERMINISTIC_SCORE")
    tie = copy.deepcopy(draft); tie["assessments"][0].update(evidence_score=40, constraint_score=30, risk_penalty=5)
    check("stable-option-id-tie-break", run(tie)["decision"]["selected_option_id"] == "option-a")
    check("constitution-conflict-blocks", run(constitution_conflict=True)["decision"]["disposition"] == "block")
    low = copy.deepcopy(draft); low["confidence"] = "low"
    check("low-confidence-escalates", run(low)["decision"]["disposition"] == "escalate")
    irreversible = copy.deepcopy(request); irreversible["options"][0]["reversibility"] = "irreversible"; hashed(irreversible)
    check("irreversible-without-approval-blocks", run(req=irreversible)["disposition"] == "block")
    escalated_draft = copy.deepcopy(challenge_draft); escalated_draft.update(recommended_disposition="escalate", findings=[{"finding_id": "finding-1", "category": "safety", "severity": "material", "claim": "Residual risk remains.", "evidence_refs": ["source-1"], "remediation": "Obtain owner review."}])
    escalated = normalize_challenge(request, plan, policy, escalated_draft, expected_authority_sha256=plan["authority_sha256"])["challenge"]
    escalated_result = run(challenge_value=escalated)["decision"]
    check("challenge-cannot-be-overridden-by-score", escalated_result["selected_option_id"] is None)
    check("stop-clears-autonomous-retry", escalated_result["retry_budget"] == 0 and escalated_result["stop_reason"] is not None)
    incomplete = copy.deepcopy(draft); incomplete["assessments"].pop()
    check("incomplete-options-fail", "DECISION_OPTIONS_INCOMPLETE" in run(incomplete)["reason_codes"])
    dangling = copy.deepcopy(draft); dangling["assessments"][0]["evidence_refs"] = ["missing"]
    check("dangling-evidence-fails", "DECISION_EVIDENCE_REF_INVALID" in run(dangling)["reason_codes"])
    excessive = copy.deepcopy(draft); excessive["retry_budget"] = 9
    check("retry-limit-fails-closed", run(excessive)["disposition"] == "block")
    tampered = copy.deepcopy(challenge); tampered["recommended_disposition"] = "block"
    check("tampered-challenge-fails", "GOVERNED_CONTENT_HASH_INVALID" in run(challenge_value=tampered)["reason_codes"])
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, indent=2)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
