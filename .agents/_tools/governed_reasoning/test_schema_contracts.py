#!/usr/bin/env python3
"""Focused structural and adversarial checks for governed-reasoning schemas."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / ".agents/core/contracts"
NAMES = (
    "governed-reasoning-request.schema.json",
    "governed-plan-receipt.schema.json",
    "governed-challenge-receipt.schema.json",
    "governed-decision-receipt.schema.json",
    "governed-reasoning-policy.schema.json",
)
HEX64 = "0" * 64


def resolve(schema: dict[str, Any], node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        target: Any = schema
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def valid(schema: dict[str, Any], node: Any, value: Any) -> bool:
    node = resolve(schema, node)
    if "oneOf" in node and sum(valid(schema, item, value) for item in node["oneOf"]) != 1:
        return False
    if "const" in node and value != node["const"]:
        return False
    if "enum" in node and value not in node["enum"]:
        return False
    expected = node.get("type")
    types = expected if isinstance(expected, list) else [expected] if expected else []
    checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list), "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int, "boolean": lambda: type(value) is bool, "null": lambda: value is None}
    if types and not any(checks[item]() for item in types):
        return False
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", 10**9):
            return False
        if "pattern" in node and re.fullmatch(node["pattern"], value) is None:
            return False
    if type(value) is int and not node.get("minimum", value) <= value <= node.get("maximum", value):
        return False
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", 10**9):
            return False
        if node.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            return False
        if "items" in node and not all(valid(schema, node["items"], item) for item in value):
            return False
    if isinstance(value, dict):
        required = set(node.get("required", []))
        properties = node.get("properties", {})
        if not required <= set(value) or node.get("additionalProperties") is False and not set(value) <= set(properties):
            return False
        if any(key in properties and not valid(schema, properties[key], item) for key, item in value.items()):
            return False
    for rule in node.get("allOf", []):
        condition = rule.get("if")
        branch = rule.get("then") if condition and valid(schema, condition, value) else rule.get("else")
        if branch is not None and not valid(schema, branch, value):
            return False
    return True


def privacy() -> dict[str, bool]:
    return {"raw_conversation_stored": False, "raw_prompt_stored": False, "chain_of_thought_stored": False, "secret_stored": False}


def samples() -> dict[str, dict[str, Any]]:
    request = {"schema_version": 1, "request_id": "request-" + "1" * 24, "project_id": "universal-agent-os", "created_at": "2026-08-14T00:00:00Z", "goal": "Choose a governed implementation option.", "objectives": ["Preserve authority."], "constraints": ["Remain local-first."], "assumptions": [{"claim": "The change is reversible.", "status": "inferred", "confidence": "medium", "evidence_refs": ["source-1"]}], "options": [{"option_id": "option-a", "summary": "Use the bounded path.", "reversibility": "reversible", "evidence_refs": ["source-1"], "risks": ["Implementation defect."]}], "evidence": [{"evidence_id": "source-1", "kind": "git-blob", "reference": "docs/roadmap.md", "sha256": HEX64, "git_commit": "0" * 40}], "authority": {"binding_sha256": HEX64, "genesis_revision": 2, "genesis_source_sha256": HEX64, "intent_sha256": HEX64, "approval_sha256": None, "policy_sha256": HEX64}, "privacy": privacy(), "content_sha256": HEX64}
    plan = {"schema_version": 1, "receipt_id": "plan-" + "2" * 24, "project_id": "universal-agent-os", "created_at": "2026-08-14T00:00:00Z", "request_sha256": HEX64, "authority_sha256": HEX64, "steps": [{"step_id": "step-1", "action": "Apply the bounded change.", "depends_on": [], "acceptance": ["Focused tests pass."], "evidence_refs": ["source-1"]}], "alternatives": [{"option_id": "option-b", "status": "rejected", "rationale": "It widens authority."}], "uncertainties": ["Hosted behavior is unobserved."], "confidence": "medium", "supersedes": None, "privacy": privacy(), "content_sha256": HEX64}
    challenge = {"schema_version": 1, "receipt_id": "challenge-" + "3" * 24, "project_id": "universal-agent-os", "created_at": "2026-08-14T00:00:00Z", "request_sha256": HEX64, "plan_sha256": HEX64, "authority_sha256": HEX64, "critic_relation": "partially-correlated", "findings": [{"finding_id": "finding-1", "category": "authority", "severity": "material", "claim": "Approval scope may be incomplete.", "evidence_refs": ["source-1"], "remediation": "Require an exact guard."}], "counterexamples": ["A stale approval must not proceed."], "limitations": ["Same runtime family."], "recommended_disposition": "escalate", "supersedes": None, "privacy": privacy(), "content_sha256": HEX64}
    decision = {"schema_version": 1, "receipt_id": "decision-" + "4" * 24, "project_id": "universal-agent-os", "created_at": "2026-08-14T00:00:00Z", "request_sha256": HEX64, "plan_sha256": HEX64, "challenge_sha256": HEX64, "authority_sha256": HEX64, "ranked_options": [{"option_id": "option-a", "rank": 1, "score": 10, "evidence_refs": ["source-1"]}], "selected_option_id": "option-a", "rejections": [], "disposition": "proceed", "reason_codes": ["AUTHORITY_VALID"], "stop_reason": None, "retry_budget": 0, "confidence": "high", "supersedes": None, "privacy": privacy(), "content_sha256": HEX64}
    policy = {"schema_version": 1, "policy_id": "policy-default", "project_id": "universal-agent-os", "overlay_mode": "restrict-only", "fail_closed": True, "authority": {"binding_required": True, "confirmed_genesis_required": True, "matching_intent_required": True, "matching_approval_when_required": True, "transaction_gates_required": True, "scores_cannot_override": True}, "risk": {"unknown_reversibility": "escalate", "irreversible_without_approval": "block", "constitution_conflict": "block", "low_confidence": "escalate"}, "limits": {"max_options": 16, "max_steps": 32, "max_findings": 32, "max_evidence_refs": 32, "max_retry_budget": 8, "max_artifact_bytes": 131072}, "content_sha256": HEX64}
    return dict(zip(NAMES, (request, plan, challenge, decision, policy), strict=True))


def main() -> None:
    schemas = {name: json.loads((CONTRACTS / name).read_text(encoding="utf-8")) for name in NAMES}
    fixtures = samples()
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("five-draft-2020-12-closed-contracts", all(item.get("$schema", "").endswith("2020-12/schema") and item.get("additionalProperties") is False for item in schemas.values()))
    check("valid-artifact-per-schema", all(valid(schemas[name], schemas[name], fixture) for name, fixture in fixtures.items()))
    for name, fixture in fixtures.items():
        extra = copy.deepcopy(fixture); extra["private_trace"] = "hidden"
        missing = copy.deepcopy(fixture); missing.pop(next(iter(schemas[name]["required"])))
        check(f"{name}-rejects-extra-and-missing", not valid(schemas[name], schemas[name], extra) and not valid(schemas[name], schemas[name], missing))
    private = copy.deepcopy(fixtures[NAMES[1]]); private["privacy"]["chain_of_thought_stored"] = True
    oversized = copy.deepcopy(fixtures[NAMES[0]]); oversized["options"] *= 17
    traversal = copy.deepcopy(fixtures[NAMES[0]]); traversal["evidence"][0]["reference"] = "../private.txt"
    blocked = copy.deepcopy(fixtures[NAMES[3]]); blocked.update(disposition="block", selected_option_id=None, stop_reason="Authority missing.")
    invalid_block = copy.deepcopy(blocked); invalid_block["selected_option_id"] = "option-a"
    permissive = copy.deepcopy(fixtures[NAMES[4]]); permissive["overlay_mode"] = "replace"
    check("privacy-attestation-fails-closed", not valid(schemas[NAMES[1]], schemas[NAMES[1]], private))
    check("cardinality-and-path-are-bounded", not valid(schemas[NAMES[0]], schemas[NAMES[0]], oversized) and not valid(schemas[NAMES[0]], schemas[NAMES[0]], traversal))
    check("decision-disposition-controls-selection", valid(schemas[NAMES[3]], schemas[NAMES[3]], blocked) and not valid(schemas[NAMES[3]], schemas[NAMES[3]], invalid_block))
    check("policy-cannot-replace-authority", not valid(schemas[NAMES[4]], schemas[NAMES[4]], permissive))
    check("schema-payload-budget", sum((CONTRACTS / name).stat().st_size for name in NAMES) <= 49152)
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
