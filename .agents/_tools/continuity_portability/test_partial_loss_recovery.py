#!/usr/bin/env python3
"""Focused P2b proof that partial-loss recovery never invents owner truth."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity import doctor
from agent_os_continuity_transactions import (
    CATALOG_REL,
    PROJECTION_REL,
    ContinuityTransactionService,
)
from continuity_transactions.test_support import W3, make_fixture


def plan_names(service: ContinuityTransactionService) -> set[str]:
    return (
        {item.name for item in service.plans.iterdir()}
        if service.plans.is_dir()
        else set()
    )


def optional_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": passed, **details})

    with tempfile.TemporaryDirectory(prefix="aos15-w6-p2b-no-backup-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        service = ContinuityTransactionService(root)
        baseline = doctor(root)
        roadmap = root.parent / "docs/roadmap.md"
        catalog_before = (root / CATALOG_REL).read_bytes()
        projection_before = optional_bytes(root / PROJECTION_REL)
        roadmap.unlink()
        lost = doctor(root)
        roadmap_result = next(
            item for item in lost["references"] if item["reference_id"] == "roadmap"
        )
        plans_before = plan_names(service)
        repair = service.plan_repair()

        check(
            "configured-fixture-starts-topologically-complete",
            baseline.get("topology_state") == "complete",
        )
        check(
            "required-source-loss-makes-topology-incomplete",
            lost.get("topology_state") == "incomplete"
            and "CONTINUITY_REQUIRED_SOURCE_MISSING" in lost.get("reason_codes", []),
            reason_codes=lost.get("reason_codes"),
        )
        check(
            "lost-reference-has-exact-missing-readiness",
            roadmap_result.get("readiness") == "missing"
            and roadmap_result.get("reason_codes")
            == ["CONTINUITY_REQUIRED_SOURCE_MISSING"],
            reference=roadmap_result,
        )
        check(
            "repair-without-backup-fails-before-plan-write",
            repair
            == {
                "ok": False,
                "reason_codes": [
                    "CONTINUITY_REQUIRED_SOURCE_MISSING",
                    "CONTINUITY_STATE_AWARE_SOURCE_MISSING",
                    "CONTINUITY_TARGET_NOT_SEMANTICALLY_COMPLETE",
                ],
            }
            and plan_names(service) == plans_before,
            repair=repair,
        )
        check(
            "failed-repair-does-not-recreate-or-mutate-owner-truth",
            not roadmap.exists()
            and (root / CATALOG_REL).read_bytes() == catalog_before
            and optional_bytes(root / PROJECTION_REL) == projection_before
            and lost.get("raw_conversation_stored") is False
            and lost.get("write_performed") is False,
        )

    with tempfile.TemporaryDirectory(prefix="aos15-w6-p2b-backup-") as temporary:
        root = make_fixture(Path(temporary), configured=True)
        service = ContinuityTransactionService(root)
        roadmap = root.parent / "docs/roadmap.md"
        roadmap.write_text("# Updated roadmap\n", encoding="utf-8")
        W3.commit_all(root.parent, "update partial-loss fixture source")
        refresh_plan = service.plan_refresh()
        refreshed = (
            service.apply(refresh_plan["plan"]["plan_id"], True)
            if refresh_plan.get("ok")
            else refresh_plan
        )
        backup_id = refreshed.get("backup", {}).get("backup_id")
        roadmap.unlink()
        catalog_before = (root / CATALOG_REL).read_bytes()
        projection_before = optional_bytes(root / PROJECTION_REL)
        plans_before = plan_names(service)
        repair = service.plan_repair(backup_id)
        after = doctor(root)

        check(
            "reviewed-backup-fixture-is-valid-before-loss",
            refresh_plan.get("ok") is True
            and refreshed.get("ok") is True
            and isinstance(backup_id, str),
        )
        check(
            "backup-repair-still-refuses-to-invent-missing-source",
            repair
            == {
                "ok": False,
                "reason_codes": [
                    "CONTINUITY_REQUIRED_SOURCE_MISSING",
                    "CONTINUITY_SOURCE_DRIFT",
                    "CONTINUITY_STATE_AWARE_SOURCE_MISSING",
                    "CONTINUITY_TARGET_NOT_SEMANTICALLY_COMPLETE",
                ],
            },
            repair=repair,
        )
        check(
            "backup-repair-failure-is-byte-stable-and-plan-free",
            not roadmap.exists()
            and (root / CATALOG_REL).read_bytes() == catalog_before
            and optional_bytes(root / PROJECTION_REL) == projection_before
            and plan_names(service) == plans_before,
        )
        check(
            "post-repair-health-remains-honestly-incomplete-and-private",
            after.get("topology_state") == "incomplete"
            and "CONTINUITY_REQUIRED_SOURCE_MISSING" in after.get("reason_codes", [])
            and after.get("raw_conversation_stored") is False
            and after.get("write_performed") is False,
            reason_codes=after.get("reason_codes"),
        )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
