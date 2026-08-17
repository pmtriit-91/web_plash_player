#!/usr/bin/env python3
"""Focused fixture for task Capacity Gate enforcement projections."""

from __future__ import annotations

import json
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
ROOT = TOOLS_ROOT.parent
PROJECT_ROOT = ROOT.parent


def read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def contains_all(content: str, values: list[str]) -> bool:
    lowered = content.lower()
    return all(value.lower() in lowered for value in values)


def main() -> None:
    governance = read("docs/work-governance-contract.md")
    core_agents = read(".agents/AGENTS.md")
    bootstrap = read(".agents/core/bootstrap.md")
    kernel = read(".agents/core/runtime-kernel.md")
    planner = read(".agents/workflows/planner.md")
    reviewer = read(".agents/workflows/reviewer.md")
    maintenance = read(".agents/skills/agent-os-maintenance/SKILL.md")
    w6_plan = read(
        "docs/evolution/aos-15/analysis/w6-opening-and-decomposition-plan.md"
    )
    evals = json.loads(read(".agents/evals/agent-os-evals.json"))

    projection_text = (
        f"{core_agents}\n{bootstrap}\n{kernel}\n{planner}\n{reviewer}\n{maintenance}"
    )
    cases = [
        {
            "id": "normative-capacity-authority",
            "passed": contains_all(
                governance,
                [
                    "Capacity Gate và phân rã bắt buộc",
                    "500 dòng",
                    "12 path",
                    "20 executable case",
                    "dừng trước production mutation",
                    "không được “cố làm cho xong”",
                ],
            ),
        },
        {
            "id": "boot-blocks-oversized-mutation",
            "passed": all(
                contains_all(
                    content,
                    [
                        "Capacity Gate",
                        "implementation",
                        "STOP_AND_SPLIT",
                        "writable scope",
                    ],
                )
                for content in (core_agents, bootstrap)
            ),
        },
        {
            "id": "kernel-keeps-project-authority-normative",
            "passed": contains_all(
                kernel,
                [
                    "bounded task envelope",
                    "STOP_AND_SPLIT",
                    "project authority",
                    "competing threshold",
                ],
            ),
        },
        {
            "id": "planner-requires-complete-envelope",
            "passed": contains_all(
                planner,
                [
                    "one primary outcome",
                    "exact writable paths",
                    "non-generated source/test diff",
                    "process-tree termination",
                    "Final Review",
                    "inventory-only",
                    "caller-supplied capacity envelope",
                    "primitive admission before source",
                    "STOP_AND_SPLIT",
                    ".agents/_tools",
                    "root_cardinality",
                    "resolved base",
                    "stable-public-entrypoint",
                    "Git base",
                    "self-authorize",
                ],
            ),
        },
        {
            "id": "reviewer-makes-overrun-a-blocker",
            "passed": contains_all(
                reviewer,
                [
                    "whole workstep diff",
                    "generated manifest/projection/receipt",
                    "descendant processes",
                    "blocker",
                    "must not waive",
                    "replay the same caller-supplied capacity envelope",
                    "reason_codes",
                    "offending_paths",
                    ".agents/_tools",
                    "root_cardinality",
                    "approved_direct_files",
                    "Git base",
                    "self-authorized",
                ],
            ),
        },
        {
            "id": "maintenance-separates-generated-scope",
            "passed": contains_all(
                maintenance,
                [
                    "Capacity Gate",
                    "generated",
                    "STOP_AND_SPLIT",
                    "rebuild and verify the release",
                    "caller-supplied capacity envelope",
                    "primitive admission before source",
                    "no inferred",
                    "waived",
                    ".agents/_tools",
                    "root_cardinality",
                    "stable public entrypoint",
                    "Git base",
                    "self-authorized",
                ],
            ),
        },
        {
            "id": "w6-parent-registry-tracks-current-authority",
            "passed": contains_all(
                w6_plan,
                [
                    "parent registry và current boot card",
                    "Parent node chỉ làm registry",
                    "SP0 Control plane",
                    "SP1 Safety",
                    "SP2 Recovery",
                    "SP3 Release",
                    "Mỗi task có đúng một behavior concern",
                    "inventory-only",
                    "STOP_AND_SPLIT",
                    "Context Memory active task",
                    "BR5",
                    "NAV",
                ],
            ),
        },
        {
            "id": "aggregate-registers-capacity-fixture",
            "passed": all(
                any(
                    case.get("id") == identifier
                    and case.get("argv") == ["python3", path]
                    for case in evals.get("cases", [])
                    if isinstance(case, dict)
                )
                for identifier, path in (
                    (
                        "task-capacity-decomposition-enforcement",
                        ".agents/_tools/tooling_topology/test_task_capacity_contract.py",
                    ),
                    (
                        "task-file-growth-ratchet",
                        ".agents/_tools/tooling_topology/test_task_growth_ratchet.py",
                    ),
                )
            ),
        },
        {
            "id": "release-projection-does-not-own-numeric-ceilings",
            "passed": all(
                marker not in projection_text
                for marker in ("500 LOC", "12 source path", "20 case/driver")
            ),
        },
        {
            "id": "projection-does-not-tighten-threshold-boundary",
            "passed": (
                "threshold is crossed" in projection_text
                and "threshold is met or exceeded" not in projection_text
            ),
        },
    ]
    passed = sum(1 for case in cases if case["passed"])
    output = {
        "ok": passed == len(cases),
        "passed": passed,
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
