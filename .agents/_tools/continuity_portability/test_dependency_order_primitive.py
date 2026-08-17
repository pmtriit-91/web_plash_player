#!/usr/bin/env python3
"""Focused P1b1 checks for the pure stable dependency-order primitive."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity_dependency_order import (
    DependencyOrderError,
    stable_dependency_order,
)


def reference(
    reference_id: str, dependencies: list[tuple[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "reference_id": reference_id,
        "dependencies": [
            {"relation": relation, "target_reference_id": target}
            for relation, target in dependencies or []
        ],
    }


def target(entry_id: str, path: str, *reference_ids: str) -> dict[str, Any]:
    return {"entry_id": entry_id, "path": path, "reference_ids": list(reference_ids)}


def rejected(reason_code: str, operation: Callable[[], object]) -> bool:
    try:
        operation()
    except DependencyOrderError as error:
        return error.reason_code == reason_code
    return False


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    check(
        "independent-targets-use-canonical-path-order",
        stable_dependency_order([], [target("z", "z.md"), target("a", "a.md")])
        == ["a", "z"],
    )
    chain_references = [
        reference("root"),
        reference("middle", [("requires", "root")]),
        reference("alias", [("requires", "root")]),
        reference("leaf", [("requires", "middle")]),
    ]
    check(
        "requires-chain-and-multi-reference-target-collapse",
        stable_dependency_order(
            chain_references,
            [
                target("leaf-entry", "a.md", "leaf"),
                target("root-entry", "z.md", "root"),
                target("middle-entry", "m.md", "middle", "alias"),
            ],
        )
        == ["root-entry", "middle-entry", "leaf-entry"],
    )
    check(
        "generated-from-orders-prerequisite-first",
        stable_dependency_order(
            [
                reference("source"),
                reference("projection", [("generated-from", "source")]),
            ],
            [
                target("projection", "a.md", "projection"),
                target("source", "z.md", "source"),
            ],
        )
        == ["source", "projection"],
    )
    check(
        "non-ordering-relation-is-ignored",
        stable_dependency_order(
            [reference("a", [("evidence-for", "z")]), reference("z")],
            [target("a", "a.md", "a"), target("z", "z.md", "z")],
        )
        == ["a", "z"],
    )
    check(
        "dependency-without-current-target-is-allowed",
        stable_dependency_order(
            [reference("present"), reference("change", [("requires", "present")])],
            [target("change", "change.md", "change")],
        )
        == ["change"],
    )
    check(
        "dangling-dependency-fails-closed",
        rejected(
            "PORTABILITY_DEPENDENCY_REFERENCE_MISSING",
            lambda: stable_dependency_order(
                [reference("a", [("requires", "missing")])], []
            ),
        ),
    )
    check(
        "cycle-outside-target-set-fails-closed",
        rejected(
            "PORTABILITY_DEPENDENCY_CYCLE",
            lambda: stable_dependency_order(
                [
                    reference("a", [("requires", "b")]),
                    reference("b", [("requires", "a")]),
                ],
                [],
            ),
        ),
    )
    check(
        "duplicate-catalog-reference-fails-closed",
        rejected(
            "PORTABILITY_DEPENDENCY_REFERENCE_DUPLICATE",
            lambda: stable_dependency_order([reference("a"), reference("a")], []),
        ),
    )
    check(
        "ambiguous-reference-to-target-fails-closed",
        rejected(
            "PORTABILITY_DEPENDENCY_TARGET_AMBIGUOUS",
            lambda: stable_dependency_order(
                [reference("a")],
                [target("one", "one.md", "a"), target("two", "two.md", "a")],
            ),
        ),
    )
    check(
        "unknown-target-reference-fails-closed",
        rejected(
            "PORTABILITY_DEPENDENCY_TARGET_REFERENCE_MISSING",
            lambda: stable_dependency_order([], [target("one", "one.md", "missing")]),
        ),
    )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
