#!/usr/bin/env python3
"""Nine focused checks for task-growth path, budget, and byte contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capacity import check_growth
from tooling_topology.task_growth_support import build_growth_fixture, write

TOOL = TOOLS_ROOT / "agent_os_capacity.py"


def evaluate_growth_contract() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        baseline, envelope, restore = build_growth_fixture(root)
        result = check_growth(root, envelope)
        check(
            "clean-baseline-is-admitted", result["ok"] and len(result["generated"]) == 1
        )
        input_path = root / ".git" / "growth-envelope.json"
        input_path.write_text(json.dumps(envelope), encoding="utf-8")
        cli = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "check-growth",
                "--input",
                str(input_path),
                "--root",
                str(root),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        check(
            "cli-admits-clean-baseline",
            cli.returncode == 0 and json.loads(cli.stdout)["state"] == "ADMITTED",
        )

        write(root, "src/small.py", baseline["src/small.py"] + b"x\n")
        write(root, "docs/status.md", baseline["docs/status.md"] + b"x\n")
        write(root, "data/state.bin", baseline["data/state.bin"] + b"3")
        write(root, "build/projection.json", b"x" * 1000)
        result = check_growth(root, envelope)
        check(
            "bounded-class-growth-is-admitted",
            result["ok"] and result["generated"][0]["current_bytes"] == 1000,
        )
        restore()

        write(root, "src/large.py", baseline["src/large.py"] + b"x\n")
        result = check_growth(root, envelope)
        check(
            "oversized-growth-stops-with-path",
            result["reason_codes"] == ["CAPACITY_OVERSIZED_SOURCE_TEST_GROWTH"]
            and result["offending_paths"] == ["src/large.py"],
        )
        restore()

        failures = []
        for relative, extra in (
            ("src/small.py", b"x\n" * 3),
            ("docs/status.md", b"x\n" * 3),
            ("data/state.bin", b"123"),
        ):
            write(root, relative, baseline[relative] + extra)
            failures.extend(check_growth(root, envelope)["reason_codes"])
            restore()
        check("all-class-budgets-fail-closed", len(set(failures)) == 3)

        write(root, "extra.txt", b"x\n")
        result = check_growth(root, envelope)
        check(
            "undeclared-change-stops-with-path",
            result["offending_paths"] == ["extra.txt"],
        )
        restore()

        (root / "data/state.bin").unlink()
        (root / "data/state.bin").mkdir()
        invalid = check_growth(root, {"schema_version": 1})
        nonregular = check_growth(root, envelope)
        check(
            "invalid-envelope-and-nonregular-path-block",
            invalid["reason_codes"] == ["CAPACITY_ENVELOPE_INVALID"]
            and nonregular["reason_codes"] == ["CAPACITY_PATH_NOT_REGULAR"],
        )
        restore()

        invalid_base = {**envelope, "base_commit": "not-a-commit"}
        result = check_growth(root, invalid_base)
        check(
            "invalid-base-is-blocked",
            result["reason_codes"] == ["CAPACITY_BASE_COMMIT_INVALID"],
        )

        write(root, "data/state.bin", b"x" * 200001)
        result = check_growth(root, envelope)
        check(
            "byte-bound-is-enforced",
            result["reason_codes"] == ["CAPACITY_FILE_BYTE_LIMIT_EXCEEDED"]
            and result["offending_paths"] == ["data/state.bin"],
        )

    return cases


def main() -> None:
    results = evaluate_growth_contract()
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
