#!/usr/bin/env python3
"""Focused acceptance for bounded governed challenge normalization."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.challenge import normalize_challenge  # noqa: E402
from governed_reasoning.contracts import validate_artifact  # noqa: E402
from governed_reasoning.planning import normalize_plan  # noqa: E402
from governed_reasoning.test_planning import fixtures  # noqa: E402


def main() -> None:
    snapshot, policy, request, plan_draft = fixtures()
    planned = normalize_plan(request, policy, snapshot, plan_draft, current_intent_sha256="0" * 64)
    plan, authority = planned["plan"], planned["plan"]["authority_sha256"]
    draft = {"critic_relation": "independent", "findings": [], "counterexamples": ["A stale source could invalidate the plan."], "limitations": [], "recommended_disposition": "proceed"}
    run = lambda value=draft, current=authority, req=request, receipt=plan: normalize_challenge(req, receipt, policy, value, expected_authority_sha256=current)
    first, second = run(), run()
    cases = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("independent-challenge-proceeds", first["ok"] and first["disposition"] == "proceed")
    check("deterministic-repeat", first == second)
    check("receipt-contract-valid", validate_artifact("challenge", first["challenge"]) == [])
    correlated = copy.deepcopy(draft); correlated.update(critic_relation="correlated", limitations=["Same model and evidence context were used."])
    check("correlated-critic-cannot-clear", "CORRELATED_CRITIC_CANNOT_CLEAR" in run(correlated)["reason_codes"])
    undisclosed = copy.deepcopy(correlated); undisclosed["limitations"] = []; undisclosed["recommended_disposition"] = "escalate"; undisclosed["findings"] = [{"finding_id": "finding-1", "category": "evidence", "severity": "material", "claim": "Independence is unproven.", "evidence_refs": [], "remediation": "Use an independent oracle."}]
    check("correlation-must-be-disclosed", "CRITIC_CORRELATION_NOT_DISCLOSED" in run(undisclosed)["reason_codes"])
    blocker = copy.deepcopy(undisclosed); blocker.update(critic_relation="independent", limitations=[], recommended_disposition="proceed"); blocker["findings"][0]["severity"] = "blocker"
    check("blocker-cannot-proceed", "BLOCKER_FINDING_NOT_BLOCKED" in run(blocker)["reason_codes"])
    material = copy.deepcopy(blocker); material["findings"][0]["severity"] = "material"
    check("material-cannot-proceed", "MATERIAL_FINDING_NOT_ESCALATED" in run(material)["reason_codes"])
    empty_block = copy.deepcopy(draft); empty_block["recommended_disposition"] = "block"
    check("unsupported-block-rejected", "CHALLENGE_FINDING_REQUIRED" in run(empty_block)["reason_codes"])
    dangling = copy.deepcopy(undisclosed); dangling.update(critic_relation="independent", limitations=[]); dangling["findings"][0]["evidence_refs"] = ["missing"]
    check("dangling-evidence-rejected", "CHALLENGE_EVIDENCE_REF_INVALID" in run(dangling)["reason_codes"])
    check("authority-mismatch-rejected", "CHALLENGE_AUTHORITY_MISMATCH" in run(current="f" * 64)["reason_codes"])
    tampered = copy.deepcopy(plan); tampered["steps"][0]["action"] = "Tampered"
    check("tampered-plan-rejected", "GOVERNED_CONTENT_HASH_INVALID" in run(receipt=tampered)["reason_codes"])
    oversized = copy.deepcopy(undisclosed); oversized.update(critic_relation="independent", limitations=[], recommended_disposition="block"); oversized["findings"] = [{**oversized["findings"][0], "finding_id": f"finding-{index}"} for index in range(33)]
    limited_result = run(oversized)
    check("finding-limit-enforced", "POLICY_FINDING_LIMIT_EXCEEDED" in limited_result["reason_codes"])
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False, indent=2)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
