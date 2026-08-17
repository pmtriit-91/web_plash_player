#!/usr/bin/env python3
"""Bounded mixed-state registry for the six AOS-15 W6 gates."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from continuity_portability.test_supervisor import supervise_command

HARNESS_VERSION = "aos15-w6-p2c-v1"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
HEARTBEAT_SECONDS = 5
AUTOMATIC_RETRIES = 0
DEFERRED_REASON_CODE = "W6_CASE_DEFERRED"
EXECUTABLE_SHARD_IDS = {
    "windows-path",
    "dependency-order",
    "stale-lock",
    "multi-generation",
    "partial-loss",
    "clean-clone",
}
BASELINE_CASE_SET_SHA256 = (
    "711c31ab76f6466e26aeaa2c3955a7c796c951a74a1ab852f1d1f9f05ea67a7a"
)
TOOLS_DIR = Path(__file__).resolve().parent
SHARDS: tuple[dict[str, Any], ...] = (
    {
        "id": "windows-path",
        "file": "continuity_portability/test_windows_path.py",
        "case_id": "windows-portable-path-collisions",
        "implementation_task": "P1a",
    },
    {
        "id": "dependency-order",
        "file": "continuity_portability/test_dependency_order.py",
        "case_id": "dependency-ordered-restore",
        "implementation_task": "P1b",
    },
    {
        "id": "stale-lock",
        "file": "continuity_portability/test_stale_lock.py",
        "case_id": "stale-lock-recovery",
        "implementation_task": "P1c",
    },
    {
        "id": "multi-generation",
        "file": "continuity_portability/test_multi_generation.py",
        "case_id": "multi-generation-portability",
        "implementation_task": "P2a",
    },
    {
        "id": "partial-loss",
        "file": "continuity_portability/test_partial_loss.py",
        "case_id": "partial-loss-recovery",
        "implementation_task": "P2b",
    },
    {
        "id": "clean-clone",
        "file": "continuity_portability/test_clean_clone.py",
        "case_id": "C26",
        "implementation_task": "P2c",
    },
)
SHARD_BY_ID = {item["id"]: item for item in SHARDS}


def case_set_sha256(case_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(case_ids)).encode("utf-8")).hexdigest()


def load_shard(path: Path, shard_id: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"aos15_w6_{shard_id}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load W6 shard: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for shard in SHARDS:
        module = load_shard(TOOLS_DIR / shard["file"], shard["id"])
        executable = shard["id"] in EXECUTABLE_SHARD_IDS
        attribute = "CASE" if executable else "DEFERRED_CASE"
        case = getattr(module, attribute, None)
        if not isinstance(case, dict):
            raise TypeError(f"case metadata missing: {shard['id']}")
        expected = {
            "id": shard["case_id"],
            "target": "AOS15-W6",
            "implementation_task": shard["implementation_task"],
            "executable": executable,
            "status": "executable" if executable else "deferred",
        }
        if case != expected:
            raise RuntimeError(f"case metadata drift: {shard['id']}")
        entries.append({**shard, "case": case})
    case_ids = [entry["case"]["id"] for entry in entries]
    if len(entries) != 6 or len(set(case_ids)) != 6:
        raise RuntimeError("W6 registry must contain exactly six cases")
    if case_set_sha256(case_ids) != BASELINE_CASE_SET_SHA256:
        raise RuntimeError("W6 case set drifted from the W5 registry")
    return entries


def list_registry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    executable = sum(1 for entry in entries if entry["case"]["executable"])
    return {
        "ok": True,
        "harness_version": HARNESS_VERSION,
        "status": (
            "executable" if executable == len(entries) else "partially_executable"
        ),
        "registered_cases": len(entries),
        "executable_cases": executable,
        "passed_cases": 0,
        "deferred_cases": len(entries) - executable,
        "case_set_sha256": BASELINE_CASE_SET_SHA256,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "max_timeout_seconds": MAX_TIMEOUT_SECONDS,
        "automatic_retries": AUTOMATIC_RETRIES,
        "shards": entries,
    }


def run_selected(
    entries: list[dict[str, Any]], selected_ids: list[str], timeout_seconds: int
) -> int:
    results: list[dict[str, Any]] = []
    registry_by_id = {entry["id"]: entry for entry in entries}
    for shard_id in selected_ids:
        entry = registry_by_id[shard_id]
        result = supervise_command(
            shard_id,
            [sys.executable, str(TOOLS_DIR / entry["file"])],
            timeout_seconds,
            cwd=TOOLS_DIR,
            heartbeat_seconds=HEARTBEAT_SECONDS,
            progress_prefix="[aos15-w6] ",
        )
        worker = result.get("worker_result")
        executable = entry["case"]["executable"] is True
        expected_proofs = 4 if shard_id in {"stale-lock", "multi-generation"} else 3
        passed = (
            executable
            and isinstance(worker, dict)
            and worker.get("ok") is True
            and worker.get("shard_id") == shard_id
            and worker.get("executable_cases") == 1
            and worker.get("passed_cases") == 1
            and worker.get("proofs_total") == expected_proofs
            and worker.get("proofs_passed") == expected_proofs
            and worker.get("case") == registry_by_id[shard_id]["case"]
        )
        deferred = (
            not executable
            and isinstance(worker, dict)
            and worker.get("ok") is False
            and worker.get("shard_id") == shard_id
            and worker.get("reason_code") == DEFERRED_REASON_CODE
            and worker.get("executable_cases") == 0
            and worker.get("passed_cases") == 0
            and worker.get("case") == registry_by_id[shard_id]["case"]
        )
        results.append(
            {
                "shard_id": shard_id,
                "passed": passed,
                "deferred": deferred,
                "timed_out": result["timed_out"],
                "attempts": result["attempts"],
                "automatic_retries": result["automatic_retries"],
                "streams_closed": result["streams_closed"],
                "protocol_errors": result["protocol_errors"],
                "worker_result": worker,
            }
        )
    protocol_valid = all(
        (item["passed"] or item["deferred"])
        and not item["timed_out"]
        and item["attempts"] == 1
        and item["automatic_retries"] == 0
        and item["streams_closed"]
        and not item["protocol_errors"]
        for item in results
    )
    executable_cases = sum(
        1 for shard_id in selected_ids if registry_by_id[shard_id]["case"]["executable"]
    )
    passed_cases = sum(1 for item in results if item["passed"])
    deferred_cases = sum(1 for item in results if item["deferred"])
    ok = protocol_valid and deferred_cases == 0 and passed_cases == executable_cases
    payload = {
        "ok": ok,
        "harness_version": HARNESS_VERSION,
        "status": "passed" if ok else "blocked_non_executable",
        "reason_code": (
            None
            if ok
            else DEFERRED_REASON_CODE
            if protocol_valid and deferred_cases > 0
            else "W6_SHARD_PROTOCOL_INVALID"
        ),
        "selected_shards": selected_ids,
        "registered_cases": len(entries),
        "selected_registered_cases": len(selected_ids),
        "executable_cases": executable_cases,
        "passed_cases": passed_cases,
        "deferred_cases": deferred_cases,
        "hard_timeout_seconds_per_shard": timeout_seconds,
        "automatic_retries": AUTOMATIC_RETRIES,
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shard", action="append", choices=tuple(SHARD_BY_ID), default=[]
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--list-shards", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.timeout <= MAX_TIMEOUT_SECONDS:
        parser.error(f"--timeout must be between 1 and {MAX_TIMEOUT_SECONDS}")
    entries = registry()
    if args.list_shards:
        print(json.dumps(list_registry(entries), ensure_ascii=False, indent=2))
        return 0
    selected = list(dict.fromkeys(args.shard)) or list(SHARD_BY_ID)
    return run_selected(entries, selected, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
