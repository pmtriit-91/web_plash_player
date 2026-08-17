#!/usr/bin/env python3
"""Five focused capability lifecycle plan, apply, and rollback checks."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capability_lifecycle import (
    CAPABILITY_DECISIONS,
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    MANIFEST,
    receipt_valid,
)
from capability_lifecycle.test_support import (
    assembly,
    candidate,
    fixture,
    git,
    reason,
    snapshot,
)


def main() -> None:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="capability-plan-apply-rollback-") as temporary:
        base = Path(temporary)
        project, agent, service = fixture(base, "success")
        candidate_value, content = candidate()
        protected_before = snapshot(agent)
        tracked_before = git(project, "status", "--porcelain")
        head_before = git(project, "rev-parse", "HEAD")
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
        results.append(
            {
                "id": "plan-is-read-only",
                "passed": bool(planned.get("ok") and tracked_before == git(project, "status", "--porcelain") and head_before == git(project, "rev-parse", "HEAD")),
            }
        )
        rejected = service.apply(planned["plan"]["plan_id"], False)
        results.append(
            {
                "id": "confirmation-required",
                "passed": reason(rejected, "WRITE_CONFIRMATION_REQUIRED"),
            }
        )
        applied = service.apply(planned["plan"]["plan_id"], True)
        descriptor_document = json.loads((agent / DESCRIPTORS).read_text())
        descriptor = next(item for item in descriptor_document["capabilities"] if item["id"] == "widget-helper")
        active_candidate = next(item for item in service.runtime_candidate_records() if item["id"] == "widget-helper")
        lifecycle = json.loads((agent / LIFECYCLE_LEDGER).read_text())["receipts"][-1]
        manifest = json.loads((agent / MANIFEST).read_text())
        results.append(
            {
                "id": "one-approval-active-working-baseline",
                "passed": bool(applied.get("ok") and descriptor["lifecycle_state"] == "active" and active_candidate["state"] == "active" and receipt_valid(lifecycle) and manifest["provenance"]["status"] == "working-baseline" and manifest["provenance"]["source_commit"] is None and snapshot(agent) == protected_before and git(project, "rev-parse", "HEAD") == head_before and applied["receipt"]["commit_created"] is False and applied["receipt"]["push_performed"] is False),
            }
        )
        replay = service.apply(planned["plan"]["plan_id"], True)
        results.append({"id": "plan-replay-rejected", "passed": reason(replay, "PLAN_NOT_PENDING")})

        rollback_plan = service.plan_rollback(applied["receipt"]["transaction_id"])
        rolled_back = service.apply(rollback_plan.get("plan", {}).get("plan_id", ""), True)
        rolled_descriptors = json.loads((agent / DESCRIPTORS).read_text())["capabilities"]
        rolled_candidate = next(item for item in service.runtime_candidate_records() if item["id"] == "widget-helper")
        retained_decisions = json.loads((agent / CAPABILITY_DECISIONS).read_text())["receipts"]
        rollback_history = json.loads((agent / LIFECYCLE_LEDGER).read_text())["receipts"]
        results.append(
            {
                "id": "explicit-rollback-restores-functional-state",
                "passed": bool(rollback_plan.get("ok") and rolled_back.get("ok") and all(item["id"] != "widget-helper" for item in rolled_descriptors) and not (agent / "skills/widget-helper/SKILL.md").exists() and rolled_candidate["state"] == "deprecated" and any(item.get("candidate_id") == "widget-helper" for item in retained_decisions) and rollback_history[-1]["action"] == "rollback" and snapshot(agent) == protected_before),
            }
        )

    passed = sum(1 for item in results if item.get("passed"))
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
