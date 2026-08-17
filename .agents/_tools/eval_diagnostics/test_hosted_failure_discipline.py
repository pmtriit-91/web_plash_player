#!/usr/bin/env python3
"""Release fixture for the universal hosted-failure debugging discipline."""

from __future__ import annotations

import json
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = AGENTS_ROOT.parent


def read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def contains_all(content: str, fragments: tuple[str, ...]) -> bool:
    normalized = " ".join(content.casefold().split())
    return all(
        " ".join(fragment.casefold().split()) in normalized for fragment in fragments
    )


def main() -> None:
    kernel = read(".agents/core/runtime-kernel.md")
    workflow = read(".agents/workflows/debugging.md")
    topology = json.loads(read(".agents/_tools/eval_diagnostics/topology.json"))
    evals = json.loads(read(".agents/evals/agent-os-evals.json"))
    fixture = "_tools/eval_diagnostics/test_hosted_failure_discipline.py"
    cases = [
        {
            "id": "kernel-makes-hosted-verification-a-final-evidence-surface",
            "passed": contains_all(
                kernel,
                (
                    "scarce final evidence surface",
                    "must not be rerun blindly",
                    "bounded compact summary",
                    "focused local reproduction",
                    "one evidence-bound hosted dispatch",
                ),
            ),
        },
        {
            "id": "workflow-forbids-blind-reruns-and-automatic-retry",
            "passed": contains_all(
                workflow,
                (
                    "never press rerun repeatedly",
                    "never configure automatic retries",
                    "same failed evidence tuple",
                    "dispatch that new tuple exactly once",
                    "zero automatic retry",
                ),
            ),
        },
        {
            "id": "workflow-requires-summary-first-bounded-log-fallback",
            "passed": contains_all(
                workflow,
                (
                    "compact summary or compact artifact first",
                    "do not download or ingest the full raw log by default",
                    "bounded, targeted excerpt",
                    "full-log ingestion is an explicit last resort",
                ),
            ),
        },
        {
            "id": "workflow-requires-focused-then-full-local-acceptance",
            "passed": contains_all(
                workflow,
                (
                    "reproduce the smallest relevant case locally",
                    "run the focused local check again",
                    "full relevant local acceptance path",
                    "hosted-only uncertainty must be stated explicitly",
                ),
            ),
        },
        {
            "id": "workflow-requires-sparse-compact-monitoring",
            "passed": contains_all(
                workflow,
                (
                    "monitor sparsely from compact status",
                    "do not repeatedly stream or fetch verbose logs",
                    "inspect compact terminal artifacts once",
                ),
            ),
        },
        {
            "id": "topology-registers-focused-release-fixture",
            "passed": any(
                entry.get("entrypoint") == fixture
                and entry.get("focused_shard") == fixture
                for entry in topology.get("entries", [])
                if isinstance(entry, dict)
            ),
        },
        {
            "id": "aggregate-registers-focused-release-fixture",
            "passed": any(
                case.get("id") == "hosted-failure-discipline"
                and case.get("argv")
                == ["python3", f".agents/{fixture}"]
                for case in evals.get("cases", [])
                if isinstance(case, dict)
            ),
        },
    ]
    passed = sum(1 for case in cases if case["passed"])
    result = {
        "ok": passed == len(cases),
        "passed": passed,
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
