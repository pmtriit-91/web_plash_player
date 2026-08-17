#!/usr/bin/env python3
"""Focused acceptance for governed-reasoning contract and authority composition."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.authority import (  # noqa: E402
    evaluate_authority,
    inspect_authority,
)
from governed_reasoning.contracts import content_hash, validate_artifact  # noqa: E402

AGENT_ROOT = PACKAGE.parents[1]
HEX = "0" * 64


def policy() -> dict:
    value = {"schema_version": 1, "policy_id": "policy-default", "project_id": "universal-agent-os", "overlay_mode": "restrict-only", "fail_closed": True, "authority": {"binding_required": True, "confirmed_genesis_required": True, "matching_intent_required": True, "matching_approval_when_required": True, "transaction_gates_required": True, "scores_cannot_override": True}, "risk": {"unknown_reversibility": "escalate", "irreversible_without_approval": "block", "constitution_conflict": "block", "low_confidence": "escalate"}, "limits": {"max_options": 16, "max_steps": 32, "max_findings": 32, "max_evidence_refs": 32, "max_retry_budget": 8, "max_artifact_bytes": 131072}, "content_sha256": HEX}
    value["content_sha256"] = content_hash(value)
    return value


def request(snapshot: dict, active_policy: dict) -> dict:
    value = {"schema_version": 1, "request_id": "request-" + "1" * 24, "project_id": snapshot["project_id"], "created_at": "2026-08-14T00:00:00Z", "goal": "Choose a governed option.", "objectives": ["Preserve authority."], "constraints": [], "assumptions": [], "options": [{"option_id": "option-a", "summary": "Use a bounded change.", "reversibility": "reversible", "evidence_refs": ["source-1"], "risks": []}], "evidence": [{"evidence_id": "source-1", "kind": "git-blob", "reference": "docs/roadmap.md", "sha256": HEX, "git_commit": "0" * 40}], "authority": {"binding_sha256": snapshot["binding_sha256"], "genesis_revision": snapshot["genesis_revision"], "genesis_source_sha256": snapshot["genesis_source_sha256"], "intent_sha256": HEX, "approval_sha256": None, "policy_sha256": content_hash(active_policy)}, "privacy": {"raw_conversation_stored": False, "raw_prompt_stored": False, "chain_of_thought_stored": False, "secret_stored": False}, "content_sha256": HEX}
    value["content_sha256"] = content_hash(value)
    return value


def mutate(value: dict, function) -> dict:
    result = copy.deepcopy(value); function(result); result["content_sha256"] = content_hash(result); return result


def main() -> None:
    snapshot, active_policy = inspect_authority(AGENT_ROOT), policy()
    base = request(snapshot, active_policy)
    evaluate = lambda value=base, intent=HEX, **kwargs: evaluate_authority(value, active_policy, snapshot, current_intent_sha256=intent, **kwargs)
    cases: list[dict] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("current-binding-and-confirmed-genesis-available", snapshot.get("available") and snapshot.get("project_id") == "universal-agent-os")
    check("valid-request-and-restrictive-policy", validate_artifact("request", base) == [] and validate_artifact("policy", active_policy) == [])
    check("matching-authority-proceeds", evaluate()["disposition"] == "proceed")
    wrong = mutate(base, lambda item: item.update(project_id="foreign-project"))
    check("wrong-project-blocks", "WRONG_PROJECT" in evaluate(wrong)["reason_codes"])
    stale = mutate(base, lambda item: item["authority"].update(genesis_source_sha256="f" * 64))
    check("stale-genesis-blocks", "GENESIS_SOURCE_SHA256_MISMATCH" in evaluate(stale)["reason_codes"])
    foreign_policy = mutate(active_policy, lambda item: item.update(project_id="foreign-project"))
    foreign_request = mutate(base, lambda item: item["authority"].update(policy_sha256=content_hash(foreign_policy)))
    foreign_result = evaluate_authority(foreign_request, foreign_policy, snapshot, current_intent_sha256=HEX)
    check("foreign-policy-blocks", "POLICY_PROJECT_MISMATCH" in foreign_result["reason_codes"])
    intent = evaluate(intent="f" * 64)
    check("intent-mismatch-blocks", intent["disposition"] == "block" and "INTENT_AUTHORITY_MISMATCH" in intent["reason_codes"])
    irreversible = mutate(base, lambda item: item["options"][0].update(reversibility="irreversible"))
    check("irreversible-without-approval-blocks", "APPROVAL_REQUIRED" in evaluate(irreversible)["reason_codes"])
    approved = mutate(irreversible, lambda item: item["authority"].update(approval_sha256="a" * 64))
    check("matching-approval-proceeds", evaluate(approved, current_approval_sha256="a" * 64)["disposition"] == "proceed")
    unknown = mutate(base, lambda item: item["options"][0].update(reversibility="unknown"))
    check("unknown-reversibility-escalates", evaluate(unknown)["disposition"] == "escalate")
    owner_input = mutate(base, lambda item: item["assumptions"].append({"claim": "Owner preference is unknown.", "status": "owner-input-required", "confidence": "low", "evidence_refs": []}))
    check("owner-input-required-escalates", evaluate(owner_input)["disposition"] == "escalate")
    dangling = mutate(base, lambda item: item["assumptions"].append({"claim": "A claimed fact.", "status": "verified", "confidence": "high", "evidence_refs": ["missing-source"]}))
    check("dangling-evidence-blocks", "GOVERNED_EVIDENCE_REF_INVALID" in evaluate(dangling)["reason_codes"])
    restrictive = mutate(active_policy, lambda item: item["limits"].update(max_options=1, max_evidence_refs=1, max_artifact_bytes=1024))
    expanded = mutate(base, lambda item: (item["options"].append({**item["options"][0], "option_id": "option-b"}), item["evidence"].append({**item["evidence"][0], "evidence_id": "source-2"}), item["authority"].update(policy_sha256=content_hash(restrictive))))
    limited = evaluate_authority(expanded, restrictive, snapshot, current_intent_sha256=HEX)
    check("restrictive-overlay-limits-block", {"POLICY_OPTION_LIMIT_EXCEEDED", "POLICY_EVIDENCE_LIMIT_EXCEEDED", "POLICY_ARTIFACT_LIMIT_EXCEEDED"} <= set(limited["reason_codes"]))
    check("constitution-and-transaction-conflicts-block", evaluate(constitution_conflict=True)["disposition"] == "block" and evaluate(transaction_gates_valid=False)["disposition"] == "block")
    check("low-confidence-escalates", evaluate(confidence="low")["disposition"] == "escalate")
    unavailable = {**snapshot, "available": False, "reason_codes": ["GENESIS_AUTHORITY_UNAVAILABLE"]}
    check("missing-constitutional-authority-blocks", evaluate_authority(base, active_policy, unavailable, current_intent_sha256=HEX)["disposition"] == "block")
    tampered = copy.deepcopy(base); tampered["goal"] = "Changed without rehash."
    check("tampered-request-blocks", "GOVERNED_CONTENT_HASH_INVALID" in evaluate(tampered)["reason_codes"])
    topology = json.loads((PACKAGE / "topology.json").read_text(encoding="utf-8"))
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    expected = {"_tools/governed_reasoning/contracts.py", "_tools/governed_reasoning/authority.py", "_tools/governed_reasoning/planning.py", "_tools/governed_reasoning/challenge.py", "_tools/governed_reasoning/policy.py", "_tools/governed_reasoning/decision.py", "_tools/governed_reasoning/receipts.py", "_tools/governed_reasoning/transactions.py", "_tools/governed_reasoning/service.py", "_tools/governed_reasoning/recovery.py"}
    check("topology-has-one-way-owners", topology["domain"] == "governed-reasoning" and set(entries) == expected and all(item["owner"] and item["focused_shard"] for item in entries.values()))
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False, indent=2)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
