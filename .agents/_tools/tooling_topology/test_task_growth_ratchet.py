#!/usr/bin/env python3
"""Twelve focused checks for the Git/worktree file-growth ratchet."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from tooling_topology.test_task_growth_contract import evaluate_growth_contract
from tooling_topology.test_tools_root_cardinality_integration import (
    evaluate_tools_root_cardinality_integration,
)


def main() -> None:
    results: list[dict[str, Any]] = [
        *evaluate_growth_contract(),
        *evaluate_tools_root_cardinality_integration(),
    ]
    passed = sum(1 for result in results if result["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
