"""Deterministic normalization of a bounded governed plan draft."""

from __future__ import annotations

import hashlib
from typing import Any

from governed_reasoning.authority import evaluate_authority
from governed_reasoning.contracts import (
    canonical_bytes,
    content_hash,
    validate_artifact,
)

DRAFT_FIELDS = {"steps", "alternatives", "uncertainties", "confidence"}
STEP_FIELDS = {"step_id", "action", "depends_on", "acceptance", "evidence_refs"}
ALTERNATIVE_FIELDS = {"option_id", "status", "rationale"}


def _blocked(reasons: list[str], disposition: str = "block") -> dict[str, Any]:
    return {
        "ok": False,
        "disposition": disposition,
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def _draft_reasons(
    request: dict[str, Any], policy: dict[str, Any], draft: Any
) -> list[str]:
    if not isinstance(draft, dict) or set(draft) != DRAFT_FIELDS:
        return ["PLAN_DRAFT_INVALID"]
    steps, alternatives = draft.get("steps"), draft.get("alternatives")
    uncertainties, confidence = draft.get("uncertainties"), draft.get("confidence")
    if (
        not isinstance(steps, list)
        or not steps
        or not isinstance(alternatives, list)
        or not isinstance(uncertainties, list)
        or confidence not in {"low", "medium", "high"}
    ):
        return ["PLAN_DRAFT_INVALID"]
    reasons: list[str] = []
    if len(steps) > policy["limits"]["max_steps"]:
        reasons.append("POLICY_STEP_LIMIT_EXCEEDED")
    step_ids = [item.get("step_id") for item in steps if isinstance(item, dict)]
    if any(not isinstance(item, dict) or set(item) != STEP_FIELDS for item in steps):
        reasons.append("PLAN_STEP_INVALID")
    elif len(step_ids) != len(set(step_ids)):
        reasons.append("PLAN_STEP_ID_DUPLICATE")
    else:
        seen: set[str] = set()
        for step in steps:
            dependencies = step.get("depends_on")
            if not isinstance(dependencies, list) or any(item not in seen for item in dependencies):
                reasons.append("PLAN_DEPENDENCY_INVALID")
            seen.add(step["step_id"])
    evidence_ids = {item["evidence_id"] for item in request["evidence"]}
    if any(
        not isinstance(step, dict)
        or not isinstance(step.get("evidence_refs"), list)
        or any(reference not in evidence_ids for reference in step["evidence_refs"])
        for step in steps
    ):
        reasons.append("PLAN_EVIDENCE_REF_INVALID")
    option_ids = {item["option_id"] for item in request["options"]}
    alternative_ids = [
        item.get("option_id") for item in alternatives if isinstance(item, dict)
    ]
    if (
        any(not isinstance(item, dict) or set(item) != ALTERNATIVE_FIELDS for item in alternatives)
        or len(alternative_ids) != len(set(alternative_ids))
        or set(alternative_ids) != option_ids
    ):
        reasons.append("PLAN_ALTERNATIVES_INCOMPLETE")
    return reasons


def normalize_plan(
    request: Any,
    policy: Any,
    snapshot: dict[str, Any],
    draft: Any,
    *,
    current_intent_sha256: str,
    current_approval_sha256: str | None = None,
    approval_required: bool = False,
    transaction_gates_valid: bool = True,
    constitution_conflict: bool = False,
) -> dict[str, Any]:
    authority = evaluate_authority(
        request,
        policy,
        snapshot,
        current_intent_sha256=current_intent_sha256,
        current_approval_sha256=current_approval_sha256,
        approval_required=approval_required,
        transaction_gates_valid=transaction_gates_valid,
        constitution_conflict=constitution_conflict,
    )
    if authority["disposition"] != "proceed":
        return _blocked(authority["reason_codes"], authority["disposition"])
    reasons = _draft_reasons(request, policy, draft)
    if reasons:
        return _blocked(reasons)
    body = {
        "schema_version": 1,
        "project_id": request["project_id"],
        "created_at": request["created_at"],
        "request_sha256": content_hash(request),
        "authority_sha256": authority["authority_sha256"],
        "steps": [
            {
                **step,
                "depends_on": sorted(step["depends_on"]),
                "evidence_refs": sorted(step["evidence_refs"]),
            }
            for step in draft["steps"]
        ],
        "alternatives": sorted(draft["alternatives"], key=lambda item: item["option_id"]),
        "uncertainties": sorted(draft["uncertainties"]),
        "confidence": draft["confidence"],
        "supersedes": None,
        "privacy": request["privacy"],
    }
    body["receipt_id"] = "plan-" + hashlib.sha256(canonical_bytes(body)).hexdigest()[:24]
    body["content_sha256"] = content_hash(body)
    reasons = validate_artifact("plan", body)
    if len(canonical_bytes(body)) > policy["limits"]["max_artifact_bytes"]:
        reasons.append("POLICY_ARTIFACT_LIMIT_EXCEEDED")
    if reasons:
        return _blocked(reasons)
    return {
        "ok": True,
        "disposition": "proceed",
        "reason_codes": ["PLAN_NORMALIZED"],
        "plan": body,
    }
