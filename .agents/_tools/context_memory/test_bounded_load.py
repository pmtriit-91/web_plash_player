#!/usr/bin/env python3
"""BR3a1 focused shard for bounded load and quick doctor."""

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
    def __init__(self, root: Path):
        self.root = root
        self.calls: list[dict[str, object]] = []
        self.validation = {
            "errors": [],
            "stale": [],
            "conflicts": [],
            "warnings": [],
            "tasks": {"tasks": []},
            "handoff_durability": {},
        }
        self.manifest = {
            "project_id": "fixture-project",
            "refreshed_commit": "a" * 40,
            "sources": [
                {"tier": "hot", "path": facade.HOT_REL},
                {"tier": "warm", "path": facade.WARM_REL},
            ],
            "authority_order": ["binding"],
        }
        self.documents = {
            facade.MANIFEST_REL: self.manifest,
            facade.HOT_REL: {"records": [{"id": "hot-one"}]},
            facade.WARM_REL: {"records": [{"id": "warm-one"}]},
            facade.TASKS_REL: {
                "tasks": [
                    {"id": "active", "status": "active"},
                    {"id": "blocked", "status": "blocked"},
                    {"id": "done", "status": "handed-off"},
                    "invalid",
                ]
            },
        }

    def configure(self) -> FakeService:
        path = self.path(facade.MANIFEST_REL)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return self

    def path(self, relative: str) -> Path:
        return self.root / relative

    def binding(self) -> dict[str, str]:
        return {"project_id": "fixture-project"}

    def document(self, relative: str, default: object) -> object:
        return self.documents.get(relative, default)

    def validate_manifest(
        self, manifest: object, **options: object
    ) -> dict[str, object]:
        self.calls.append({"manifest": manifest, **options})
        return self.validation

    def validate_current_authority(self, manifest: object) -> dict[str, object]:
        return self.validate_manifest(
            manifest,
            verify_evidence=False,
            verify_handoffs=False,
        )

    def head(self) -> str:
        return "b" * 40


def case_quick_skips_history(base: Path) -> bool:
    service = FakeService(base).configure()
    result = health.quick_doctor(service)
    return result["state"] == "FRESH" and service.calls == [
        {
            "manifest": service.manifest,
            "verify_evidence": False,
            "verify_handoffs": False,
        }
    ]


def case_deep_preserves_default_validation(base: Path) -> bool:
    service = FakeService(base).configure()
    result = health.doctor(service)
    return result["state"] == "FRESH" and service.calls == [
        {"manifest": service.manifest}
    ]


def case_quick_unconfigured(base: Path) -> bool:
    service = FakeService(base)
    result = health.quick_doctor(service)
    return result["state"] == "UNCONFIGURED" and not service.calls


def case_quick_fails_closed_error(base: Path) -> bool:
    service = FakeService(base).configure()
    service.validation["errors"] = [{"code": "CONTEXT_PROJECTION_NON_CANONICAL"}]
    result = health.quick_doctor(service)
    return result["state"] == "DEGRADED" and result["reason_codes"] == [
        "CONTEXT_PROJECTION_NON_CANONICAL"
    ]


def case_quick_reports_stale(base: Path) -> bool:
    service = FakeService(base).configure()
    service.validation["stale"] = [{"code": "TASK_LEDGER_STALE"}]
    result = health.quick_doctor(service)
    return result["state"] == "STALE" and result["reason_codes"] == [
        "TASK_LEDGER_STALE"
    ]


def case_load_uses_quick_path(base: Path) -> bool:
    service = FakeService(base).configure()
    result = health.load(service, "hot")
    return result["ok"] is True and service.calls[0].get("verify_handoffs") is False


def case_hot_filters_terminal(base: Path) -> bool:
    result = health.load(FakeService(base).configure(), "hot")
    return [task["id"] for task in result["tasks"]] == ["active", "blocked"]


def case_warm_excludes_tasks(base: Path) -> bool:
    result = health.load(FakeService(base).configure(), "warm")
    return result["records"] == [{"id": "warm-one"}] and result["tasks"] == []


def case_degraded_load_empty(base: Path) -> bool:
    service = FakeService(base).configure()
    service.validation["errors"] = [{"code": "TASK_LEDGER_V2_INDEX_HASH_MISMATCH"}]
    result = health.load(service, "hot")
    return result["ok"] is False and result["records"] == [] and result["tasks"] == []


def case_invalid_tier_short_circuits(base: Path) -> bool:
    service = FakeService(base).configure()
    result = health.load(service, "terminal-history")
    return result["reason_codes"] == ["CONTEXT_TIER_INVALID"] and not service.calls


CASES = [
    ("quick-skips-history", case_quick_skips_history),
    ("deep-default", case_deep_preserves_default_validation),
    ("quick-unconfigured", case_quick_unconfigured),
    ("quick-error", case_quick_fails_closed_error),
    ("quick-stale", case_quick_reports_stale),
    ("load-uses-quick", case_load_uses_quick_path),
    ("hot-filters-terminal", case_hot_filters_terminal),
    ("warm-no-tasks", case_warm_excludes_tasks),
    ("degraded-empty", case_degraded_load_empty),
    ("invalid-tier", case_invalid_tier_short_circuits),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br3a1-") as temporary:
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
