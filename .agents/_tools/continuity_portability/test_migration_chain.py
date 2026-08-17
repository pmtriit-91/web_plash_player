#!/usr/bin/env python3
"""Focused P2a1 checks for the pure bounded migration-chain primitive."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity_migration_chain import (
    MigrationChainError,
    resolve_migration_chain,
)


def migration(identifier: str, source: int, target: int) -> dict[str, Any]:
    return {
        "migration_id": identifier,
        "source_generation": source,
        "target_generation": target,
        "provider": f"builtin:{identifier}",
        "fixture_marker": identifier,
    }


def rejected(reason_code: str, operation: Callable[[], object]) -> bool:
    try:
        operation()
    except MigrationChainError as error:
        return error.reason_code == reason_code
    return False


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    check("same-generation-needs-no-hop", resolve_migration_chain([], 2, 2) == [])
    direct = migration("v1-v2", 1, 2)
    check(
        "direct-hop-preserves-entry-fields",
        resolve_migration_chain([direct], 1, 2) == [direct],
    )
    unordered = [
        migration("v1-v2", 1, 2),
        migration("v0-v1", 0, 1),
    ]
    check(
        "two-hop-chain-is-source-ordered",
        [item["migration_id"] for item in resolve_migration_chain(unordered, 0, 2)]
        == ["v0-v1", "v1-v2"],
    )
    check(
        "unrelated-branch-does-not-change-unique-path",
        [
            item["migration_id"]
            for item in resolve_migration_chain(
                [*unordered, migration("v0-v4", 0, 4)], 0, 2
            )
        ]
        == ["v0-v1", "v1-v2"],
    )
    check(
        "missing-path-fails-closed",
        rejected(
            "CONTINUITY_MIGRATION_CHAIN_NOT_FOUND",
            lambda: resolve_migration_chain([migration("v0-v1", 0, 1)], 0, 2),
        ),
    )
    check(
        "alternate-path-fails-ambiguous",
        rejected(
            "CONTINUITY_MIGRATION_CHAIN_AMBIGUOUS",
            lambda: resolve_migration_chain(
                [*unordered, migration("v0-v2", 0, 2)], 0, 2
            ),
        ),
    )
    check(
        "cycle-fails-before-selection",
        rejected(
            "CONTINUITY_MIGRATION_CHAIN_CYCLE",
            lambda: resolve_migration_chain(
                [migration("v0-v1", 0, 1), migration("v1-v0", 1, 0)], 0, 1
            ),
        ),
    )
    check(
        "backward-edge-fails-non-monotonic",
        rejected(
            "CONTINUITY_MIGRATION_CHAIN_NON_MONOTONIC",
            lambda: resolve_migration_chain([migration("v2-v1", 2, 1)], 0, 1),
        ),
    )
    eight_hops = [migration(f"v{i}-v{i + 1}", i, i + 1) for i in range(8)]
    nine_hops = [*eight_hops, migration("v8-v9", 8, 9)]
    check(
        "eight-hop-cap-is-inclusive-and-nine-fails",
        len(resolve_migration_chain(eight_hops, 0, 8)) == 8
        and rejected(
            "CONTINUITY_MIGRATION_CHAIN_TOO_LONG",
            lambda: resolve_migration_chain(nine_hops, 0, 9),
        ),
    )
    check(
        "malformed-request-and-duplicate-id-fail-closed",
        rejected(
            "CONTINUITY_MIGRATION_CHAIN_INPUT_INVALID",
            lambda: resolve_migration_chain([], 2, 1),
        )
        and rejected(
            "CONTINUITY_MIGRATION_CHAIN_ID_DUPLICATE",
            lambda: resolve_migration_chain(
                [migration("same", 0, 1), migration("same", 1, 2)], 0, 2
            ),
        ),
    )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
