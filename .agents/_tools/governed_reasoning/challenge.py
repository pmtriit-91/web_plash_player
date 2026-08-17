"""Bounded challenge receipts with explicit critic-correlation disclosure."""

from __future__ import annotations

import hashlib
from typing import Any

from governed_reasoning.contracts import (
    canonical_bytes,
    content_hash,
    validate_artifact,
)

DRAFT_FIELDS = {
    "critic_relation",
    "findings",
    "counterexamples",
    "limitations",
    "recommended_disposition",
}
FINDING_FIELDS = {
    "finding_id",
    "category",
    "severity",
    "claim",
    "evidence_refs",
    "remediation",
}


def _blocked(reasons: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "disposition": "block",
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def _draft_reasons(
    request: dict[str, Any], policy: dict[str, Any], draft: Any
) -> list[str]:
    if not isinstance(draft, dict) or set(draft) != DRAFT_FIELDS:
        return ["CHALLENGE_DRAFT_INVALID"]
    findings = draft.get("findings")
    counterexamples = draft.get("counterexamples")
    limitations = draft.get("limitations")
    relation = draft.get("critic_relation")
    disposition = draft.get("recommended_disposition")
    if (
        not isinstance(findings, list)
        or not isinstance(counterexamples, list)
        or not isinstance(limitations, list)
        or relation not in {"independent", "partially-correlated", "correlated", "unknown"}
        or disposition not in {"proceed", "escalate", "block"}
    ):
        return ["CHALLENGE_DRAFT_INVALID"]
    reasons: list[str] = []
    if len(findings) > policy["limits"]["max_findings"]:
        reasons.append("POLICY_FINDING_LIMIT_EXCEEDED")
    if any(not isinstance(item, dict) or set(item) != FINDING_FIELDS for item in findings):
        reasons.append("CHALLENGE_FINDING_INVALID")
    else:
        finding_ids = [item["finding_id"] for item in findings]
        if len(finding_ids) != len(set(finding_ids)):
            reasons.append("CHALLENGE_FINDING_ID_DUPLICATE")
        evidence_ids = {item["evidence_id"] for item in request["evidence"]}
        if any(
            reference not in evidence_ids
            for finding in findings
            for reference in finding["evidence_refs"]
        ):
            reasons.append("CHALLENGE_EVIDENCE_REF_INVALID")
        severities = {item["severity"] for item in findings}
        if "blocker" in severities and disposition != "block":
            reasons.append("BLOCKER_FINDING_NOT_BLOCKED")
        if "material" in severities and disposition == "proceed":
            reasons.append("MATERIAL_FINDING_NOT_ESCALATED")
    if disposition != "proceed" and not findings:
        reasons.append("CHALLENGE_FINDING_REQUIRED")
    if relation != "independent" and not limitations:
        reasons.append("CRITIC_CORRELATION_NOT_DISCLOSED")
    if relation in {"correlated", "unknown"} and disposition == "proceed":
        reasons.append("CORRELATED_CRITIC_CANNOT_CLEAR")
    return reasons


def normalize_challenge(
    request: Any,
    plan: Any,
    policy: Any,
    draft: Any,
    *,
    expected_authority_sha256: str,
) -> dict[str, Any]:
    reasons = [
        *validate_artifact("request", request),
        *validate_artifact("plan", plan),
        *validate_artifact("policy", policy),
    ]
    if reasons:
        return _blocked(reasons)
    if request["project_id"] != plan["project_id"]:
        reasons.append("CHALLENGE_PROJECT_MISMATCH")
    if plan["request_sha256"] != content_hash(request):
        reasons.append("CHALLENGE_REQUEST_MISMATCH")
    if plan["authority_sha256"] != expected_authority_sha256:
        reasons.append("CHALLENGE_AUTHORITY_MISMATCH")
    if policy["project_id"] != request["project_id"]:
        reasons.append("POLICY_PROJECT_MISMATCH")
    if request["authority"]["policy_sha256"] != content_hash(policy):
        reasons.append("CHALLENGE_POLICY_MISMATCH")
    reasons.extend(_draft_reasons(request, policy, draft))
    if reasons:
        return _blocked(reasons)
    body = {
        "schema_version": 1,
        "project_id": request["project_id"],
        "created_at": request["created_at"],
        "request_sha256": content_hash(request),
        "plan_sha256": content_hash(plan),
        "authority_sha256": plan["authority_sha256"],
        "critic_relation": draft["critic_relation"],
        "findings": sorted(draft["findings"], key=lambda item: item["finding_id"]),
        "counterexamples": sorted(draft["counterexamples"]),
        "limitations": sorted(draft["limitations"]),
        "recommended_disposition": draft["recommended_disposition"],
        "supersedes": None,
        "privacy": request["privacy"],
    }
    body["receipt_id"] = "challenge-" + hashlib.sha256(canonical_bytes(body)).hexdigest()[:24]
    body["content_sha256"] = content_hash(body)
    reasons = validate_artifact("challenge", body)
    if len(canonical_bytes(body)) > policy["limits"]["max_artifact_bytes"]:
        reasons.append("POLICY_ARTIFACT_LIMIT_EXCEEDED")
    if reasons:
        return _blocked(reasons)
    return {
        "ok": True,
        "disposition": draft["recommended_disposition"],
        "reason_codes": ["CHALLENGE_NORMALIZED"],
        "challenge": body,
    }
