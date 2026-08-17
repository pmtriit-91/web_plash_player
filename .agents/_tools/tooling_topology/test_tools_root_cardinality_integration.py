#!/usr/bin/env python3
"""Three focused checks for task-growth tools-root cardinality integration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capacity import check_growth
from tooling_topology.task_growth_support import build_growth_fixture, write


def evaluate_tools_root_cardinality_integration() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        baseline, envelope, restore = build_growth_fixture(root)
        tools_envelope = {
            **envelope,
            "paths": [
                {
                    "path": ".agents/_tools/existing.py",
                    "artifact_class": "source-test",
                }
            ],
        }
        write(
            root,
            ".agents/_tools/existing.py",
            baseline[".agents/_tools/existing.py"] + b"x\n",
        )
        result = check_growth(root, tools_envelope)
        check(
            "existing-tools-root-file-change-is-admitted",
            result["ok"] and result["root_cardinality"]["state"] == "ADMITTED",
        )
        restore()

        write(root, ".agents/_tools/approved.py", b"x\n")
        approved_envelope = {
            **tools_envelope,
            "paths": [
                *tools_envelope["paths"],
                {
                    "path": ".agents/_tools/approved.py",
                    "artifact_class": "source-test",
                },
            ],
        }
        admitted = check_growth(root, approved_envelope)
        tight_envelope = {
            **approved_envelope,
            "budgets": {
                **approved_envelope["budgets"],
                "source_test_growth_lines": 0,
            },
        }
        budget_blocked = check_growth(root, tight_envelope)
        check(
            "base-approved-root-entrypoint-keeps-capacity-guards",
            admitted["ok"]
            and admitted["root_cardinality"]["approved_direct_files"] == ["approved.py"]
            and budget_blocked["reason_codes"]
            == ["CAPACITY_SOURCE_TEST_GROWTH_BUDGET_EXCEEDED"],
        )
        restore()

        write(root, ".agents/_tools/new.py", b"x\n")
        direct_envelope = {
            **tools_envelope,
            "paths": [
                *tools_envelope["paths"],
                {
                    "path": ".agents/_tools/new.py",
                    "artifact_class": "source-test",
                },
            ],
        }
        result = check_growth(root, direct_envelope)
        check(
            "direct-tools-file-addition-stops-with-root-reasons",
            result["state"] == "STOP_AND_SPLIT"
            and result["reason_codes"]
            == ["ROOT_DIRECT_FILE_ADDED", "ROOT_DIRECT_FILE_CARDINALITY_GROWTH"]
            and result["offending_paths"] == [".agents/_tools/new.py"],
        )

    return cases


def main() -> None:
    results = evaluate_tools_root_cardinality_integration()
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
