"""Fail-closed disposition policy and separately reported escalation metrics."""

from __future__ import annotations

from typing import Any

from governed_reasoning.contracts import validate_artifact

DISPOSITIONS = {"proceed", "escalate", "block"}


def resolve_disposition(
    policy: Any,
    authority: Any,
    challenge_disposition: str,
    *,
    confidence: str,
    retry_budget: int,
) -> dict[str, Any]:
    reasons = validate_artifact("policy", policy)
    if not isinstance(authority, dict) or authority.get("disposition") not in DISPOSITIONS:
        reasons.append("AUTHORITY_RESULT_INVALID")
    if challenge_disposition not in DISPOSITIONS:
        reasons.append("CHALLENGE_DISPOSITION_INVALID")
    if confidence not in {"low", "medium", "high"}:
        reasons.append("DECISION_CONFIDENCE_INVALID")
    if type(retry_budget) is not int or not 0 <= retry_budget <= 8:
        reasons.append("RETRY_BUDGET_INVALID")
    elif isinstance(policy, dict) and retry_budget > policy.get("limits", {}).get("max_retry_budget", -1):
        reasons.append("POLICY_RETRY_LIMIT_EXCEEDED")
    if reasons:
        return {"disposition": "block", "reason_codes": list(dict.fromkeys(reasons))}

    candidates: list[tuple[str, list[str]]] = []
    authority_disposition = authority["disposition"]
    if authority_disposition != "proceed":
        candidates.append((authority_disposition, authority.get("reason_codes", ["AUTHORITY_NOT_GRANTED"])))
    if challenge_disposition != "proceed":
        candidates.append((challenge_disposition, [f"CHALLENGE_{challenge_disposition.upper()}"]))
    if confidence == "low":
        disposition = policy["risk"]["low_confidence"]
        candidates.append((disposition, ["LOW_CONFIDENCE"]))
    if candidates:
        disposition = max((item[0] for item in candidates), key={"proceed": 0, "escalate": 1, "block": 2}.__getitem__)
        return {"disposition": disposition, "reason_codes": list(dict.fromkeys(reason for _, item_reasons in candidates for reason in item_reasons))}
    return {"disposition": "proceed", "reason_codes": ["POLICY_GATES_VALID"]}


def escalation_metrics(expected: list[str], observed: list[str]) -> dict[str, Any]:
    if not expected or len(expected) != len(observed) or any(item not in DISPOSITIONS for item in [*expected, *observed]):
        raise ValueError("ESCALATION_METRIC_INPUT_INVALID")
    required = sum(item != "proceed" for item in expected)
    permitted = len(expected) - required
    false_negative = sum(want != "proceed" and got == "proceed" for want, got in zip(expected, observed, strict=True))
    excessive = sum(want == "proceed" and got != "proceed" for want, got in zip(expected, observed, strict=True))
    return {
        "sample_count": len(expected),
        "required_escalation_count": required,
        "permitted_proceed_count": permitted,
        "false_negative_escalation_count": false_negative,
        "false_negative_escalation_rate": false_negative / required if required else 0.0,
        "excessive_escalation_count": excessive,
        "excessive_escalation_rate": excessive / permitted if permitted else 0.0,
    }
