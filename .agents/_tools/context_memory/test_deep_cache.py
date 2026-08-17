#!/usr/bin/env python3
"""BR3d1 focused shard for fail-closed deep-doctor cache runtime."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as engine
from context_memory import deep_receipt, handoff_validation

NOW = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
SUMMARY = {field: 0 for field in deep_receipt.SUMMARY_FIELDS}
FULL = {
    "errors": [],
    "warnings": [],
    "summary": SUMMARY,
    "valid_receipts": [{"id": "full"}],
}


class Service:
    def __init__(self, root: Path):
        self.root = root
        self.now = lambda: NOW
        self.current_head = "a" * 40
        for relative in deep_receipt.TREE_RELS.values():
            self.path(relative).mkdir(parents=True)
        self.path("project/context/handoffs/one.json").write_text(
            "{}\n", encoding="utf-8"
        )
        self.path("project/context/task-ledger/index.json").write_text(
            "{}\n", encoding="utf-8"
        )

    def path(self, relative: str) -> Path:
        return self.root / relative

    def binding(self) -> dict[str, str]:
        return {"project_id": "universal-agent-os"}

    def head(self) -> str:
        return self.current_head


def fixture(check: Any) -> bool:
    with tempfile.TemporaryDirectory() as holder:
        return bool(check(Service(Path(holder))))


def case_tree_digest_and_unsafe(service: Service) -> bool:
    first = deep_receipt.current_bindings(service)
    second = deep_receipt.current_bindings(service)
    service.path("project/context/handoffs/one.json").write_text(
        '{"changed":true}\n', encoding="utf-8"
    )
    changed = deep_receipt.current_bindings(service)
    service.path("project/context/task-ledger/not-json").write_text(
        "unsafe", encoding="utf-8"
    )
    return (
        first == second
        and first != changed
        and deep_receipt.current_bindings(service) is None
    )


def case_cache_round_trip(service: Service) -> bool:
    bindings = deep_receipt.current_bindings(service)
    assert bindings is not None
    verdict = {field: FULL[field] for field in ("errors", "warnings", "summary")}
    return (
        deep_receipt.write_cached(service, bindings, verdict, NOW)
        and deep_receipt.load_cached(service, bindings, NOW) == verdict
    )


def case_cache_misses_fail_closed(service: Service) -> bool:
    bindings = deep_receipt.current_bindings(service)
    verdict = {field: FULL[field] for field in ("errors", "warnings", "summary")}
    assert bindings is not None and deep_receipt.write_cached(
        service, bindings, verdict, NOW
    )
    expired = (
        deep_receipt.load_cached(service, bindings, NOW + timedelta(seconds=300))
        is None
    )
    service.current_head = "b" * 40
    foreign = (
        deep_receipt.load_cached(
            service, deep_receipt.current_bindings(service) or {}, NOW
        )
        is None
    )
    service.path(deep_receipt.CACHE_REL).write_text("{broken", encoding="utf-8")
    corrupt = (
        deep_receipt.load_cached(
            service, deep_receipt.current_bindings(service) or {}, NOW
        )
        is None
    )
    return expired and foreign and corrupt


def case_doctor_miss_then_hit(service: Service) -> bool:
    original = handoff_validation._validate_handoffs
    calls = 0

    def traversal(_service: Service) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return FULL

    handoff_validation._validate_handoffs = traversal
    try:
        first = handoff_validation.validate_for_doctor(service)
        second = handoff_validation.validate_for_doctor(service)
        return first == second and calls == 1 and "valid_receipts" not in first
    finally:
        handoff_validation._validate_handoffs = original


def case_tree_mutation_forces_fallback(service: Service) -> bool:
    if not case_doctor_miss_then_hit(service):
        return False
    service.path("project/context/task-ledger/index.json").write_text(
        '{"next":1}\n', encoding="utf-8"
    )
    original = handoff_validation._validate_handoffs
    calls = 0

    def traversal(_service: Service) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return FULL

    handoff_validation._validate_handoffs = traversal
    try:
        return (
            handoff_validation.validate_for_doctor(service)["summary"] == SUMMARY
            and calls == 1
        )
    finally:
        handoff_validation._validate_handoffs = original


def case_public_validation_stays_full(service: Service) -> bool:
    original = handoff_validation._validate_handoffs
    handoff_validation._validate_handoffs = lambda _service: FULL
    try:
        return handoff_validation.validate_handoffs(service) == FULL
    finally:
        handoff_validation._validate_handoffs = original


def case_binding_race_forces_fallback(service: Service) -> bool:
    bindings = deep_receipt.current_bindings(service)
    assert bindings is not None
    verdict = {field: FULL[field] for field in ("errors", "warnings", "summary")}
    assert deep_receipt.write_cached(service, bindings, verdict, NOW)
    original_bindings = deep_receipt.current_bindings
    original_validate = handoff_validation._validate_handoffs
    sequence = iter(
        (bindings, {**bindings, "head": "b" * 40}, {**bindings, "head": "b" * 40})
    )
    calls = 0

    def traversal(_service: Service) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return FULL

    deep_receipt.current_bindings = lambda _service: next(sequence)
    handoff_validation._validate_handoffs = traversal
    try:
        return (
            handoff_validation.validate_for_doctor(service)["summary"] == SUMMARY
            and calls == 1
        )
    finally:
        deep_receipt.current_bindings = original_bindings
        handoff_validation._validate_handoffs = original_validate


def case_write_failure_does_not_change_verdict(service: Service) -> bool:
    original_atomic = engine.atomic_bytes
    original_validate = handoff_validation._validate_handoffs
    engine.atomic_bytes = lambda *_args: (_ for _ in ()).throw(OSError("bounded"))
    handoff_validation._validate_handoffs = lambda _service: FULL
    try:
        return handoff_validation.validate_for_doctor(service)["errors"] == []
    finally:
        engine.atomic_bytes = original_atomic
        handoff_validation._validate_handoffs = original_validate


CASES = [
    ("tree-digest-unsafe", case_tree_digest_and_unsafe),
    ("cache-round-trip", case_cache_round_trip),
    ("cache-misses", case_cache_misses_fail_closed),
    ("doctor-miss-hit", case_doctor_miss_then_hit),
    ("tree-mutation", case_tree_mutation_forces_fallback),
    ("public-full", case_public_validation_stays_full),
    ("binding-race", case_binding_race_forces_fallback),
    ("write-failure", case_write_failure_does_not_change_verdict),
]


def main() -> None:
    results = []
    for name, check in CASES:
        try:
            passed, error = fixture(check), None
        except Exception as exc:  # noqa: BLE001 - bounded case diagnostics
            passed, error = False, str(exc)
        results.append(
            {"id": name, "passed": passed, **({"error": error} if error else {})}
        )
    output = {
        "ok": all(item["passed"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
