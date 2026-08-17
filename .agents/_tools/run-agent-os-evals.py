#!/usr/bin/env python3
"""Run dependency-free behavioral evals for Universal Agent OS."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from eval_diagnostics.compact_summary import (
    DIAGNOSTIC_FAILURE_LIMIT,
    add_summary_arguments,
    diagnostic_text,
    emit_summary,
    output_text,
)
from eval_diagnostics.compact_summary import (
    DIAGNOSTIC_TEXT_LIMIT as _DIAGNOSTIC_TEXT_LIMIT,
)

DIAGNOSTIC_TEXT_LIMIT = _DIAGNOSTIC_TEXT_LIMIT

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULT_EVALS = ROOT / "evals" / "agent-os-evals.json"
AGENTIGNORE = ROOT / ".agentignore"
EVAL_HEARTBEAT_SECONDS = 5
AUTOMATIC_RETRIES = 0


class CaseSelectionError(ValueError):
    """Fail-closed error for an invalid bounded eval selection."""

    def __init__(self, reason_code: str, case_ids: list[str] | None = None) -> None:
        self.reason_code = reason_code
        self.case_ids = case_ids or []
        super().__init__(reason_code)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _read_stream(
    stream: TextIO, stream_name: str, messages: queue.Queue[tuple[str, str | None]]
) -> None:
    try:
        for chunk in iter(lambda: stream.read(4096), ""):
            messages.put((stream_name, chunk))
    finally:
        messages.put((stream_name, None))


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return

    # Descendants may retain pipes after the group leader exits. The process group
    # remains addressable by the leader PID, so signal the complete group twice.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _emit_heartbeat(label: str, elapsed_seconds: float) -> None:
    event = {
        "event": "eval_heartbeat",
        "case_id": diagnostic_text(label),
        "elapsed_seconds": round(elapsed_seconds, 1),
        "attempt": 1,
        "automatic_retries": AUTOMATIC_RETRIES,
    }
    print(
        "AGENT_OS_EVAL_PROGRESS "
        + json.dumps(event, ensure_ascii=False, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def run_json(
    argv: list[str],
    timeout: int = 30,
    *,
    label: str = "command",
    heartbeat_seconds: float = EVAL_HEARTBEAT_SECONDS,
) -> dict[str, Any]:
    started = time.monotonic()
    popen_options: dict[str, Any] = {
        "cwd": PROJECT_ROOT,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "nt":
        popen_options["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(argv, **popen_options)
    if process.stdout is None or process.stderr is None:
        _terminate_process_tree(process)
        raise RuntimeError("eval command pipes unavailable")

    messages: queue.Queue[tuple[str, str | None]] = queue.Queue()
    readers = [
        threading.Thread(
            target=_read_stream,
            args=(process.stdout, "stdout", messages),
            daemon=True,
        ),
        threading.Thread(
            target=_read_stream,
            args=(process.stderr, "stderr", messages),
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()

    deadline = started + timeout
    next_heartbeat = started + heartbeat_seconds
    drain_deadline: float | None = None
    stream_done: set[str] = set()
    chunks: dict[str, list[str]] = {"stdout": [], "stderr": []}
    timed_out = False
    while True:
        now = time.monotonic()
        if not timed_out and now >= deadline:
            timed_out = True
            _terminate_process_tree(process)
            drain_deadline = time.monotonic() + 3
        if not timed_out and now >= next_heartbeat:
            _emit_heartbeat(label, now - started)
            next_heartbeat = now + heartbeat_seconds
        try:
            stream_name, chunk = messages.get(timeout=0.1)
        except queue.Empty:
            stream_name = ""
            chunk = ""
        if stream_name:
            if chunk is None:
                stream_done.add(stream_name)
            else:
                chunks[stream_name].append(chunk)
        if process.poll() is not None and stream_done == {"stdout", "stderr"}:
            break
        if timed_out and drain_deadline is not None and now >= drain_deadline:
            break

    for reader in readers:
        reader.join(timeout=1)
    stdout = output_text("".join(chunks["stdout"]))
    stderr = output_text("".join(chunks["stderr"]))
    try:
        parsed = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        parsed = {}
    return {
        "returncode": 124 if timed_out else process.returncode,
        "parsed": parsed,
        "stdout": diagnostic_text(stdout),
        "stderr": diagnostic_text(stderr),
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "attempts": 1,
        "automatic_retries": AUTOMATIC_RETRIES,
        "process_tree_terminated": timed_out,
    }


def failure_diagnostics(command_result: dict[str, Any]) -> dict[str, Any]:
    """Return bounded, privacy-filtered child diagnostics only for failed cases."""
    diagnostics: dict[str, Any] = {}
    parsed = command_result.get("parsed")
    if isinstance(parsed, dict) and parsed:
        summary = {
            key: parsed[key]
            for key in ("ok", "passed", "total")
            if isinstance(parsed.get(key), (bool, int))
        }
        reason_codes = parsed.get("reason_codes")
        if isinstance(reason_codes, list):
            bounded_reasons = [
                diagnostic_text(item) for item in reason_codes[:DIAGNOSTIC_FAILURE_LIMIT]
            ]
            if bounded_reasons:
                summary["reason_codes"] = bounded_reasons
        failures = parsed.get("results")
        if not isinstance(failures, list):
            failures = parsed.get("cases")
        if isinstance(failures, list):
            failed_results = []
            for item in failures:
                if not isinstance(item, dict) or item.get("passed") is True:
                    continue
                passed_value = item.get("passed")
                failure = {
                    "id": diagnostic_text(item.get("id", "unknown")),
                    "passed": passed_value if isinstance(passed_value, bool) else False,
                }
                if "error" in item:
                    failure["error"] = diagnostic_text(item["error"])
                item_reasons = item.get("reason_codes")
                if isinstance(item_reasons, list):
                    failure["reason_codes"] = [
                        diagnostic_text(value)
                        for value in item_reasons[:DIAGNOSTIC_FAILURE_LIMIT]
                    ]
                failed_results.append(failure)
                if len(failed_results) >= DIAGNOSTIC_FAILURE_LIMIT:
                    break
            if failed_results:
                summary["failed_results"] = failed_results
        if "error" in parsed:
            summary["error"] = diagnostic_text(parsed["error"])
        if summary:
            diagnostics["child_result"] = summary
    if "child_result" not in diagnostics:
        stdout = command_result.get("stdout")
        if isinstance(stdout, str) and stdout.strip():
            diagnostics["stdout_tail"] = diagnostic_text(stdout)
    stderr = command_result.get("stderr")
    if isinstance(stderr, str) and stderr.strip():
        diagnostics["stderr_tail"] = diagnostic_text(stderr)
    return diagnostics


def resolve(prompt: str) -> dict[str, Any]:
    return run_json(
        [sys.executable, ".agents/_tools/agent_os_resolver.py", "resolve", "--prompt", prompt],
        timeout=10,
    )["parsed"]


def agentignore_patterns() -> list[str]:
    return [
        line.strip()
        for line in AGENTIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def blocked(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        clean = pattern.strip("/")
        if pattern.endswith("/") and (normalized == clean or normalized.startswith(clean + "/")):
            return True
        if fnmatch.fnmatch(normalized, clean) or fnmatch.fnmatch(Path(normalized).name, clean):
            return True
    return False


def mcp_tools() -> list[str]:
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            "",
        ]
    )
    process = subprocess.run(
        [sys.executable, ".agents/_tools/agent_os_mcp_server.py"],
        cwd=PROJECT_ROOT,
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    for line in process.stdout.splitlines():
        item = json.loads(line)
        if item.get("id") == 2:
            return [tool.get("name") for tool in item.get("result", {}).get("tools", [])]
    return []


def select_cases(
    cases: list[dict[str, Any]],
    *,
    include_case_ids: list[str],
    exclude_case_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select a deterministic non-empty eval shard without weakening the spec."""
    if include_case_ids and exclude_case_ids:
        raise CaseSelectionError("EVAL_CASE_SELECTION_MODES_CONFLICT")
    case_ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise CaseSelectionError("EVAL_CASE_ID_INVALID")
    if len(set(case_ids)) != len(case_ids):
        raise CaseSelectionError("EVAL_CASE_ID_DUPLICATE")
    requested = include_case_ids or exclude_case_ids
    unknown = sorted(set(requested) - set(case_ids))
    if unknown:
        raise CaseSelectionError("EVAL_CASE_SELECTION_UNKNOWN", unknown)

    include = set(include_case_ids)
    exclude = set(exclude_case_ids)
    if include:
        selected = [case for case in cases if case["id"] in include]
        mode = "include"
    else:
        selected = [case for case in cases if case["id"] not in exclude]
        mode = "exclude" if exclude else "all"
    if not selected:
        raise CaseSelectionError("EVAL_CASE_SELECTION_EMPTY")
    return selected, {
        "mode": mode,
        "requested_case_ids": sorted(requested),
        "selected_count": len(selected),
        "spec_count": len(cases),
    }


def evaluate(case: dict[str, Any], patterns: list[str]) -> dict[str, Any]:
    case_type = case.get("type")
    result: dict[str, Any] = {"id": case.get("id"), "type": case_type}
    if case_type == "routing":
        actual = resolve(case["prompt"])
        workflow_matches = "expected_workflow" not in case or actual.get("workflow", {}).get("id") == case["expected_workflow"]
        capability_matches = "expected_capability" not in case or actual.get("capability", {}).get("id") == case["expected_capability"]
        result.update(
            {
                "passed": bool(actual.get("ok") and workflow_matches and capability_matches),
                "actual_workflow": actual.get("workflow", {}).get("id"),
                "actual_capability": actual.get("capability", {}).get("id"),
            }
        )
        return result
    if case_type == "firewall":
        actual = blocked(case["path"], patterns)
        result.update({"passed": actual == case["expected_blocked"], "actual_blocked": actual})
        return result
    if case_type == "lifecycle":
        timeout_seconds = case.get("timeout_seconds", 30)
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
            result.update(
                {
                    "passed": False,
                    "error": "timeout_seconds must be an integer from 1 to 300",
                }
            )
            return result
        command_result = run_json(
            [sys.executable, ".agents/_tools/agent_os_lifecycle.py", case["command"]],
            timeout=timeout_seconds,
            label=str(case.get("id", "lifecycle")),
        )
        actual = command_result["parsed"]
        expected_state = case.get("expected_state")
        if expected_state == "derived":
            adapter_state = actual.get("adapter", {}).get("state")
            if adapter_state == "UNBOUND":
                derived_state = "UNBOUND"
            elif (
                actual.get("core", {}).get("ok") is True
                and actual.get("adapter", {}).get("ok") is True
                and actual.get("client_bridge", {}).get("ok") is True
            ):
                derived_state = "BOUND"
            else:
                derived_state = "DEGRADED"
            expected_ok = derived_state == "BOUND"
        else:
            derived_state = expected_state
            expected_ok = case.get("expected_ok")
        core_matches = "expected_core_ok" not in case or actual.get("core", {}).get("ok") is case.get("expected_core_ok")
        result.update(
            {
                "passed": actual.get("state") == derived_state and actual.get("ok") is expected_ok and core_matches,
                "actual_state": actual.get("state"),
                "actual_ok": actual.get("ok"),
                "actual_core_ok": actual.get("core", {}).get("ok"),
                "returncode": command_result["returncode"],
                "timed_out": command_result["timed_out"],
                "timeout_seconds": timeout_seconds,
                "attempts": command_result["attempts"],
                "automatic_retries": command_result["automatic_retries"],
                "process_tree_terminated": command_result[
                    "process_tree_terminated"
                ],
            }
        )
        if result["passed"] is False:
            result["diagnostics"] = failure_diagnostics(command_result)
        return result
    if case_type == "command":
        argv = list(case["argv"])
        if argv and argv[0] in {"python", "python3", "py"}:
            argv[0] = sys.executable
        timeout_seconds = case.get("timeout_seconds", 30)
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 300:
            result.update({"passed": False, "error": "timeout_seconds must be an integer from 1 to 300"})
            return result
        command_result = run_json(
            argv,
            timeout=timeout_seconds,
            label=str(case.get("id", "command")),
        )
        actual_ok = command_result["parsed"].get("ok") is True
        result.update(
            {
                "passed": actual_ok is case.get("expected_ok", True),
                "actual_ok": actual_ok,
                "returncode": command_result["returncode"],
                "timed_out": command_result["timed_out"],
                "timeout_seconds": timeout_seconds,
                "attempts": command_result["attempts"],
                "automatic_retries": command_result["automatic_retries"],
                "process_tree_terminated": command_result[
                    "process_tree_terminated"
                ],
            }
        )
        if result["passed"] is False:
            result["diagnostics"] = failure_diagnostics(command_result)
        return result
    if case_type == "mcp":
        actual = set(mcp_tools())
        expected = set(case.get("expect_tools", []))
        result.update({"passed": expected <= actual, "missing_tools": sorted(expected - actual)})
        return result
    result.update({"passed": False, "error": "unknown case type"})
    return result


def main() -> int:
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    parser = argparse.ArgumentParser(description="Run Agent OS evals")
    parser.add_argument("--evals", default=str(DEFAULT_EVALS))
    parser.add_argument("--include-case-id", action="append", default=[])
    parser.add_argument("--exclude-case-id", action="append", default=[])
    add_summary_arguments(parser, default_step_name="bounded-behavioral-evals")
    args = parser.parse_args()
    spec = load_json(Path(args.evals), {})
    patterns = agentignore_patterns()
    cases = spec.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    try:
        selected_cases, selection = select_cases(
            cases,
            include_case_ids=args.include_case_id,
            exclude_case_ids=args.exclude_case_id,
        )
    except CaseSelectionError as error:
        output = {
            "ok": False,
            "version": spec.get("version"),
            "passed": 0,
            "total": 0,
            "results": [],
            "reason_codes": [error.reason_code],
            "case_ids": error.case_ids,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        completed_at = datetime.now(timezone.utc)
        return emit_summary(
            args,
            output,
            source_returncode=2,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            duration_seconds=time.monotonic() - started_monotonic,
        )
    results = [evaluate(case, patterns) for case in selected_cases]
    passed = sum(1 for result in results if result.get("passed"))
    output = {
        "ok": passed == len(results),
        "version": spec.get("version"),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    if selection["mode"] != "all":
        output["selection"] = selection
    print(json.dumps(output, ensure_ascii=False, indent=2))
    returncode = 0 if output["ok"] else 2
    completed_at = datetime.now(timezone.utc)
    return emit_summary(
        args,
        output,
        source_returncode=returncode,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_seconds=time.monotonic() - started_monotonic,
    )


if __name__ == "__main__":
    raise SystemExit(main())
