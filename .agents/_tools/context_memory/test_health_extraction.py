#!/usr/bin/env python3
"""BR3a0 focused parity shard for extracted health/load orchestration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import health


class FakeService:
    def __init__(self, root: Path, state: str = "FRESH"):
        self.root = root
        self.state = state
        self.manifest = {
            "project_id": "fixture-project",
            "refreshed_commit": "a" * 40,
            "sources": [
                {"tier": "hot", "path": "project/context/hot.json"},
                {"tier": "warm", "path": "project/context/warm.json"},
            ],
            "authority_order": ["binding"],
        }
        self.documents = {
            facade.MANIFEST_REL: self.manifest,
            facade.HOT_REL: {"records": [{"id": "hot-one"}]},
            facade.WARM_REL: {"records": [{"id": "warm-one"}]},
            facade.TASKS_REL: {"tasks": [{"id": "active-one", "status": "active"}]},
        }

    def path(self, relative: str) -> Path:
        return self.root / relative

    def binding(self):
        return {"project_id": "fixture-project"}

    def document(self, relative: str, default):
        return self.documents.get(relative, default)

    def validate_manifest(self, manifest):
        del manifest
        errors = [{"code": "BROKEN"}] if self.state == "DEGRADED" else []
        stale = [{"code": "STALE"}] if self.state == "STALE" else []
        return {
            "errors": errors,
            "stale": stale,
            "conflicts": [],
            "warnings": [{"code": "DISCLOSED"}],
            "tasks": self.documents[facade.TASKS_REL],
            "handoff_durability": {"receipts": 2},
        }

    def head(self):
        return "b" * 40

    def doctor(self):
        return health.doctor(self)


def configured(base: Path, state: str = "FRESH") -> FakeService:
    service = FakeService(base, state)
    path = service.path(facade.MANIFEST_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return service


def case_facade_doctor_delegates(base: Path) -> bool:
    del base
    service = object.__new__(facade.ContextMemoryService)
    original = facade.context_health.doctor
    facade.context_health.doctor = lambda received: {"marker": received is service}
    try:
        return service.doctor() == {"marker": True}
    finally:
        facade.context_health.doctor = original


def case_facade_load_delegates(base: Path) -> bool:
    del base
    service = object.__new__(facade.ContextMemoryService)
    original = facade.context_health.load
    facade.context_health.load = lambda received, tier: {
        "marker": received is service,
        "tier": tier,
    }
    try:
        return service.load("warm") == {"marker": True, "tier": "warm"}
    finally:
        facade.context_health.load = original


def case_unconfigured_contract(base: Path) -> bool:
    result = health.doctor(FakeService(base))
    return result.get("state") == "UNCONFIGURED" and result.get("reason_codes") == [
        "CONTEXT_MANIFEST_MISSING"
    ]


def case_fresh_contract(base: Path) -> bool:
    result = health.doctor(configured(base))
    return (
        result.get("ok") is True
        and result.get("state") == "FRESH"
        and result.get("task_count") == 1
        and result.get("handoff_durability") == {"receipts": 2}
    )


def case_stale_contract(base: Path) -> bool:
    result = health.doctor(configured(base, "STALE"))
    return (
        result.get("ok") is False
        and result.get("state") == "STALE"
        and result.get("reason_codes") == ["STALE"]
    )


def case_degraded_precedes_stale(base: Path) -> bool:
    service = configured(base)
    service.validate_manifest = lambda manifest: {
        "errors": [{"code": "BROKEN"}],
        "stale": [{"code": "STALE"}],
        "conflicts": [],
        "tasks": {},
    }
    result = health.doctor(service)
    return result.get("state") == "DEGRADED" and result.get("reason_codes") == [
        "BROKEN",
        "STALE",
    ]


def case_invalid_tier(base: Path) -> bool:
    return health.load(configured(base), "invalid").get("reason_codes") == [
        "CONTEXT_TIER_INVALID"
    ]


def case_degraded_load_is_empty(base: Path) -> bool:
    result = health.load(configured(base, "DEGRADED"), "hot")
    return (
        result.get("ok") is False
        and result.get("authoritative") is False
        and result.get("records") == []
        and result.get("tasks") == []
    )


def case_hot_load_preserves_tasks(base: Path) -> bool:
    result = health.load(configured(base), "hot")
    return (
        result.get("authoritative") is True
        and result.get("records") == [{"id": "hot-one"}]
        and result.get("tasks") == [{"id": "active-one", "status": "active"}]
    )


def case_non_hot_load_excludes_tasks(base: Path) -> bool:
    result = health.load(configured(base, "STALE"), "warm")
    return (
        result.get("ok") is True
        and result.get("authoritative") is False
        and result.get("freshness_state") == "STALE"
        and result.get("tasks") == []
        and result.get("records") == [{"id": "warm-one"}]
    )


CASES = [
    ("facade-doctor-delegation", case_facade_doctor_delegates),
    ("facade-load-delegation", case_facade_load_delegates),
    ("unconfigured-contract", case_unconfigured_contract),
    ("fresh-contract", case_fresh_contract),
    ("stale-contract", case_stale_contract),
    ("degraded-precedence", case_degraded_precedes_stale),
    ("invalid-tier", case_invalid_tier),
    ("degraded-load-empty", case_degraded_load_is_empty),
    ("hot-load-tasks", case_hot_load_preserves_tasks),
    ("non-hot-no-tasks", case_non_hot_load_excludes_tasks),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br3a0-") as temporary:
        for index, (name, check) in enumerate(CASES):
            try:
                passed, error = bool(check(Path(temporary) / str(index))), None
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
