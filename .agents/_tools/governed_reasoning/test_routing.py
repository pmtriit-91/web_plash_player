"""Focused acceptance for governed-reasoning routing projections."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parents[1]
AGENT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

from agent_os_capabilities import route_capability, validate_catalog
from agent_os_resolver import resolve_workflow


def load(relative: str) -> Any:
    return json.loads((AGENT / relative).read_text(encoding="utf-8"))


def read(relative: str) -> str:
    return (AGENT / relative).read_text(encoding="utf-8")


def main() -> None:
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )
    capabilities = load("routing/capability-registry.json")
    workflows = load("routing/workflow-registry.json")
    planner = read("workflows/planner.md")
    reviewer = read("workflows/reviewer.md")
    routes = capabilities.get("capabilities", {})
    architecture = routes.get("architecture_refactor", {})
    expected_capabilities = {
        "fast_ui_fix",
        "standard_feature",
        "architecture_refactor",
        "agent_os_maintenance",
        "notebooklm_research",
        "security_review",
        "quality_gates",
    }
    expected_workflows = {
        "planner",
        "executor",
        "reviewer",
        "fast-task-loop",
        "advanced-agent-loop",
        "debugging",
        "refactoring",
        "creative-experience-loop",
        "frontend-runtime-verification-loop",
        "git-commit",
    }

    check(
        "routing-reuses-existing-capability-and-workflow-owners",
        set(routes) == expected_capabilities
        and set(workflows.get("workflows", {})) == expected_workflows,
    )
    check(
        "architecture-capability-declares-governed-reasoning-triggers",
        {
            "governed reasoning",
            "governed decision",
            "permission/risk policy",
            "adversarial challenge",
            "reasoning receipt",
        }
        <= set(architecture.get("triggers", [])),
    )
    check(
        "architecture-capability-keeps-constitutional-challenge-loads",
        architecture.get("mode") == "DEEP"
        and architecture.get("load")
        == [
            "skills/thinking/constitution-first/SKILL.md",
            "skills/thinking/architecture-challenge-framework/SKILL.md",
        ],
    )
    checks = set(architecture.get("checks", []))
    check(
        "capability-checks-bind-authority-review-and-transaction-boundaries",
        {
            "confirmed Genesis and current binding",
            "matching intent, approval and transaction gates",
            "critic correlation disclosure and counterexample",
            "explicit confirmation for persistence or recovery",
        }
        <= checks,
    )

    decision_route = route_capability(
        "Create a governed decision under the active permission/risk policy.",
        capabilities,
        overrides={},
    )
    challenge_route = route_capability(
        "Produce an adversarial challenge for a reasoning receipt.",
        capabilities,
        overrides={},
    )
    check(
        "governed-decision-and-challenge-select-existing-deep-capability",
        decision_route.get("selected", {}).get("id") == "architecture_refactor"
        and challenge_route.get("selected", {}).get("id") == "architecture_refactor",
    )
    ordinary = route_capability(
        "Implement a local feature component.", capabilities, overrides={}
    )
    check(
        "ordinary-feature-routing-remains-unchanged",
        ordinary.get("selected", {}).get("id") == "standard_feature",
    )

    planner_route = resolve_workflow(
        "Create a governed decision under the active permission/risk policy.", workflows
    )
    reviewer_route = resolve_workflow(
        "Run an adversarial challenge with critic correlation disclosure.", workflows
    )
    check(
        "governed-planning-routes-explicitly-to-planner",
        planner_route.get("id") == "planner"
        and not planner_route.get("fallback")
        and "governed decision" in planner_route.get("matched_triggers", []),
    )
    check(
        "adversarial-challenge-routes-explicitly-to-reviewer",
        reviewer_route.get("id") == "reviewer"
        and not reviewer_route.get("fallback")
        and "adversarial challenge" in reviewer_route.get("matched_triggers", []),
    )
    reviewer_entry = workflows.get("workflows", {}).get("reviewer", {})
    check(
        "cumulative-review-routing-contract-is-preserved",
        "cumulative phase review" in reviewer_entry.get("triggers", [])
        and "phase transition gate" in reviewer_entry.get("triggers", []),
    )

    planner_lower, reviewer_lower = planner.lower(), reviewer.lower()
    planner_normalized = " ".join(planner_lower.split())
    reviewer_normalized = " ".join(reviewer_lower.split())
    check(
        "planner-uses-canonical-service-without-second-router",
        "canonical governed-reasoning service" in planner_normalized
        and "không tạo router thứ hai" in planner_normalized,
    )
    check(
        "planner-cannot-self-certify-review-or-authority",
        "không được tự phát hành challenge/reviewer verdict" in planner_normalized
        and "không tự tạo product truth" in planner_normalized,
    )
    check(
        "reviewer-discloses-correlation-and-falsifies",
        "critic relation" in reviewer_normalized
        and "correlated" in reviewer_normalized
        and "counterexample" in reviewer_normalized,
    )
    check(
        "reviewer-cannot-grant-permission-or-apply",
        "không tự cấp authority" in reviewer_normalized
        and "không tự apply" in reviewer_normalized,
    )
    check(
        "cumulative-review-gate-remains-a-separate-contract",
        "cumulative phase review gate vẫn là gate riêng" in reviewer_normalized,
    )

    joined = "\n".join(
        [
            json.dumps(capabilities, ensure_ascii=False),
            json.dumps(workflows, ensure_ascii=False),
            planner,
            reviewer,
        ]
    ).lower()
    check(
        "routing-does-not-open-delegation-or-aos17",
        "aos-17" not in joined and "delegate" not in joined and "delegation" not in joined,
    )
    catalog = validate_catalog()
    check(
        "existing-capability-descriptor-and-decision-coverage-stays-valid",
        catalog.get("ok") is True and not catalog.get("errors"),
    )

    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
