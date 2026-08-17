#!/usr/bin/env python3
"""Focused contract tests for portable documentation governance."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def contains_all(content: str, values: list[str]) -> bool:
    normalized = " ".join(content.lower().split())
    return all(" ".join(value.lower().split()) in normalized for value in values)


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
    agents = read("AGENTS.md")
    bootstrap = read("core/bootstrap.md")
    kernel = read("core/runtime-kernel.md")
    planner = read("workflows/planner.md")
    reviewer = read("workflows/reviewer.md")
    template = read("project-template/documentation-map.md")
    notebook_skill = read("skills/notebooklm-research/SKILL.md")
    registry = json.loads(read("routing/capability-registry.json"))
    descriptor_document = json.loads(read("routing/capability-descriptors.json"))
    notebook_route = registry.get("capabilities", {}).get("notebooklm_research", {})
    notebook_descriptor = next(
        (
            item
            for item in descriptor_document.get("capabilities", [])
            if item.get("id") == "notebooklm_research"
        ),
        {},
    )
    proactive = resolve(
        "Synthesize conflicts in the curated research corpus before we decide "
        "a consequential system design."
    )
    local_fact = resolve(
        "Read this single local file and explain what the current function does."
    )

    cases = [
        {
            "id": "documentation-map-is-task-time-only",
            "passed": (
                contains_all(
                    agents,
                    [
                        "Before creating, renaming, or moving durable project documentation",
                        "placement and navigation authority only",
                        "absence must never affect boot",
                    ],
                )
                and "documentation-map.md" not in bootstrap
                and "documentation-map.md" not in kernel
            ),
        },
        {
            "id": "portable-scaffold-is-not-project-authority",
            "passed": contains_all(
                template,
                [
                    "release-owned scaffold",
                    "not project authority",
                    "placement and navigation only",
                    "must not parse the adapted map as project truth",
                    "missing-map behavior",
                ],
            ),
        },
        {
            "id": "planner-routes-documentation-before-creation",
            "passed": contains_all(
                planner,
                [
                    "Durable documentation routing",
                    "classify each artifact",
                    "single canonical authority",
                    "inbound references",
                    "does not block boot",
                ],
            ),
        },
        {
            "id": "reviewer-detects-documentation-drift",
            "passed": contains_all(
                reviewer,
                [
                    "Documentation integrity review",
                    "does not duplicate roadmap",
                    "machine-readable",
                    "historical references",
                    "raw conversation",
                    "runtime evidence",
                ],
            ),
        },
        {
            "id": "notebooklm-proactive-activation-is-bounded",
            "passed": (
                contains_all(
                    notebook_skill,
                    [
                        "Activation heuristic",
                        "Do not wait for the user to name NotebookLM",
                        "single local file",
                        "Stop querying",
                        "return to repository verification",
                    ],
                )
                and "curated research corpus" in notebook_route.get("triggers", [])
                and "stop when decision input is sufficient" in notebook_route.get("checks", [])
                and notebook_descriptor.get("version") == "1.3.0"
                and notebook_descriptor.get("permissions", {}).get("network") == "research-only"
                and notebook_descriptor.get("permissions", {}).get("external_state") == "explicit-approval"
            ),
        },
        {
            "id": "research-routing-positive-and-negative",
            "passed": (
                proactive.get("capability", {}).get("id") == "notebooklm_research"
                and local_fact.get("capability", {}).get("id") == "standard_feature"
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
