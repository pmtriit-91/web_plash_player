#!/usr/bin/env python3
"""Focused acceptance for deterministic governed plan normalization."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.authority import inspect_authority  # noqa: E402
from governed_reasoning.contracts import content_hash, validate_artifact  # noqa: E402
from governed_reasoning.planning import normalize_plan  # noqa: E402

AGENT_ROOT = PACKAGE.parents[1]
HEX = "0" * 64


def hashed(value: dict) -> dict:
    value["content_sha256"] = content_hash(value)
    return value


def fixtures() -> tuple[dict, dict, dict, dict]:
    snapshot = inspect_authority(AGENT_ROOT)
    policy = hashed({"schema_version": 1, "policy_id": "policy-default", "project_id": "universal-agent-os", "overlay_mode": "restrict-only", "fail_closed": True, "authority": {"binding_required": True, "confirmed_genesis_required": True, "matching_intent_required": True, "matching_approval_when_required": True, "transaction_gates_required": True, "scores_cannot_override": True}, "risk": {"unknown_reversibility": "escalate", "irreversible_without_approval": "block", "constitution_conflict": "block", "low_confidence": "escalate"}, "limits": {"max_options": 16, "max_steps": 32, "max_findings": 32, "max_evidence_refs": 32, "max_retry_budget": 8, "max_artifact_bytes": 131072}, "content_sha256": HEX})
    request = hashed({"schema_version": 1, "request_id": "request-" + "1" * 24, "project_id": "universal-agent-os", "created_at": "2026-08-14T00:00:00Z", "goal": "Produce a bounded implementation plan.", "objectives": ["Preserve authority."], "constraints": ["Remain local-first."], "assumptions": [], "options": [{"option_id": "option-a", "summary": "Use deterministic normalization.", "reversibility": "reversible", "evidence_refs": ["source-1"], "risks": []}], "evidence": [{"evidence_id": "source-1", "kind": "git-blob", "reference": "docs/roadmap.md", "sha256": HEX, "git_commit": "0" * 40}], "authority": {"binding_sha256": snapshot["binding_sha256"], "genesis_revision": snapshot["genesis_revision"], "genesis_source_sha256": snapshot["genesis_source_sha256"], "intent_sha256": HEX, "approval_sha256": None, "policy_sha256": content_hash(policy)}, "privacy": {"raw_conversation_stored": False, "raw_prompt_stored": False, "chain_of_thought_stored": False, "secret_stored": False}, "content_sha256": HEX})
    draft = {"steps": [{"step_id": "step-1", "action": "Verify the bounded input.", "depends_on": [], "acceptance": ["Input is valid."], "evidence_refs": ["source-1"]}], "alternatives": [{"option_id": "option-a", "status": "candidate", "rationale": "It is bounded and deterministic."}], "uncertainties": [], "confidence": "high"}
    return snapshot, policy, request, draft


def main() -> None:
    snapshot, policy, request, draft = fixtures()
    run = lambda req=request, pol=policy, plan=draft, intent=HEX: normalize_plan(req, pol, snapshot, plan, current_intent_sha256=intent)
    first, second = run(), run()
    cases = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("deterministic-repeat", first == second and first["ok"])
    check("receipt-contract-valid", validate_artifact("plan", first["plan"]) == [])
    check("authority-bound", first["plan"]["authority_sha256"] and first["plan"]["request_sha256"] == content_hash(request))
    missing_goal = hashed({key: value for key, value in request.items() if key not in {"goal", "content_sha256"}})
    check("missing-goal-fails", "GOVERNED_ARTIFACT_INVALID" in run(req=missing_goal)["reason_codes"])
    missing_evidence = copy.deepcopy(request); missing_evidence["evidence"] = []; hashed(missing_evidence)
    check("missing-evidence-fails", "GOVERNED_ARTIFACT_INVALID" in run(req=missing_evidence)["reason_codes"])
    missing_budget = copy.deepcopy(policy); del missing_budget["limits"]; hashed(missing_budget)
    check("missing-budget-fails", "GOVERNED_ARTIFACT_INVALID" in run(pol=missing_budget)["reason_codes"])
    forward = copy.deepcopy(draft); forward["steps"][0]["depends_on"] = ["step-2"]
    check("forward-dependency-fails", "PLAN_DEPENDENCY_INVALID" in run(plan=forward)["reason_codes"])
    unknown = copy.deepcopy(draft); unknown["steps"][0]["evidence_refs"] = ["missing"]
    check("unknown-evidence-fails", "PLAN_EVIDENCE_REF_INVALID" in run(plan=unknown)["reason_codes"])
    alternatives = copy.deepcopy(draft); alternatives["alternatives"] = []
    check("missing-alternative-fails", "PLAN_ALTERNATIVES_INCOMPLETE" in run(plan=alternatives)["reason_codes"])
    check("stale-intent-fails", "INTENT_AUTHORITY_MISMATCH" in run(intent="f" * 64)["reason_codes"])
    bounded = copy.deepcopy(policy); bounded["limits"]["max_steps"] = 1; hashed(bounded)
    bounded_request = copy.deepcopy(request); bounded_request["authority"]["policy_sha256"] = content_hash(bounded); hashed(bounded_request)
    two_steps = copy.deepcopy(draft); two_steps["steps"].append({"step_id": "step-2", "action": "Finish.", "depends_on": ["step-1"], "acceptance": ["Finished."], "evidence_refs": []})
    check("restrictive-step-limit-fails", "POLICY_STEP_LIMIT_EXCEEDED" in run(req=bounded_request, pol=bounded, plan=two_steps)["reason_codes"])
    suite = json.loads((AGENT_ROOT / "evals/governed-reasoning-adversarial.json").read_text())
    check("adversarial-fixture-bounded", suite["authority"] == "test-fixture-only" and len(suite["cases"]) == 8)
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False, indent=2)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
