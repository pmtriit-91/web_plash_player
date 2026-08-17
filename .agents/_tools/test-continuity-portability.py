#!/usr/bin/env python3
"""Executable AOS-15 W5 retention, export, and restore fixtures."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from continuity_portability.test_supervisor import (
    supervise_command as _supervise_command,
)
from continuity_portability.test_support import initialize_w4
from eval_diagnostics.compact_summary import add_summary_arguments, emit_summary

HARNESS_VERSION = "aos15-w5-r2-v2"
DEFAULT_SHARD_TIMEOUT_SECONDS = 120
MAX_SHARD_TIMEOUT_SECONDS = 180
HEARTBEAT_SECONDS = 5
BASELINE_CASE_COUNT = 83
# SHA-256 of the sorted 83-case ID registry extracted from the pre-split
# 69f479f1... monolith. This prevents count-only parity from hiding case swaps.
BASELINE_CASE_SET_SHA256 = (
    "a1348e12a9e7777c20bcc857a6f4ec7eea69d9675e822976a9391d0948e837be"
)
SCRIPT_PATH = Path(__file__).resolve()
TOOLS_DIR = SCRIPT_PATH.parent
SHARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "retention-policy-bounds",
        "file": "continuity_portability/test_retention_policy_bounds.py",
        "groups": ("retention-archive",),
        "case_count": 9,
        "timeout_seconds": 120,
    },
    {
        "id": "retention-archive",
        "file": "continuity_portability/test_retention_archive.py",
        "groups": ("retention-archive",),
        "case_count": 8,
        "timeout_seconds": 120,
    },
    {
        "id": "path-security",
        "file": "continuity_portability/test_path_security.py",
        "groups": ("path-security",),
        "case_count": 9,
        "timeout_seconds": 120,
    },
    {
        "id": "cli-integration",
        "file": "continuity_portability/test_cli_integration.py",
        "groups": ("cli-integration",),
        "case_count": 2,
        "timeout_seconds": 120,
    },
    {
        "id": "export-bundle-contract",
        "file": "continuity_portability/test_export_bundle_contract.py",
        "groups": ("export",),
        "case_count": 8,
        "timeout_seconds": 120,
    },
    {
        "id": "export-bundle-adversarial-guards",
        "file": "continuity_portability/test_export_bundle_adversarial_guards.py",
        "groups": ("export",),
        "case_count": 8,
        "timeout_seconds": 120,
    },
    {
        "id": "export-source-and-plan-guards",
        "file": "continuity_portability/test_export_source_and_plan_guards.py",
        "groups": ("export",),
        "case_count": 8,
        "timeout_seconds": 120,
    },
    {
        "id": "export-cleanup-and-privacy",
        "file": "continuity_portability/test_export_cleanup_and_privacy.py",
        "groups": ("export",),
        "case_count": 8,
        "timeout_seconds": 120,
    },
    {
        "id": "restore-admission-and-backup-guards",
        "file": "continuity_portability/test_restore_admission_and_backup_guards.py",
        "groups": ("restore",),
        "case_count": 8,
        "timeout_seconds": 180,
    },
    {
        "id": "restore-receipt-and-drift",
        "file": "continuity_portability/test_restore_receipt_and_drift.py",
        "groups": ("restore",),
        "case_count": 8,
        "timeout_seconds": 120,
    },
    {
        "id": "restore-rollback-and-diff-bounds",
        "file": "continuity_portability/test_restore_rollback_and_diff_bounds.py",
        "groups": ("restore",),
        "case_count": 7,
        "timeout_seconds": 120,
    },
)
SHARD_BY_ID = {item["id"]: item for item in SHARDS}
GROUP_IDS = tuple(sorted({group for item in SHARDS for group in item["groups"]}))
AGGREGATE_CASE_COUNT = sum(item["case_count"] for item in SHARDS)
if AGGREGATE_CASE_COUNT != BASELINE_CASE_COUNT:
    raise RuntimeError("shard registry count does not match the pre-split W5 baseline")

DEFERRED_CASES = [
    {
        "id": "windows-portable-path-collisions",
        "target": "AOS15-W6",
        "reason": "reserved-name, invalid-character, trailing-dot-space, case-fold, and Unicode-normalization collision contract",
    },
    {
        "id": "dependency-ordered-restore",
        "target": "AOS15-W6",
        "reason": "restore ordering derived from declared dependency topology",
    },
    {
        "id": "stale-lock-recovery",
        "target": "AOS15-W6",
        "reason": "safe owner/liveness recovery after an interrupted portability transaction",
    },
    {
        "id": "C26",
        "target": "AOS15-W6",
        "reason": "clean-clone release recovery",
    },
    {
        "id": "multi-generation-portability",
        "target": "AOS15-W6",
        "reason": "release proof across continuity generations",
    },
    {
        "id": "partial-loss-recovery",
        "target": "AOS15-W6",
        "reason": "release recovery drill",
    },
]


def _load_module(
    name: str,
    path: Path,
) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _emit_worker(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)


def _worker_result(
    *,
    shard_id: str,
    started: float,
    cases: list[tuple[str, bool]],
    expected_case_ids: list[str],
    harness_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    failed = [identifier for identifier, passed in cases if not passed]
    return {
        "event": "shard_result",
        "harness_version": HARNESS_VERSION,
        "shard_id": shard_id,
        "ok": not failed and not harness_errors,
        "duration_seconds": round(time.monotonic() - started, 3),
        "case_count": len(cases),
        "expected_case_count": len(expected_case_ids),
        "expected_case_ids": expected_case_ids,
        "cases": [{"id": identifier, "passed": passed} for identifier, passed in cases],
        "failed": failed,
        "harness_errors": harness_errors,
    }


def run_worker(shard_id: str) -> int:
    started = time.monotonic()
    spec = SHARD_BY_ID[shard_id]
    _emit_worker(
        {
            "event": "worker_boot",
            "shard_id": shard_id,
            "operation": "load-shared-fixtures",
        }
    )
    initialize_w4()
    shard_path = TOOLS_DIR / spec["file"]
    shard = _load_module(
        f"aos15_w5_shard_{shard_id.replace('-', '_')}",
        shard_path,
    )
    if shard.SHARD_ID != shard_id:
        raise RuntimeError(
            f"shard identity mismatch: expected {shard_id}, got {shard.SHARD_ID}"
        )
    if tuple(shard.GROUPS) != tuple(spec["groups"]):
        raise RuntimeError(f"shard group mismatch: {shard_id}")
    if int(shard.TIMEOUT_SECONDS) != int(spec["timeout_seconds"]):
        raise RuntimeError(f"shard timeout does not match registry: {shard_id}")
    if int(shard.TIMEOUT_SECONDS) > MAX_SHARD_TIMEOUT_SECONDS:
        raise RuntimeError(f"shard timeout exceeds policy: {shard_id}")

    cases: list[tuple[str, bool]] = []
    expected_case_ids: list[str] = []
    harness_errors: list[dict[str, Any]] = []
    _emit_worker(
        {
            "event": "shard_start",
            "shard_id": shard_id,
            "groups": list(spec["groups"]),
            "expected_case_count": spec["case_count"],
        }
    )
    for scenario_id, scenario_case_ids, scenario in shard.SCENARIOS:
        expected = list(scenario_case_ids)
        expected_case_ids.extend(expected)
        before = len(cases)
        scenario_started = time.monotonic()
        _emit_worker(
            {
                "event": "scenario_start",
                "shard_id": shard_id,
                "scenario_id": scenario_id,
                "case_ids": expected,
            }
        )
        try:
            scenario(cases)
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            error = {
                "code": "SHARD_SCENARIO_EXCEPTION",
                "scenario_id": scenario_id,
                "pending_case_ids": expected,
                "exception_type": type(exc).__name__,
                "message": str(exc)[:2000],
                "traceback": traceback.format_exc(limit=16),
            }
            harness_errors.append(error)
            _emit_worker(
                {
                    "event": "scenario_error",
                    "shard_id": shard_id,
                    **error,
                }
            )
            result = _worker_result(
                shard_id=shard_id,
                started=started,
                cases=cases,
                expected_case_ids=expected_case_ids,
                harness_errors=harness_errors,
            )
            _emit_worker(result)
            return 2

        appended = cases[before:]
        actual_ids = [item[0] for item in appended]
        malformed = [
            item
            for item in appended
            if not (
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], bool)
            )
        ]
        if malformed or actual_ids != expected:
            error = {
                "code": "SHARD_CASE_REGISTRY_MISMATCH",
                "scenario_id": scenario_id,
                "expected_case_ids": expected,
                "actual_case_ids": actual_ids,
                "malformed_case_count": len(malformed),
            }
            harness_errors.append(error)
            _emit_worker(
                {
                    "event": "scenario_error",
                    "shard_id": shard_id,
                    **error,
                }
            )
            result = _worker_result(
                shard_id=shard_id,
                started=started,
                cases=cases,
                expected_case_ids=expected_case_ids,
                harness_errors=harness_errors,
            )
            _emit_worker(result)
            return 2

        for identifier, passed in appended:
            _emit_worker(
                {
                    "event": "case_result",
                    "shard_id": shard_id,
                    "scenario_id": scenario_id,
                    "case_id": identifier,
                    "passed": passed,
                }
            )
        _emit_worker(
            {
                "event": "scenario_end",
                "shard_id": shard_id,
                "scenario_id": scenario_id,
                "duration_seconds": round(time.monotonic() - scenario_started, 3),
                "ok": all(passed for _identifier, passed in appended),
            }
        )

    if len(cases) != spec["case_count"]:
        harness_errors.append(
            {
                "code": "SHARD_CASE_COUNT_MISMATCH",
                "expected": spec["case_count"],
                "actual": len(cases),
            }
        )
    if len(expected_case_ids) != len(set(expected_case_ids)):
        harness_errors.append({"code": "SHARD_CASE_ID_DUPLICATE"})
    result = _worker_result(
        shard_id=shard_id,
        started=started,
        cases=cases,
        expected_case_ids=expected_case_ids,
        harness_errors=harness_errors,
    )
    _emit_worker(result)
    return 0 if result["ok"] else 2


def supervise_command(
    label: str,
    command: list[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    return _supervise_command(
        label,
        command,
        timeout_seconds,
        cwd=TOOLS_DIR,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        progress_prefix="[aos15-w5] ",
    )


def run_timeout_self_test() -> int:
    probe_commands = (
        ("leader-alive", "--worker-timeout-probe"),
        ("leader-exited-descendant-holds-pipes", "--worker-orphan-pipe-probe"),
    )
    probes = []
    for probe_id, argument in probe_commands:
        supervised = supervise_command(
            f"timeout-probe-{probe_id}",
            [sys.executable, str(SCRIPT_PATH), argument],
            1,
        )
        probes.append(
            {
                "id": probe_id,
                "passed": (
                    supervised["timed_out"] is True
                    and supervised["attempts"] == 1
                    and supervised["automatic_retries"] == 0
                    and supervised["duration_seconds"] < 5
                    and supervised["streams_closed"] is True
                ),
                "duration_seconds": supervised["duration_seconds"],
                "timed_out": supervised["timed_out"],
                "attempts": supervised["attempts"],
                "automatic_retries": supervised["automatic_retries"],
                "active_scenario": supervised["active_scenario"],
                "pending_case_ids": supervised["pending_case_ids"],
                "streams_closed": supervised["streams_closed"],
            }
        )
    passed = all(probe["passed"] for probe in probes)
    result = {
        "ok": passed,
        "harness_version": HARNESS_VERSION,
        "test": "hard-timeout-kills-worker-process-tree-even-after-leader-exit",
        "timeout_seconds": 1,
        "max_duration_seconds": max(probe["duration_seconds"] for probe in probes),
        "automatic_retries": 0,
        "probes": probes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 2


def run_timeout_probe() -> int:
    _emit_worker(
        {
            "event": "scenario_start",
            "shard_id": "timeout-probe",
            "scenario_id": "intentional-sleep",
            "case_ids": ["timeout-probe-must-be-terminated"],
        }
    )
    time.sleep(30)
    return 99


def run_orphan_pipe_probe() -> int:
    _emit_worker(
        {
            "event": "scenario_start",
            "shard_id": "timeout-probe-leader-exited-descendant-holds-pipes",
            "scenario_id": "spawn-descendant-and-exit",
            "case_ids": ["orphaned-pipe-holder-must-be-terminated"],
        }
    )
    subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=str(TOOLS_DIR),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return 0


def selected_shards(shard_ids: list[str], group_ids: list[str]) -> list[dict[str, Any]]:
    if not shard_ids and not group_ids:
        return list(SHARDS)
    requested = set(shard_ids)
    requested_groups = set(group_ids)
    return [
        item
        for item in SHARDS
        if item["id"] in requested or requested_groups.intersection(item["groups"])
    ]


def shard_timeout_seconds(
    spec: dict[str, Any], timeout_override: int | None
) -> int:
    return (
        timeout_override
        if timeout_override is not None
        else int(spec["timeout_seconds"])
    )


def run_supervisor(
    selection: list[dict[str, Any]], timeout_override: int | None
) -> tuple[dict[str, Any], int]:
    supervised_results: list[dict[str, Any]] = []
    all_cases: list[dict[str, Any]] = []
    all_expected_ids: list[str] = []
    harness_errors: list[dict[str, Any]] = []
    timed_out = False
    effective_timeouts: dict[str, int] = {}

    for spec in selection:
        effective_timeout = shard_timeout_seconds(spec, timeout_override)
        effective_timeouts[spec["id"]] = effective_timeout
        supervised = supervise_command(
            spec["id"],
            [sys.executable, str(SCRIPT_PATH), "--worker", spec["id"]],
            effective_timeout,
        )
        supervised_results.append(supervised)
        timed_out = timed_out or supervised["timed_out"]
        harness_errors.extend(
            {"shard_id": spec["id"], **error} for error in supervised["protocol_errors"]
        )
        worker = supervised["worker_result"]
        if worker is not None:
            all_cases.extend(worker.get("cases", []))
            all_expected_ids.extend(worker.get("expected_case_ids", []))
            harness_errors.extend(
                {"shard_id": spec["id"], **error}
                for error in worker.get("harness_errors", [])
            )
        # Rescue Plan invariant: a timeout or failure ends the workstep; never retry.
        if (
            supervised["timed_out"]
            or worker is None
            or not worker.get("ok", False)
            or supervised["protocol_errors"]
        ):
            break

    selected_all = [item["id"] for item in selection] == [item["id"] for item in SHARDS]
    expected_selected_count = sum(item["case_count"] for item in selection)
    case_ids = [item["id"] for item in all_cases]
    failed = [item["id"] for item in all_cases if not item["passed"]]
    selection_complete = len(supervised_results) == len(selection)
    registry_matches = (
        len(all_cases) == expected_selected_count
        and case_ids == all_expected_ids
        and len(case_ids) == len(set(case_ids))
    )
    case_set_sha256 = (
        hashlib.sha256(
            json.dumps(
                sorted(case_ids),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if len(case_ids) == len(set(case_ids))
        else None
    )
    aggregate_parity = (
        registry_matches
        and len(all_cases) == BASELINE_CASE_COUNT
        and case_set_sha256 == BASELINE_CASE_SET_SHA256
        if selected_all and selection_complete
        else None
    )
    if selection_complete and not registry_matches:
        harness_errors.append(
            {
                "code": "AGGREGATE_CASE_REGISTRY_MISMATCH",
                "expected_case_count": expected_selected_count,
                "actual_case_count": len(all_cases),
            }
        )
    if selected_all and selection_complete and aggregate_parity is not True:
        harness_errors.append(
            {
                "code": "AGGREGATE_PARITY_FAILED",
                "expected_case_count": AGGREGATE_CASE_COUNT,
                "actual_case_count": len(all_cases),
            }
        )

    compact_shards = []
    for supervised in supervised_results:
        worker = supervised["worker_result"] or {}
        compact_shards.append(
            {
                "id": supervised["shard_id"],
                "ok": bool(worker.get("ok")) and not supervised["protocol_errors"],
                "timed_out": supervised["timed_out"],
                "timeout_seconds": supervised["timeout_seconds"],
                "duration_seconds": supervised["duration_seconds"],
                "attempts": supervised["attempts"],
                "automatic_retries": supervised["automatic_retries"],
                "case_count": worker.get("case_count", 0),
                "expected_case_count": worker.get("expected_case_count"),
                "failed": worker.get("failed", []),
                "active_scenario": supervised["active_scenario"],
                "pending_case_ids": supervised["pending_case_ids"],
            }
        )
    ok = (
        selection_complete
        and not timed_out
        and not failed
        and not harness_errors
        and registry_matches
        and all(item["ok"] for item in compact_shards)
    )
    result = {
        "ok": ok,
        "harness_version": HARNESS_VERSION,
        "selected_shards": [item["id"] for item in selection],
        "selection_complete": selection_complete,
        "fail_fast": True,
        "hard_timeout_seconds_per_shard": max(effective_timeouts.values()),
        "shard_timeout_seconds": effective_timeouts,
        "timeout_override_seconds": timeout_override,
        "automatic_retries": 0,
        "executable_cases": len(all_cases),
        "expected_executable_cases": expected_selected_count,
        "aggregate_expected_executable_cases": BASELINE_CASE_COUNT,
        "aggregate_parity": aggregate_parity,
        "baseline_case_set_sha256": BASELINE_CASE_SET_SHA256,
        "case_set_sha256": case_set_sha256,
        "case_registry_sha256": (
            hashlib.sha256(
                json.dumps(case_ids, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if registry_matches
            else None
        ),
        "non_executable_cases": len(DEFERRED_CASES),
        "deferred_cases": DEFERRED_CASES,
        "shards": compact_shards,
        "cases": all_cases,
        "failed": failed,
        "harness_errors": harness_errors,
    }
    if timed_out:
        return result, 124
    return result, 0 if ok else 2


def timeout_value(raw: str) -> int:
    value = int(raw)
    if not 1 <= value <= MAX_SHARD_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"timeout must be between 1 and {MAX_SHARD_TIMEOUT_SECONDS} seconds"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run independently supervised AOS-15 W5 portability test shards."
    )
    parser.add_argument(
        "--shard",
        action="append",
        default=[],
        choices=tuple(SHARD_BY_ID),
        help="run one shard; repeat to select multiple shards",
    )
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        choices=GROUP_IDS,
        help="run every shard assigned to a logical test group",
    )
    parser.add_argument(
        "--timeout",
        type=timeout_value,
        default=None,
        help=(
            "override every shard hard timeout "
            f"(maximum: {MAX_SHARD_TIMEOUT_SECONDS} seconds)"
        ),
    )
    parser.add_argument("--list-shards", action="store_true")
    parser.add_argument("--self-test-timeout", action="store_true")
    parser.add_argument("--worker", choices=tuple(SHARD_BY_ID), help=argparse.SUPPRESS)
    parser.add_argument(
        "--worker-timeout-probe", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--worker-orphan-pipe-probe",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    add_summary_arguments(parser, default_step_name="offline-portability-shards")
    return parser


def main() -> int:
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    args = build_parser().parse_args()
    if args.worker_orphan_pipe_probe:
        return run_orphan_pipe_probe()
    if args.worker_timeout_probe:
        return run_timeout_probe()
    if args.worker:
        return run_worker(args.worker)
    if args.list_shards:
        print(
            json.dumps(
                {
                    "harness_version": HARNESS_VERSION,
                    "aggregate_case_count": BASELINE_CASE_COUNT,
                    "baseline_case_set_sha256": BASELINE_CASE_SET_SHA256,
                    "max_timeout_seconds": MAX_SHARD_TIMEOUT_SECONDS,
                    "heartbeat_seconds": HEARTBEAT_SECONDS,
                    "automatic_retries": 0,
                    "groups": list(GROUP_IDS),
                    "shards": [
                        {
                            **item,
                            "groups": list(item["groups"]),
                        }
                        for item in SHARDS
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.self_test_timeout:
        return run_timeout_self_test()
    selection = selected_shards(args.shard, args.group)
    if not selection:
        raise SystemExit("no shard selected")
    result, returncode = run_supervisor(selection, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    completed_at = datetime.now(timezone.utc)
    return emit_summary(
        args,
        result,
        source_returncode=returncode,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_seconds=time.monotonic() - started_monotonic,
    )


if __name__ == "__main__":
    raise SystemExit(main())
