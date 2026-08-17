#!/usr/bin/env python3
"""Remaining positive-route, fallback, card, and override acceptance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capabilities import capability_cards, route_capability

CASES = [
    ("Simplify code and reduce complexity without behavior changes.", "code-simplification"),
    ("Debug this regression and find the root cause.", "debugging-and-error-recovery"),
    ("Record this architecture decision as an ADR.", "documentation-and-adrs"),
    ("Harden authentication against untrusted input.", "security-and-hardening"),
    ("Verify the current API using official documentation.", "source-driven-development"),
    ("Use TDD and write a regression test before the fix.", "test-driven-development"),
]


def main() -> None:
    results: list[dict[str, object]] = []
    for index, (prompt, expected) in enumerate(CASES, start=7):
        routed = route_capability(prompt)
        selected = routed["selected"]
        results.append(
            {
                "id": f"positive-route-{index}",
                "passed": selected.get("id") == expected and bool(selected.get("evidence")),
            }
        )
    ambiguous = route_capability("Help me think about this ordinary task.")
    results.append(
        {
            "id": "low-confidence-fallback-emits-gap",
            "passed": ambiguous["selected"].get("id") == "standard_feature"
            and ambiguous["selected"].get("fallback") is True
            and ambiguous["capability_gap"].get("detected") is True,
        }
    )
    cards = capability_cards()
    results.append(
        {
            "id": "cards-expose-operational-memory",
            "passed": all(
                card.get("summary")
                and card.get("when_to_use")
                and card.get("not_for")
                and card.get("decision_ref")
                and card.get("permissions")
                and card.get("eval")
                for card in cards
            ),
        }
    )
    disabled = route_capability(
        "Review this PR for code quality before merge.",
        overrides={"code-review-and-quality": "disabled"},
    )
    results.append(
        {
            "id": "project-disabled-never-auto-routes",
            "passed": disabled["selected"].get("id") != "code-review-and-quality"
            and any(item.get("id") == "code-review-and-quality" and item.get("reason") == "project_override:disabled" for item in disabled["excluded"]),
        }
    )
    manual = route_capability(
        "Review this PR for code quality before merge.",
        overrides={"code-review-and-quality": "manual-only"},
    )
    explicit = route_capability(
        "Use code review and quality for this PR.",
        overrides={"code-review-and-quality": "manual-only"},
    )
    results.append(
        {
            "id": "manual-only-requires-explicit-name",
            "passed": manual["selected"].get("id") != "code-review-and-quality"
            and explicit["selected"].get("id") == "code-review-and-quality",
        }
    )
    passed = sum(1 for result in results if result["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
