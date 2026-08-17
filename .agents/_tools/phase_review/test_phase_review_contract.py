#!/usr/bin/env python3
"""Focused fixture for cumulative phase review enforcement projections."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent


def read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def contains_all(content: str, values: list[str]) -> bool:
    lowered = content.lower()
    return all(value.lower() in lowered for value in values)


def resolve(prompt: str) -> dict[str, Any]:
    process = subprocess.run(
        [
            sys.executable,
            ".agents/_tools/agent_os_resolver.py",
            "resolve",
            "--prompt",
            prompt,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        return {}


def main() -> None:
    core_agents = read(".agents/AGENTS.md")
    bootstrap = read(".agents/core/bootstrap.md")
    kernel = read(".agents/core/runtime-kernel.md")
    reviewer = read(".agents/workflows/reviewer.md")
    maintenance = read(".agents/skills/agent-os-maintenance/SKILL.md")
    root_bridge = read("AGENTS.md")
    governance = read("docs/work-governance-contract.md")
    registry = json.loads(read(".agents/routing/workflow-registry.json"))
    reviewer_entry = registry.get("workflows", {}).get("reviewer", {})
    routing = resolve(
        "Before opening the next major Agent OS phase, run the cumulative phase "
        "review transition gate."
    )

    cases = [
        {
            "id": "normative-governance-authority",
            "passed": contains_all(
                governance,
                [
                    "Cumulative Phase Review Gate",
                    "normative authority",
                    "enforcement projection",
                ],
            ),
        },
        {
            "id": "boot-transition-block",
            "passed": all(
                contains_all(
                    content,
                    [
                        "major phase",
                        "REMEDIATION_REQUIRED",
                        "PASS_AFTER_REMEDIATION",
                        "reviewer",
                    ],
                )
                for content in (core_agents, bootstrap)
            ),
        },
        {
            "id": "kernel-invariant",
            "passed": contains_all(
                kernel,
                [
                    "dependent major phase",
                    "REMEDIATION_REQUIRED",
                    "enforcement projections",
                ],
            ),
        },
        {
            "id": "reviewer-execution-contract",
            "passed": contains_all(
                reviewer,
                [
                    "Cumulative phase review",
                    "durable-evidence reachability",
                    "PASS_AFTER_REMEDIATION",
                    "prevents release",
                ],
            ),
        },
        {
            "id": "routing-trigger",
            "passed": (
                "cumulative phase review" in reviewer_entry.get("triggers", [])
                and routing.get("workflow", {}).get("id") == "reviewer"
                and routing.get("capability", {}).get("id") == "agent_os_maintenance"
            ),
        },
        {
            "id": "source-bridge-and-maintenance-guard",
            "passed": (
                contains_all(
                    root_bridge,
                    [
                        "Cumulative Phase Review Gate",
                        ".agents/workflows/reviewer.md",
                        "Do not wait for the owner",
                    ],
                )
                and contains_all(
                    maintenance,
                    [
                        "cumulative phase review gate",
                        "project governance",
                        "Do not treat the skill",
                    ],
                )
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
