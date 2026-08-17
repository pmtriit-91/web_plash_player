#!/usr/bin/env python3
"""Focused structured, bounded, fallback, evaluate and timeout diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
EVAL_REGISTRY = TOOLS_ROOT.parent / "evals" / "agent-os-evals.json"
sys.path.insert(0, str(TOOLS_ROOT))

from eval_diagnostics.test_support import runner, structured_scenarios

EXPLICIT_TIMEOUT_COMMANDS = {
    "v8-v9-migration-transactions": (
        90,
        ["python3", ".agents/_tools/migration/test_agent_os_migrations.py"],
    ),
    "update-transaction-recovery": (
        90,
        ["python3", ".agents/_tools/lifecycle/test_update_transaction_integration.py"],
    ),
    "release-manifest-provenance": (
        90,
        ["python3", ".agents/_tools/lifecycle/test_release_manifest_provenance.py"],
    ),
    "continuity-catalog-lifecycle": (
        120,
        [
            "python3",
            ".agents/_tools/continuity_core/test_privacy_terminal_contracts.py",
        ],
    ),
    "continuity-core-identity-path-contracts": (
        60,
        ["python3", ".agents/_tools/continuity_core/test_identity_path_contracts.py"],
    ),
    "continuity-core-payload-drift-contracts": (
        60,
        ["python3", ".agents/_tools/continuity_core/test_payload_drift_contracts.py"],
    ),
    "continuity-core-dependency-handoff-contracts": (
        90,
        [
            "python3",
            ".agents/_tools/continuity_core/test_dependency_handoff_contracts.py",
        ],
    ),
    "continuity-core-privacy-terminal-contracts": (
        90,
        [
            "python3",
            ".agents/_tools/continuity_core/test_privacy_terminal_contracts.py",
            "--focused",
        ],
    ),
}


def lifecycle_supervision_scenarios() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    responses = iter(
        [
            {
                "returncode": 0,
                "parsed": {
                    "ok": True,
                    "state": "BOUND",
                    "core": {"ok": True},
                    "adapter": {"ok": True, "state": "BOUND"},
                    "client_bridge": {"ok": True},
                },
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "timeout_seconds": 47,
                "attempts": 1,
                "automatic_retries": 0,
                "process_tree_terminated": False,
            },
            {
                "returncode": 124,
                "parsed": {},
                "stdout": "",
                "stderr": "token=lifecycle-timeout-private",
                "timed_out": True,
                "timeout_seconds": 47,
                "attempts": 1,
                "automatic_retries": 0,
                "process_tree_terminated": True,
            },
            {
                "returncode": 2,
                "parsed": {},
                "stdout": "not-json",
                "stderr": "lifecycle child failed",
                "timed_out": False,
                "timeout_seconds": 47,
                "attempts": 1,
                "automatic_retries": 0,
                "process_tree_terminated": False,
            },
        ]
    )
    calls: list[dict[str, Any]] = []
    original = runner.run_json

    def fake_run_json(
        argv: list[str],
        timeout: int = 30,
        *,
        label: str = "command",
        heartbeat_seconds: float = runner.EVAL_HEARTBEAT_SECONDS,
    ) -> dict[str, Any]:
        calls.append(
            {
                "argv": argv,
                "timeout": timeout,
                "label": label,
                "heartbeat_seconds": heartbeat_seconds,
            }
        )
        return next(responses)

    case = {
        "id": "synthetic-lifecycle",
        "type": "lifecycle",
        "command": "doctor",
        "expected_state": "derived",
        "expected_core_ok": True,
        "timeout_seconds": 47,
    }
    runner.run_json = fake_run_json
    try:
        success = runner.evaluate(case, [])
        timeout = runner.evaluate(case, [])
        malformed = runner.evaluate(case, [])
        invalid = runner.evaluate({**case, "timeout_seconds": 0}, [])
    finally:
        runner.run_json = original
    return success, timeout, malformed, invalid, calls


def evaluate_structured_diagnostics() -> list[dict[str, Any]]:
    (
        structured,
        failed_results,
        case_structured,
        failed_cases,
        unparsed,
        bounded,
        unrecognized,
        many_failures,
        evaluated,
        timeout_result,
        limited_failures,
        heartbeat_result,
        heartbeat_output,
        process_tree_result,
        descendant_survived,
    ) = structured_scenarios()
    selected, selection = runner.select_cases(
        [
            {"id": "first"},
            {"id": "offline"},
            {"id": "last"},
        ],
        include_case_ids=[],
        exclude_case_ids=["offline"],
    )
    try:
        runner.select_cases(
            [{"id": "first"}],
            include_case_ids=["unknown"],
            exclude_case_ids=[],
        )
    except runner.CaseSelectionError as error:
        unknown_reason = error.reason_code
        unknown_ids = error.case_ids
    else:
        unknown_reason = None
        unknown_ids = []
    try:
        runner.select_cases(
            [{"id": "first"}],
            include_case_ids=["first"],
            exclude_case_ids=["first"],
        )
    except runner.CaseSelectionError as error:
        conflict_reason = error.reason_code
    else:
        conflict_reason = None
    registry = json.loads(EVAL_REGISTRY.read_text(encoding="utf-8"))["cases"]
    registry_by_id = {case["id"]: case for case in registry}
    default_result = runner.evaluate(
        {
            "id": "implicit-default-timeout-contract",
            "type": "command",
            "argv": [sys.executable, "-c", 'print("{\\"ok\\":true}")'],
            "expected_ok": True,
        },
        [],
    )
    (
        lifecycle_success,
        lifecycle_timeout,
        lifecycle_malformed,
        lifecycle_invalid,
        lifecycle_calls,
    ) = lifecycle_supervision_scenarios()
    return [
        {
            "id": "structured-output-keeps-only-failed-child",
            "passed": bool(
                len(failed_results) == 1
                and failed_results[0].get("id") == "failing-child"
                and "passing-child" not in json.dumps(structured)
                and len(failed_cases) == 1
                and failed_cases[0].get("id") == "failing-case"
                and "passing-case" not in json.dumps(case_structured)
            ),
        },
        {
            "id": "diagnostics-redact-sensitive-assignments",
            "passed": bool(
                "private-value" not in json.dumps(structured)
                and "invalid-passed-private" not in json.dumps(structured)
                and "hunter2" not in json.dumps(unparsed)
                and "bearer-private" not in json.dumps(unparsed)
                and "json-private" not in json.dumps(unparsed)
                and "[REDACTED]" in json.dumps(structured)
                and "[REDACTED]" in json.dumps(unparsed)
            ),
        },
        {
            "id": "redaction-precedes-bounded-tail",
            "passed": bool(
                len(bounded.get("stdout_tail", "")) <= runner.DIAGNOSTIC_TEXT_LIMIT
                and ("s" * 100) not in bounded.get("stdout_tail", "")
                and "[REDACTED]" in bounded.get("stdout_tail", "")
            ),
        },
        {
            "id": "unrecognized-json-falls-back-to-output",
            "passed": unrecognized.get("stdout_tail") == "fallback detail",
        },
        {
            "id": "failed-child-count-is-bounded",
            "passed": bool(
                len(limited_failures) == runner.DIAGNOSTIC_FAILURE_LIMIT
                and limited_failures[-1].get("id") == "failure-19"
                and "failure-20" not in json.dumps(many_failures)
            ),
        },
        {
            "id": "evaluate-attaches-safe-child-diagnostics",
            "passed": bool(
                evaluated.get("passed") is False
                and evaluated.get("returncode") == 2
                and evaluated.get("diagnostics", {})
                .get("child_result", {})
                .get("failed_results", [{}])[0]
                .get("id")
                == "child"
                and "end-to-end-private" not in json.dumps(evaluated)
                and "[REDACTED]" in json.dumps(evaluated)
            ),
        },
        {
            "id": "timeout-keeps-decoded-partial-output",
            "passed": bool(
                timeout_result.get("timed_out") is True
                and timeout_result.get("returncode") == 124
                and "timeout-detail" in timeout_result.get("stdout", "")
                and "timeout-private" not in timeout_result.get("stderr", "")
                and "[REDACTED]" in timeout_result.get("stderr", "")
            ),
        },
        {
            "id": "command-supervision-emits-bounded-heartbeat",
            "passed": bool(
                heartbeat_result.get("parsed", {}).get("ok") is True
                and heartbeat_result.get("attempts") == 1
                and heartbeat_result.get("automatic_retries") == 0
                and runner.EVAL_HEARTBEAT_SECONDS == 5
                and '"event":"eval_heartbeat"' in heartbeat_output
                and '"case_id":"heartbeat-case"' in heartbeat_output
            ),
        },
        {
            "id": "timeout-terminates-complete-process-tree",
            "passed": bool(
                process_tree_result.get("timed_out") is True
                and process_tree_result.get("returncode") == 124
                and process_tree_result.get("process_tree_terminated") is True
                and process_tree_result.get("attempts") == 1
                and process_tree_result.get("automatic_retries") == 0
                and descendant_survived is False
            ),
        },
        {
            "id": "bounded-selection-preserves-spec-order",
            "passed": bool(
                [case["id"] for case in selected] == ["first", "last"]
                and selection
                == {
                    "mode": "exclude",
                    "requested_case_ids": ["offline"],
                    "selected_count": 2,
                    "spec_count": 3,
                }
            ),
        },
        {
            "id": "bounded-selection-rejects-unknown-case",
            "passed": bool(
                unknown_reason == "EVAL_CASE_SELECTION_UNKNOWN"
                and unknown_ids == ["unknown"]
            ),
        },
        {
            "id": "bounded-selection-rejects-conflicting-modes",
            "passed": conflict_reason == "EVAL_CASE_SELECTION_MODES_CONFLICT",
        },
        {
            "id": "exact-hosted-evals-have-evidence-bound-envelopes",
            "passed": bool(
                all(
                    registry_by_id.get(case_id, {}).get("timeout_seconds") == timeout
                    and registry_by_id[case_id].get("argv") == argv
                    and registry_by_id[case_id].get("expected_ok") is True
                    for case_id, (timeout, argv) in EXPLICIT_TIMEOUT_COMMANDS.items()
                )
                and registry_by_id[
                    "context-memory-freshness-contamination-and-coordination"
                ].get("timeout_seconds")
                == 300
                and default_result.get("timeout_seconds") == 30
                and default_result.get("attempts") == 1
                and default_result.get("automatic_retries") == 0
                and registry_by_id["lifecycle-state-is-derived"].get(
                    "timeout_seconds"
                )
                == 120
                and all(call["timeout"] == 47 for call in lifecycle_calls)
                and all(
                    call["label"] == "synthetic-lifecycle"
                    for call in lifecycle_calls
                )
                and lifecycle_success.get("passed") is True
                and "diagnostics" not in lifecycle_success
                and lifecycle_timeout.get("passed") is False
                and lifecycle_timeout.get("returncode") == 124
                and lifecycle_timeout.get("timed_out") is True
                and lifecycle_timeout.get("process_tree_terminated") is True
                and "lifecycle-timeout-private"
                not in json.dumps(lifecycle_timeout)
                and "[REDACTED]" in json.dumps(lifecycle_timeout)
                and lifecycle_malformed.get("passed") is False
                and lifecycle_malformed.get("returncode") == 2
                and lifecycle_malformed.get("timed_out") is False
                and lifecycle_malformed.get("diagnostics", {}).get("stdout_tail")
                == "not-json"
                and lifecycle_invalid.get("passed") is False
                and lifecycle_invalid.get("error")
                == "timeout_seconds must be an integer from 1 to 300"
                and len(lifecycle_calls) == 3
            ),
        },
    ]


def main() -> None:
    results = evaluate_structured_diagnostics()
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
