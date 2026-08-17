"""Focused contracts for deterministic bounded CI summaries."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_ROOT.parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from eval_diagnostics import compact_summary as summary


def metadata(profile: str = "release") -> dict[str, Any]:
    return summary.metadata_from_environment(
        {
            "GITHUB_RUN_ID": "107",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": "a" * 40,
            "AGENT_OS_RANGE_BASE": "b" * 40,
            "AGENT_OS_WORKFLOW_SHA256": "c" * 64,
            "RUNNER_OS": "Windows",
        },
        profile=profile,
        step_name="bounded-evals",
    )


def build(result: dict[str, Any], returncode: int = 0) -> dict[str, Any]:
    return summary.build_summary(
        result,
        source_returncode=returncode,
        metadata=metadata(),
        started_at="2026-08-11T00:00:00+00:00",
        completed_at="2026-08-11T00:00:01+00:00",
        duration_seconds=1.25,
    )


def evaluate() -> list[dict[str, Any]]:
    success = build({"ok": True, "passed": 3, "total": 3})
    failed = build(
        {
            "ok": False,
            "passed": 1,
            "total": 2,
            "results": [
                {"id": "pass", "passed": True},
                {
                    "id": "fail",
                    "passed": False,
                    "diagnostics": {"error": "token=private-value safe=kept"},
                },
            ],
        },
        2,
    )
    timed_out = build(
        {
            "ok": False,
            "executable_cases": 4,
            "expected_executable_cases": 7,
            "automatic_retries": 0,
            "shards": [
                {
                    "id": "restore",
                    "ok": False,
                    "timed_out": True,
                    "timeout_seconds": 120,
                    "active_scenario": "diff-bound",
                    "protocol_errors": [{"code": "SHARD_TIMEOUT"}],
                }
            ],
        },
        124,
    )
    many = build(
        {
            "ok": False,
            "results": [
                {
                    "id": "x" * 500 + str(index),
                    "passed": False,
                    "diagnostics": {"error": "password=private " + "y" * 4000},
                }
                for index in range(50)
            ],
        },
        2,
    )
    secret_metadata = summary.metadata_from_environment(
        {"GITHUB_RUN_ID": "token=metadata-private", "RUNNER_OS": "macOS"},
        profile="diagnostic",
        step_name="secret=step-private safe-step",
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        json_path = root / "summary.json"
        markdown_path = root / "summary.md"
        args = argparse.Namespace(
            summary_json=str(json_path),
            summary_markdown=str(markdown_path),
            summary_profile="release",
            summary_step_name="bounded-evals",
        )
        emitted_code = summary.emit_summary(
            args,
            {"ok": True, "passed": 1, "total": 1},
            source_returncode=0,
            started_at="start",
            completed_at="end",
            duration_seconds=0.5,
            environment={"RUNNER_OS": "Windows"},
        )
        json_raw = json_path.read_bytes()
        markdown_raw = markdown_path.read_bytes()
        failed_pair_code = summary.emit_summary(
            argparse.Namespace(
                summary_json=str(json_path),
                summary_markdown=None,
                summary_profile="release",
                summary_step_name="step",
            ),
            {"ok": False},
            source_returncode=124,
            started_at="start",
            completed_at="end",
            duration_seconds=1,
        )
        write_error_code = summary.emit_summary(
            argparse.Namespace(
                summary_json=str(root / "missing" / "summary.json"),
                summary_markdown=str(root / "missing" / "summary.md"),
                summary_profile="release",
                summary_step_name="step",
            ),
            {"ok": True},
            source_returncode=0,
            started_at="start",
            completed_at="end",
            duration_seconds=1,
        )
        spec = root / "evals.json"
        spec.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": [
                        {
                            "id": "known",
                            "type": "firewall",
                            "path": "artifact.png",
                            "expected_blocked": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        success_json = root / "eval-success.json"
        failure_json = root / "eval-failure.json"
        command = [
            sys.executable,
            str(TOOLS_ROOT / "run-agent-os-evals.py"),
            "--evals",
            str(spec),
            "--summary-markdown",
            str(root / "eval.md"),
        ]
        cli_success = subprocess.run(
            [*command, "--summary-json", str(success_json)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        cli_failure = subprocess.run(
            [
                *command,
                "--include-case-id",
                "unknown",
                "--summary-json",
                str(failure_json),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        success_summary = json.loads(success_json.read_text(encoding="utf-8"))
        failure_summary = json.loads(failure_json.read_text(encoding="utf-8"))
    failed_text = json.dumps(failed, ensure_ascii=False)
    secret_text = json.dumps(secret_metadata, ensure_ascii=False)
    return [
        {"id": "success-summary-has-exact-allowlisted-outcome", "passed": success["conclusion"] == "success" and success["passed"] == success["total"] == 3},
        {"id": "failure-summary-keeps-only-redacted-failure-hash", "passed": len(failed["failures"]) == 1 and "private-value" not in failed_text and "diagnostic_sha256" in failed_text},
        {"id": "timeout-summary-keeps-shard-and-scenario", "passed": timed_out["conclusion"] == "timed_out" and timed_out["failures"][0].get("scenario") == "diff-bound"},
        {"id": "json-summary-is-eight-kib-bounded", "passed": len(summary.json_bytes(many)) <= summary.SUMMARY_JSON_MAX_BYTES and many["failures_truncated"] is True},
        {"id": "markdown-summary-is-four-kib-bounded", "passed": len(summary.markdown_bytes(many)) <= summary.SUMMARY_MARKDOWN_MAX_BYTES},
        {"id": "metadata-and-step-values-are-redacted", "passed": "metadata-private" not in secret_text and "step-private" not in secret_text and "[REDACTED]" in secret_text},
        {"id": "windows-output-uses-lf-and-terminal-newline", "passed": emitted_code == 0 and b"\r" not in json_raw + markdown_raw and json_raw.endswith(b"\n") and markdown_raw.endswith(b"\n")},
        {"id": "summary-pair-error-preserves-source-timeout", "passed": failed_pair_code == 124},
        {"id": "summary-write-error-fails-passing-source", "passed": write_error_code == 2},
        {"id": "eval-runner-success-emits-summary-and-exit-zero", "passed": cli_success.returncode == 0 and success_summary["source_returncode"] == 0 and success_summary["conclusion"] == "success"},
        {"id": "eval-runner-selection-failure-emits-summary-and-exit-two", "passed": cli_failure.returncode == 2 and failure_summary["source_returncode"] == 2 and failure_summary["conclusion"] == "failure"},
    ]


def main() -> None:
    results = evaluate()
    passed = sum(1 for result in results if result["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
