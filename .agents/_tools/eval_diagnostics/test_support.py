#!/usr/bin/env python3
"""Shared scenarios for aggregate-eval failure diagnostics acceptance."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

RUNNER = Path(__file__).resolve().parents[1] / "run-agent-os-evals.py"
SPEC = importlib.util.spec_from_file_location("agent_os_eval_runner", RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("eval runner cannot be loaded")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

SENSITIVE_FIXTURES = [
    (
        "openai-api-key",
        "OPENAI_API_KEY=sk-openai-private status=openai-kept",
        "sk-openai-private",
        "status=openai-kept",
    ),
    (
        "github-token",
        '"GITHUB_TOKEN": "ghp_github-private", "status": "github-kept"',
        "ghp_github-private",
        '"status": "github-kept"',
    ),
    (
        "aws-secret-access-key",
        "AWS_SECRET_ACCESS_KEY='aws/private+key='; region=aws-kept",
        "aws/private+key=",
        "region=aws-kept",
    ),
    (
        "client-secret",
        "client_secret=client-private next=client-kept",
        "client-private",
        "next=client-kept",
    ),
    (
        "refresh-token",
        "refresh-token: refresh-private, next=refresh-kept",
        "refresh-private",
        "next=refresh-kept",
    ),
    (
        "authorization-bearer",
        "Authorization: Bearer auth-private; trace=auth-kept",
        "auth-private",
        "trace=auth-kept",
    ),
    (
        "standalone-bearer",
        "request failed with bearer direct-private retry=bearer-kept",
        "direct-private",
        "retry=bearer-kept",
    ),
]


def structured_scenarios() -> tuple[Any, ...]:
    structured = runner.failure_diagnostics(
        {
            "parsed": {
                "ok": False,
                "passed": 1,
                "total": 2,
                "results": [
                    {"id": "passing-child", "passed": True},
                    {
                        "id": "failing-child",
                        "passed": "token=invalid-passed-private",
                        "error": "token=private-value",
                        "reason_codes": ["CHILD_FAILED"],
                    },
                ],
            },
            "stdout": "raw structured output",
            "stderr": "",
        }
    )
    failed_results = structured.get("child_result", {}).get("failed_results", [])
    case_structured = runner.failure_diagnostics(
        {
            "parsed": {
                "ok": False,
                "cases": [
                    {"id": "passing-case", "passed": True},
                    {"id": "failing-case", "passed": False},
                ],
            },
            "stdout": "raw case output",
            "stderr": "",
        }
    )
    failed_cases = case_structured.get("child_result", {}).get("failed_results", [])
    unparsed = runner.failure_diagnostics(
        {
            "parsed": {},
            "stdout": "plain failure output",
            "stderr": (
                'password=hunter2 Authorization: Bearer bearer-private '
                '{"token": "json-private"} traceback'
            ),
        }
    )
    bounded = runner.failure_diagnostics(
        {
            "parsed": {},
            "stdout": "OPENAI_API_KEY="
            + ("s" * (runner.DIAGNOSTIC_TEXT_LIMIT + 1000)),
            "stderr": "",
        }
    )
    unrecognized = runner.failure_diagnostics(
        {
            "parsed": {"unexpected": "shape"},
            "stdout": "fallback detail",
            "stderr": "",
        }
    )
    many_failures = runner.failure_diagnostics(
        {
            "parsed": {
                "ok": False,
                "results": [
                    {"id": f"failure-{index}", "passed": False}
                    for index in range(runner.DIAGNOSTIC_FAILURE_LIMIT + 5)
                ],
            },
            "stdout": "",
            "stderr": "",
        }
    )
    evaluated = runner.evaluate(
        {
            "id": "end-to-end-failure",
            "type": "command",
            "argv": [
                sys.executable,
                "-c",
                (
                    "import json; "
                    "print(json.dumps({'ok': False, 'results': "
                    "[{'id': 'child', 'passed': False, "
                    "'error': 'secret=end-to-end-private'}]})); "
                    "raise SystemExit(2)"
                ),
            ],
            "expected_ok": True,
        },
        [],
    )
    timeout_result = runner.run_json(
        [
            sys.executable,
            "-c",
            (
                "import sys, time; "
                "print('timeout-detail', flush=True); "
                "sys.stderr.write('token=timeout-private\\n'); "
                "sys.stderr.flush(); "
                "time.sleep(2)"
            ),
        ],
        timeout=1,
    )
    heartbeat_output = io.StringIO()
    with contextlib.redirect_stderr(heartbeat_output):
        heartbeat_result = runner.run_json(
            [
                sys.executable,
                "-c",
                "import json,time; time.sleep(.35); print(json.dumps({'ok': True}))",
            ],
            timeout=2,
            label="heartbeat-case",
            heartbeat_seconds=0.1,
        )
    with tempfile.TemporaryDirectory() as temporary:
        sentinel = Path(temporary) / "descendant-survived.txt"
        descendant_source = (
            "import pathlib,time; time.sleep(3); "
            f"pathlib.Path({str(sentinel)!r}).write_text('survived', encoding='utf-8')"
        )
        parent_source = (
            "import json,subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {descendant_source!r}]); "
            "print(json.dumps({'ok': False}), flush=True); time.sleep(30)"
        )
        process_tree_result = runner.run_json(
            [sys.executable, "-c", parent_source],
            timeout=1,
            label="process-tree-case",
        )
        time.sleep(2.5)
        descendant_survived = sentinel.exists()
    limited_failures = many_failures.get("child_result", {}).get(
        "failed_results", []
    )
    return (
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
        heartbeat_output.getvalue(),
        process_tree_result,
        descendant_survived,
    )


def sensitive_scenarios() -> tuple[Any, ...]:
    sensitive_results = [
        (
            fixture_id,
            runner.diagnostic_text(source),
            private_value,
            safe_suffix,
        )
        for fixture_id, source, private_value, safe_suffix in SENSITIVE_FIXTURES
    ]
    false_positive_source = (
        "tokenizer=word monkey=banana authorization_code=safe "
        "client_secretary=safe refresh_tokenizer=safe"
    )
    false_positive_result = runner.diagnostic_text(false_positive_source)
    return sensitive_results, false_positive_source, false_positive_result
