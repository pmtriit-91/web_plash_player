"""Focused acceptance for governed reasoning receipt graph integrity."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.challenge import normalize_challenge
from governed_reasoning.contracts import content_hash
from governed_reasoning.decision import normalize_decision
from governed_reasoning.planning import normalize_plan
from governed_reasoning.receipts import seal_receipt, validate_receipt_graph
from governed_reasoning.test_planning import fixtures


def receipt_fixture() -> tuple[list[dict], str, str]:
    snapshot, policy, request, plan_draft = fixtures()
    plan = normalize_plan(
        request,
        policy,
        snapshot,
        plan_draft,
        current_intent_sha256="0" * 64,
    )["plan"]
    challenge = normalize_challenge(
        request,
        plan,
        policy,
        {
            "critic_relation": "independent",
            "findings": [],
            "counterexamples": ["A stale source could invalidate the plan."],
            "limitations": [],
            "recommended_disposition": "proceed",
        },
        expected_authority_sha256=plan["authority_sha256"],
    )["challenge"]
    decision = normalize_decision(
        request,
        plan,
        challenge,
        policy,
        {
            "assessments": [
                {
                    "option_id": "option-a",
                    "evidence_score": 40,
                    "constraint_score": 30,
                    "risk_penalty": 5,
                    "evidence_refs": ["source-1"],
                }
            ],
            "confidence": "high",
            "retry_budget": 0,
        },
        snapshot,
        current_intent_sha256="0" * 64,
    )["decision"]
    return [plan, challenge, decision], content_hash(request), plan["authority_sha256"]


def reseal(kind: str, receipt: dict) -> dict:
    result = seal_receipt(kind, receipt)
    assert result["ok"], result
    return result["receipt"]


def main() -> None:
    graph, request_sha, authority_sha = receipt_fixture()
    run = lambda value=graph, **kwargs: validate_receipt_graph(
        value,
        project_id=kwargs.get("project_id", "universal-agent-os"),
        request_sha256=kwargs.get("request_sha256", request_sha),
        authority_sha256=kwargs.get("authority_sha256", authority_sha),
        expected_active_ids=kwargs.get("expected_active_ids"),
    )
    cases: list[dict[str, object]] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    check("canonical-graph-valid", run()["state"] == "VALID")
    check("active-leaves-deterministic", run()["active_receipt_ids"] == sorted(item["receipt_id"] for item in graph))
    draft = copy.deepcopy(graph[0]); draft.pop("content_sha256")
    check("seal-builds-canonical-hash", seal_receipt("plan", draft)["receipt"]["content_sha256"] == graph[0]["content_sha256"])
    check("seal-rejects-kind-mismatch", seal_receipt("challenge", draft)["state"] == "REJECTED")
    tampered = copy.deepcopy(graph); tampered[0]["confidence"] = "low"
    check("tamper-rejected", "GOVERNED_CONTENT_HASH_INVALID" in run(tampered)["reason_codes"])
    wrong_project = copy.deepcopy(graph); wrong_project[0]["project_id"] = "other"; wrong_project[0] = reseal("plan", wrong_project[0])
    check("wrong-project-rejected", "RECEIPT_PROJECT_MISMATCH" in run(wrong_project)["reason_codes"])
    check("wrong-request-rejected", "RECEIPT_REQUEST_MISMATCH" in run(request_sha256="f" * 64)["reason_codes"])
    check("wrong-authority-rejected", "RECEIPT_AUTHORITY_MISMATCH" in run(authority_sha256="f" * 64)["reason_codes"])
    dangling_plan = copy.deepcopy(graph); dangling_plan.pop(0)
    check("dangling-plan-binding-rejected", "RECEIPT_PLAN_BINDING_DANGLING" in run(dangling_plan)["reason_codes"])
    dangling_challenge = copy.deepcopy(graph); dangling_challenge.pop(1)
    check("dangling-challenge-binding-rejected", "RECEIPT_CHALLENGE_BINDING_DANGLING" in run(dangling_challenge)["reason_codes"])
    dangling_predecessor = copy.deepcopy(graph[0]); dangling_predecessor["receipt_id"] = "plan-111111111111111111111111"; dangling_predecessor["supersedes"] = "plan-222222222222222222222222"; dangling_predecessor = reseal("plan", dangling_predecessor)
    check("dangling-supersession-rejected", "RECEIPT_SUPERSESSION_DANGLING" in run([*graph, dangling_predecessor])["reason_codes"])
    successor = copy.deepcopy(graph[0]); successor["receipt_id"] = "plan-111111111111111111111111"; successor["supersedes"] = graph[0]["receipt_id"]; successor = reseal("plan", successor)
    extended = [*graph, successor]
    check("valid-supersession-selects-leaf", run(extended)["active_receipt_ids"] == sorted([graph[1]["receipt_id"], graph[2]["receipt_id"], successor["receipt_id"]]))
    check("stale-active-set-rejected", "RECEIPT_ACTIVE_SET_STALE" in run(extended, expected_active_ids=[item["receipt_id"] for item in graph])["reason_codes"])
    invalid_active = [*run()["active_receipt_ids"], "plan-ffffffffffffffffffffffff"]
    check("unknown-active-id-rejected", "RECEIPT_ACTIVE_SET_INVALID" in run(expected_active_ids=invalid_active)["reason_codes"])
    cycle_a = copy.deepcopy(graph[0]); cycle_a["receipt_id"] = "plan-aaaaaaaaaaaaaaaaaaaaaaaa"; cycle_a["supersedes"] = "plan-bbbbbbbbbbbbbbbbbbbbbbbb"; cycle_a = reseal("plan", cycle_a)
    cycle_b = copy.deepcopy(graph[0]); cycle_b["receipt_id"] = "plan-bbbbbbbbbbbbbbbbbbbbbbbb"; cycle_b["supersedes"] = cycle_a["receipt_id"]; cycle_b = reseal("plan", cycle_b)
    check("supersession-cycle-rejected", "RECEIPT_SUPERSESSION_CYCLE" in run([cycle_a, cycle_b])["reason_codes"])
    duplicate = [*graph, copy.deepcopy(graph[0])]
    check("duplicate-id-rejected", "RECEIPT_ID_DUPLICATE_OR_INVALID" in run(duplicate)["reason_codes"])
    agent_root = PACKAGE.parents[1]
    manifest = json.loads((agent_root / "_manifest/base-release-manifest.json").read_text())
    manifest_paths = {item["path"] for item in manifest["entries"]}
    check(
        "project-reasoning-data-excluded",
        "project/**" in manifest["excluded_scopes"]
        and not any(path.startswith("project/") for path in manifest_paths),
    )
    check(
        "project-reasoning-template-declared",
        (agent_root / "project-template/reasoning/.gitkeep").is_file(),
    )
    output = {"ok": all(item["passed"] for item in cases), "cases": cases}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 1)


if __name__ == "__main__":
    main()
