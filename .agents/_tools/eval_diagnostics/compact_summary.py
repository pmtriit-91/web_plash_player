"""Deterministic, redacted and byte-bounded CI result summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DIAGNOSTIC_TEXT_LIMIT = 2000
DIAGNOSTIC_FAILURE_LIMIT = 20
SUMMARY_JSON_MAX_BYTES = 8192
SUMMARY_MARKDOWN_MAX_BYTES = 4096
SUMMARY_TEXT_LIMIT = 256
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    r"([\"']?(?:(?:[A-Za-z][A-Za-z0-9]*[_-])*(?:"
    r"secret[_-]?access[_-]?key|access[_-]?key|api[_-]?key|"
    r"client[_-]?secret|refresh[_-]?token|authorization|password|secret|token"
    r"))[\"']?\s*[:=]\s*)"
    r"(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'"
    r"|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|[^\s,;}\]\)]+)"
)
BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def output_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return ""


def diagnostic_text(value: Any) -> str:
    if isinstance(value, (str, bytes)):
        text = output_text(value)
    elif isinstance(value, (bool, int, float)):
        text = str(value)
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = ""
    redacted = SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}[REDACTED]", text
    )
    return BEARER_TOKEN.sub("Bearer [REDACTED]", redacted)[-DIAGNOSTIC_TEXT_LIMIT:]


def _safe_text(value: Any) -> str:
    return diagnostic_text(value).replace("\r", " ").replace("\n", " ")[
        -SUMMARY_TEXT_LIMIT:
    ]


def _safe_int(value: Any, default: int = 0) -> int:
    return value if type(value) is int and value >= 0 else default


def _diagnostic_hash(value: Any) -> str | None:
    redacted = diagnostic_text(value)
    if not redacted:
        return None
    return hashlib.sha256(redacted.encode("utf-8")).hexdigest()


def _failure(value: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    item: dict[str, Any] = {"kind": kind}
    identity = value.get("id", value.get("shard_id", "unknown"))
    item["id"] = _safe_text(identity) or "unknown"
    for source, target in (
        ("active_scenario", "scenario"),
        ("returncode", "returncode"),
        ("return_code", "returncode"),
        ("timed_out", "timed_out"),
        ("timeout_seconds", "timeout_seconds"),
    ):
        raw = value.get(source)
        if isinstance(raw, (bool, int, str)) and target not in item:
            item[target] = _safe_text(raw) if isinstance(raw, str) else raw
    reasons = value.get("reason_codes")
    if isinstance(reasons, list):
        item["reason_codes"] = [_safe_text(reason) for reason in reasons[:10]]
    digest = _diagnostic_hash(
        value.get("diagnostics", value.get("protocol_errors", value.get("error")))
    )
    if digest:
        item["diagnostic_sha256"] = digest
    return item


def _failures(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    children = result.get("results", result.get("cases"))
    if isinstance(children, list):
        failures.extend(
            _failure(child, kind="eval")
            for child in children
            if isinstance(child, dict) and child.get("passed") is not True
        )
    shards = result.get("shards")
    if isinstance(shards, list):
        failures.extend(
            _failure(shard, kind="shard")
            for shard in shards
            if isinstance(shard, dict) and shard.get("ok") is not True
        )
    failed_ids = result.get("failed")
    known = {item["id"] for item in failures}
    if isinstance(failed_ids, list):
        for value in failed_ids:
            identifier = _safe_text(value) or "unknown"
            if identifier not in known:
                failures.append({"kind": "case", "id": identifier})
                known.add(identifier)
    harness_errors = result.get("harness_errors")
    if isinstance(harness_errors, list):
        for error in harness_errors:
            if isinstance(error, dict):
                normalized = dict(error)
                normalized["id"] = error.get("code", "harness-error")
                failures.append(_failure(normalized, kind="harness"))
    return failures


def metadata_from_environment(
    environment: Mapping[str, str] | None,
    *,
    profile: str,
    step_name: str,
) -> dict[str, Any]:
    source = os.environ if environment is None else environment
    return {
        "run": {
            "id": _safe_text(source.get("GITHUB_RUN_ID", "local")),
            "attempt": _safe_int_string(source.get("GITHUB_RUN_ATTEMPT", "1"), 1),
            "event": _safe_text(source.get("GITHUB_EVENT_NAME", "local")),
            "head_sha": _safe_text(source.get("GITHUB_SHA", "local")),
            "range_base": _safe_text(source.get("AGENT_OS_RANGE_BASE", "local")),
            "workflow_digest": _safe_text(
                source.get("AGENT_OS_WORKFLOW_SHA256", "local")
            ),
        },
        "os": _safe_text(source.get("RUNNER_OS", sys.platform)),
        "profile": profile,
        "step_name": _safe_text(step_name),
    }


def _safe_int_string(value: str, default: int) -> int:
    return int(value) if value.isdigit() else default


def build_summary(
    result: Mapping[str, Any],
    *,
    source_returncode: int,
    metadata: Mapping[str, Any],
    started_at: str,
    completed_at: str,
    duration_seconds: float,
) -> dict[str, Any]:
    failures = _failures(result)
    timed_out = source_returncode == 124 or any(
        failure.get("timed_out") is True for failure in failures
    )
    passed = _safe_int(result.get("passed", result.get("executable_cases")))
    total = _safe_int(
        result.get("total", result.get("expected_executable_cases")), passed
    )
    summary = {
        "schema_version": 1,
        "run": metadata["run"],
        "os": metadata["os"],
        "profile": metadata["profile"],
        "step": {
            "name": metadata["step_name"],
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": round(max(0.0, duration_seconds), 3),
        },
        "status": "completed",
        "conclusion": "timed_out" if timed_out else (
            "success" if source_returncode == 0 and result.get("ok") is True else "failure"
        ),
        "source_returncode": source_returncode,
        "passed": passed,
        "total": total,
        "failure_count": len(failures),
        "failures": failures[:DIAGNOSTIC_FAILURE_LIMIT],
        "failures_truncated": len(failures) > DIAGNOSTIC_FAILURE_LIMIT,
        "automatic_retries": _safe_int(result.get("automatic_retries")),
        "redacted": True,
    }
    while len(json_bytes(summary)) > SUMMARY_JSON_MAX_BYTES and summary["failures"]:
        summary["failures"].pop()
        summary["failures_truncated"] = True
    if len(json_bytes(summary)) > SUMMARY_JSON_MAX_BYTES:
        raise ValueError("COMPACT_SUMMARY_JSON_LIMIT_EXCEEDED")
    return summary


def json_bytes(summary: Mapping[str, Any]) -> bytes:
    return (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def markdown_bytes(summary: Mapping[str, Any]) -> bytes:
    step = summary["step"]
    lines = [
        f"### Agent OS CI — {summary['os']}",
        "",
        f"- Profile: `{summary['profile']}`",
        f"- Step: `{step['name']}`",
        f"- Conclusion: `{summary['conclusion']}`",
        f"- Result: `{summary['passed']}/{summary['total']}`",
        f"- Duration: `{step['duration_seconds']}s`",
    ]
    truncated = bool(summary["failures_truncated"])
    emitted = 0
    for failure in summary["failures"]:
        line = f"- Failure: `{failure['kind']}:{failure['id']}`" + (
            f" (`{failure['diagnostic_sha256']}`)"
            if failure.get("diagnostic_sha256")
            else ""
        )
        candidate = ("\n".join([*lines, line]) + "\n").encode("utf-8")
        if len(candidate) > SUMMARY_MARKDOWN_MAX_BYTES - 96:
            truncated = True
            break
        lines.append(line)
        emitted += 1
    truncated = truncated or emitted < len(summary["failures"])
    if truncated:
        lines.append("- Additional failures were truncated from this bounded summary.")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    return payload


def add_summary_arguments(
    parser: argparse.ArgumentParser, *, default_step_name: str
) -> None:
    parser.add_argument("--summary-json")
    parser.add_argument("--summary-markdown")
    parser.add_argument(
        "--summary-profile", choices=("release", "diagnostic"), default="release"
    )
    parser.add_argument("--summary-step-name", default=default_step_name)


def emit_summary(
    args: argparse.Namespace,
    result: Mapping[str, Any],
    *,
    source_returncode: int,
    started_at: str,
    completed_at: str,
    duration_seconds: float,
    environment: Mapping[str, str] | None = None,
) -> int:
    paths = (getattr(args, "summary_json", None), getattr(args, "summary_markdown", None))
    if paths == (None, None):
        return source_returncode
    try:
        if None in paths:
            raise ValueError("COMPACT_SUMMARY_OUTPUT_PAIR_REQUIRED")
        metadata = metadata_from_environment(
            environment,
            profile=args.summary_profile,
            step_name=args.summary_step_name,
        )
        summary = build_summary(
            result,
            source_returncode=source_returncode,
            metadata=metadata,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
        )
        for raw_path, payload in zip(paths, (json_bytes(summary), markdown_bytes(summary))):
            Path(raw_path).write_bytes(payload)
    except (OSError, TypeError, ValueError) as error:
        print(f"compact-summary-error: {type(error).__name__}", file=sys.stderr)
        return source_returncode if source_returncode != 0 else 2
    return source_returncode
