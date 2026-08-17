#!/usr/bin/env python3
"""Focused compact-summary integration contracts for the W5 portability runner."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent.parent
RUNNER_PATH = TOOLS_DIR / "test-continuity-portability.py"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "aos15_w6_portability_summary_runner",
        RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load portability runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_patched(
    runner: ModuleType,
    root: Path,
    label: str,
    result: dict[str, Any],
    source_returncode: int,
) -> tuple[int, dict[str, Any]]:
    json_path = root / f"{label}.json"
    markdown_path = root / f"{label}.md"
    argv = [
        str(RUNNER_PATH),
        "--shard",
        "cli-integration",
        "--summary-json",
        str(json_path),
        "--summary-markdown",
        str(markdown_path),
    ]
    with (
        patch.object(sys, "argv", argv),
        patch.object(
            runner,
            "run_supervisor",
            return_value=(result, source_returncode),
        ),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        exit_code = runner.main()
    return exit_code, json.loads(json_path.read_text(encoding="utf-8"))


def main() -> None:
    runner = load_runner()
    cases: list[dict[str, Any]] = []
    timeout_registry = {
        item["id"]: item["timeout_seconds"] for item in runner.SHARDS
    }
    restore_shard = runner.SHARD_BY_ID["restore-admission-and-backup-guards"]
    cases.append(
        {
            "id": "only-restore-admission-receives-exact-180-second-default",
            "passed": runner.DEFAULT_SHARD_TIMEOUT_SECONDS == 120
            and runner.MAX_SHARD_TIMEOUT_SECONDS == 180
            and timeout_registry["restore-admission-and-backup-guards"] == 180
            and sum(value == 180 for value in timeout_registry.values()) == 1
            and sum(value == 120 for value in timeout_registry.values()) == 10,
        }
    )
    cases.append(
        {
            "id": "explicit-timeout-remains-a-global-diagnostic-override",
            "passed": runner.shard_timeout_seconds(restore_shard, None) == 180
            and runner.shard_timeout_seconds(restore_shard, 90) == 90,
        }
    )
    with tempfile.TemporaryDirectory(prefix="aos15-p3b2a3-") as temporary:
        root = Path(temporary)
        success_json = root / "success.json"
        success = subprocess.run(
            [
                sys.executable,
                str(RUNNER_PATH),
                "--shard",
                "cli-integration",
                "--summary-json",
                str(success_json),
                "--summary-markdown",
                str(root / "success.md"),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        success_summary = json.loads(success_json.read_text(encoding="utf-8"))
        cases.append(
            {
                "id": "portability-success-emits-summary-and-exit-zero",
                "passed": success.returncode == 0
                and success_summary["source_returncode"] == 0
                and success_summary["conclusion"] == "success",
            }
        )

        failure_result = {
            "ok": False,
            "automatic_retries": 0,
            "executable_cases": 0,
            "expected_executable_cases": 2,
            "shards": [{"id": "cli-integration", "ok": False, "timed_out": False}],
            "failed": ["cli-contract"],
            "harness_errors": [],
        }
        failure_code, failure_summary = run_patched(
            runner,
            root,
            "failure",
            failure_result,
            2,
        )
        cases.append(
            {
                "id": "portability-failure-summary-preserves-exit-two",
                "passed": failure_code == 2
                and failure_summary["source_returncode"] == 2
                and failure_summary["conclusion"] == "failure",
            }
        )

        timeout_result = {
            "ok": False,
            "automatic_retries": 0,
            "executable_cases": 0,
            "expected_executable_cases": 2,
            "shards": [
                {
                    "id": "cli-integration",
                    "ok": False,
                    "timed_out": True,
                    "timeout_seconds": 120,
                    "active_scenario": "cli-roundtrip",
                }
            ],
            "failed": [],
            "harness_errors": [],
        }
        timeout_code, timeout_summary = run_patched(
            runner,
            root,
            "timeout",
            timeout_result,
            124,
        )
        cases.append(
            {
                "id": "portability-timeout-summary-preserves-exit-124",
                "passed": timeout_code == 124
                and timeout_summary["source_returncode"] == 124
                and timeout_summary["conclusion"] == "timed_out",
            }
        )

    passed = sum(1 for case in cases if case["passed"])
    output = {
        "ok": passed == len(cases),
        "passed": passed,
        "total": len(cases),
        "results": cases,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
