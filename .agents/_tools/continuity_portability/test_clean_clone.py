#!/usr/bin/env python3
"""Executable W6 shard for clean-clone release recovery."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import time
from pathlib import Path
from types import ModuleType
from typing import Any

CASE = {
    "id": "C26",
    "target": "AOS15-W6",
    "implementation_task": "P2c",
    "executable": True,
    "status": "executable",
}
TOOLS_DIR = Path(__file__).resolve().parents[1]
PROOFS = (
    (
        "reachable-git-clean-clone-recovery",
        "continuity_portability/test_clean_clone_recovery.py",
        10,
    ),
    (
        "task-ledger-v2-clean-clone-integrity",
        "context_memory/test_task_ledger_v2_clean_clone.py",
        8,
    ),
    (
        "lifecycle-health-and-genesis-disclosure",
        "lifecycle/test_health.py",
        8,
    ),
)


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)


def load_proof(path: Path, proof_id: str) -> ModuleType:
    module_id = proof_id.replace("-", "_")
    spec = importlib.util.spec_from_file_location(f"aos15_w6_{module_id}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load clean-clone proof: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_proof(proof_id: str, filename: str, expected: int) -> dict[str, Any]:
    started = time.monotonic()
    output = io.StringIO()
    exit_code = 0
    error_type: str | None = None
    try:
        module = load_proof(TOOLS_DIR / filename, proof_id)
        with contextlib.redirect_stdout(output):
            module.main()
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        exit_code = 1
        error_type = type(exc).__name__
    try:
        payload = json.loads(output.getvalue())
    except json.JSONDecodeError:
        payload = None
    passed = (
        error_type is None
        and exit_code == 0
        and isinstance(payload, dict)
        and payload.get("ok") is True
        and payload.get("passed") == expected
        and payload.get("total") == expected
    )
    return {
        "proof_id": proof_id,
        "passed": passed,
        "expected_handed_off_cases": expected,
        "passed_handed_off_cases": (
            payload.get("passed") if isinstance(payload, dict) else 0
        ),
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
        "error_type": error_type,
    }


def main() -> int:
    results: list[dict[str, Any]] = []
    for proof_id, filename, expected in PROOFS:
        emit(
            {
                "event": "scenario_start",
                "shard_id": "clean-clone",
                "scenario_id": proof_id,
                "case_ids": [proof_id],
            }
        )
        result = run_proof(proof_id, filename, expected)
        results.append(result)
        emit(
            {
                "event": "scenario_end",
                "shard_id": "clean-clone",
                "scenario_id": proof_id,
                "duration_seconds": result["duration_seconds"],
                "ok": result["passed"],
            }
        )
        if not result["passed"]:
            break
    ok = len(results) == len(PROOFS) and all(item["passed"] for item in results)
    emit(
        {
            "event": "shard_result",
            "shard_id": "clean-clone",
            "ok": ok,
            "registered_cases": 1,
            "executable_cases": 1,
            "passed_cases": 1 if ok else 0,
            "proofs_total": len(PROOFS),
            "proofs_passed": sum(1 for item in results if item["passed"]),
            "case": CASE,
            "proofs": results,
        }
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
