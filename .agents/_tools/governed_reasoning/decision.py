"""Deterministic option ranking beneath authority, challenge, and policy gates."""

from __future__ import annotations

import hashlib
from typing import Any

from governed_reasoning.authority import evaluate_authority
from governed_reasoning.contracts import (
    canonical_bytes,
    content_hash,
    validate_artifact,
)
from governed_reasoning.policy import resolve_disposition

DRAFT_FIELDS = {"assessments", "confidence", "retry_budget"}
ASSESSMENT_FIELDS = {"option_id", "evidence_score", "constraint_score", "risk_penalty", "evidence_refs"}


def _blocked(reasons: list[str]) -> dict[str, Any]:
    return {"ok": False, "disposition": "block", "reason_codes": list(dict.fromkeys(reasons))}


def _rank(request: dict[str, Any], draft: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(draft, dict) or set(draft) != DRAFT_FIELDS:
        return [], ["DECISION_DRAFT_INVALID"]
    assessments = draft.get("assessments")
    if not isinstance(assessments, list) or not assessments:
        return [], ["DECISION_ASSESSMENTS_INVALID"]
    reasons: list[str] = []
    if any(not isinstance(item, dict) or set(item) != ASSESSMENT_FIELDS for item in assessments):
        return [], ["DECISION_ASSESSMENT_INVALID"]
    option_ids = [item["option_id"] for item in assessments]
    expected_options = {item["option_id"] for item in request["options"]}
    if len(option_ids) != len(set(option_ids)) or set(option_ids) != expected_options:
        reasons.append("DECISION_OPTIONS_INCOMPLETE")
    evidence_ids = {item["evidence_id"] for item in request["evidence"]}
    for item in assessments:
        scores = (item["evidence_score"], item["constraint_score"], item["risk_penalty"])
        if any(type(value) is not int for value in scores) or not all(-100 <= value <= 100 for value in scores[:2]) or not 0 <= scores[2] <= 100:
            reasons.append("DECISION_SCORE_INVALID")
        refs = item["evidence_refs"]
        if not isinstance(refs, list) or len(refs) != len(set(refs)) or any(ref not in evidence_ids for ref in refs):
            reasons.append("DECISION_EVIDENCE_REF_INVALID")
    if reasons:
        return [], list(dict.fromkeys(reasons))
    ordered = sorted(assessments, key=lambda item: (-(item["evidence_score"] + item["constraint_score"] - item["risk_penalty"]), item["option_id"]))
    return [
        {"option_id": item["option_id"], "rank": index, "score": item["evidence_score"] + item["constraint_score"] - item["risk_penalty"], "evidence_refs": sorted(item["evidence_refs"])}
        for index, item in enumerate(ordered, 1)
    ], []


def normalize_decision(
    request: Any,
    plan: Any,
    challenge: Any,
    policy: Any,
    draft: Any,
    snapshot: dict[str, Any],
    *,
    current_intent_sha256: str,
    current_approval_sha256: str | None = None,
    approval_required: bool = False,
    transaction_gates_valid: bool = True,
    constitution_conflict: bool = False,
) -> dict[str, Any]:
    reasons = [*validate_artifact("request", request), *validate_artifact("plan", plan), *validate_artifact("challenge", challenge), *validate_artifact("policy", policy)]
    if reasons:
        return _blocked(reasons)
    authority = evaluate_authority(request, policy, snapshot, current_intent_sha256=current_intent_sha256, current_approval_sha256=current_approval_sha256, approval_required=approval_required, transaction_gates_valid=transaction_gates_valid, constitution_conflict=constitution_conflict, confidence=draft.get("confidence") if isinstance(draft, dict) else "low")
    if request["project_id"] != plan["project_id"] or request["project_id"] != challenge["project_id"]:
        reasons.append("DECISION_PROJECT_MISMATCH")
    if plan["request_sha256"] != content_hash(request) or challenge["request_sha256"] != content_hash(request):
        reasons.append("DECISION_REQUEST_MISMATCH")
    if challenge["plan_sha256"] != content_hash(plan):
        reasons.append("DECISION_PLAN_MISMATCH")
    if plan["authority_sha256"] != authority["authority_sha256"] or challenge["authority_sha256"] != authority["authority_sha256"]:
        reasons.append("DECISION_AUTHORITY_MISMATCH")
    ranked, rank_reasons = _rank(request, draft)
    reasons.extend(rank_reasons)
    if reasons:
        return _blocked(reasons)
    policy_result = resolve_disposition(policy, authority, challenge["recommended_disposition"], confidence=draft["confidence"], retry_budget=draft["retry_budget"])
    disposition, reason_codes = policy_result["disposition"], policy_result["reason_codes"]
    selected = ranked[0]["option_id"] if disposition == "proceed" else None
    rejections = []
    if selected is not None:
        winner_score = ranked[0]["score"]
        rejections = [{"option_id": item["option_id"], "reason_code": "DETERMINISTIC_TIE_BREAK" if item["score"] == winner_score else "LOWER_DETERMINISTIC_SCORE", "rationale": f"Ranked {item['rank']} with score {item['score']}; selected {selected} scored {winner_score}."} for item in ranked[1:]]
    body = {"schema_version": 1, "project_id": request["project_id"], "created_at": request["created_at"], "request_sha256": content_hash(request), "plan_sha256": content_hash(plan), "challenge_sha256": content_hash(challenge), "authority_sha256": authority["authority_sha256"], "ranked_options": ranked, "selected_option_id": selected, "rejections": rejections, "disposition": disposition, "reason_codes": reason_codes, "stop_reason": None if disposition == "proceed" else ";".join(reason_codes), "retry_budget": draft["retry_budget"] if disposition == "proceed" else 0, "confidence": draft["confidence"], "supersedes": None, "privacy": request["privacy"]}
    body["receipt_id"] = "decision-" + hashlib.sha256(canonical_bytes(body)).hexdigest()[:24]
    body["content_sha256"] = content_hash(body)
    reasons = validate_artifact("decision", body)
    if len(canonical_bytes(body)) > policy["limits"]["max_artifact_bytes"]:
        reasons.append("POLICY_ARTIFACT_LIMIT_EXCEEDED")
    if reasons:
        return _blocked(reasons)
    return {"ok": disposition == "proceed", "disposition": disposition, "reason_codes": reason_codes, "decision": body}
