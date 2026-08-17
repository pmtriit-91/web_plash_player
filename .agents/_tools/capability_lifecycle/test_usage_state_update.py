#!/usr/bin/env python3
"""Usage, deprecation and update lifecycle acceptance tests."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capability_lifecycle import CAPABILITY_DECISIONS, DESCRIPTORS
from capability_lifecycle.test_support import assembly, candidate, fixture, git

SECOND_COMMIT = "89abcdef0123456789abcdef0123456789abcdef"


def main() -> None:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-capability-lifecycle-") as temporary:
        base = Path(temporary)

        project, agent, service = fixture(base, "usage")
        usage = service.record_usage(
            "standard_feature",
            "secret raw task prompt",
            "high",
            ["trigger:feature", "token=secret-evidence-marker"],
            "failed",
        )
        for _ in range(2):
            service.record_usage(
                "standard_feature",
                "another task",
                "high",
                ["trigger:feature"],
                "declined",
            )
        review = service.usage_review()
        raw_log = service.telemetry.read_text()
        summary = next(item for item in review["summary"] if item["capability_id"] == "standard_feature")
        results.append(
            {
                "id": "usage-is-redacted-and-reviewable",
                "passed": bool(usage.get("ok") and "secret raw task prompt" not in raw_log and "trigger:feature" not in raw_log and "token=secret-evidence-marker" not in raw_log and usage["raw_prompt_stored"] is False and usage["raw_evidence_stored"] is False and usage["receipt"].get("schema_version") == 2 and "evidence" not in usage["receipt"] and len(usage["receipt"].get("evidence_hashes", [])) == 2 and summary["review_recommended"] is True),
            }
        )

        project, agent, service = fixture(base, "state-change")
        planned = service.plan_state_change("standard_feature", "deprecated")
        applied = service.apply(planned.get("plan", {}).get("plan_id", ""), True)
        descriptor = json.loads((agent / DESCRIPTORS).read_text())["capabilities"][0]
        results.append(
            {
                "id": "deprecation-preserves-card-and-excludes-auto-state",
                "passed": bool(planned.get("ok") and applied.get("ok") and descriptor["id"] == "standard_feature" and descriptor["lifecycle_state"] == "deprecated"),
            }
        )

        project, agent, service = fixture(base, "update")
        candidate_v1, content_v1 = candidate("widget-helper-v1")
        plan_v1 = service.plan_integration(candidate_v1, assembly(candidate_v1, content_v1))
        applied_v1 = service.apply(plan_v1["plan"]["plan_id"], True)
        git(project, "add", ".agents")
        git(project, "commit", "-qm", "activate v1 fixture")
        content_v2 = content_v1 + "\nUse the second pinned revision.\n"
        candidate_v2, _ = candidate("widget-helper-v2", SECOND_COMMIT, skill=content_v2)
        comparison = service.compare_update("widget-helper", candidate_v2)
        proposal_v2 = assembly(candidate_v2, content_v2, version="2.0.0")
        plan_v2 = service.plan_integration(candidate_v2, proposal_v2)
        applied_v2 = service.apply(plan_v2.get("plan", {}).get("plan_id", ""), True)
        descriptors = json.loads((agent / DESCRIPTORS).read_text())["capabilities"]
        descriptor = next(item for item in descriptors if item["id"] == "widget-helper")
        decisions = json.loads((agent / CAPABILITY_DECISIONS).read_text())["receipts"]
        results.append(
            {
                "id": "passing-update-supersedes-old-decision",
                "passed": bool(applied_v1.get("ok") and comparison.get("eligible_for_plan") is True and comparison.get("old_pin_remains_active_until_apply") is True and plan_v2.get("ok") and applied_v2.get("ok") and descriptor["version"] == "2.0.0" and decisions[-1]["supersedes"] == decisions[-2]["id"]),
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
