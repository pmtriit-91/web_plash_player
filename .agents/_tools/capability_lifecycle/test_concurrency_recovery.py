#!/usr/bin/env python3
"""Nine focused capability concurrency, stale-state, and recovery checks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capability_lifecycle import (
    CANDIDATES,
    CAPABILITY_DECISIONS,
    DESCRIPTORS,
    MANIFEST,
    REGISTRY,
    CapabilityLifecycleService,
)
from capability_lifecycle.test_support import (
    NOW,
    assembly,
    candidate,
    fixture,
    git,
    reason,
    snapshot,
    write_json,
)


def main() -> None:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="capability-concurrency-recovery-") as temporary:
        base = Path(temporary)

        project, agent, service = fixture(base, "dirty")
        candidate_value, content = candidate()
        (project / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        blocked = service.plan_integration(candidate_value, assembly(candidate_value, content))
        results.append({"id": "dirty-git-blocked", "passed": reason(blocked, "DIRTY_GIT")})

        project, agent, service = fixture(base, "concurrent-lock")
        candidate_value, content = candidate()
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
        lock = service.acquire_lock()
        blocked = service.apply(planned["plan"]["plan_id"], True)
        service.release_lock(lock)
        results.append({"id": "concurrent-apply-lock", "passed": reason(blocked, "TRANSACTION_BUSY") and not (agent / "skills/widget-helper/SKILL.md").exists()})

        project, agent, service = fixture(base, "expired-plan")
        clock = [NOW]
        service = CapabilityLifecycleService(agent, now=lambda: clock[0])
        candidate_value, content = candidate()
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content), expiry_seconds=60)
        clock[0] += timedelta(seconds=61)
        blocked = service.apply(planned["plan"]["plan_id"], True)
        results.append({"id": "expired-plan-blocked", "passed": reason(blocked, "PLAN_EXPIRED")})

        project, agent, service = fixture(base, "stale-head")
        candidate_value, content = candidate()
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
        (project / "application.txt").write_text("new committed application\n", encoding="utf-8")
        git(project, "add", "application.txt")
        git(project, "commit", "-qm", "move head")
        blocked = service.apply(planned["plan"]["plan_id"], True)
        results.append({"id": "stale-head-blocked", "passed": reason(blocked, "STALE_GIT_HEAD")})

        project, agent, service = fixture(base, "stale-policy")
        candidate_value, content = candidate()
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
        policy = json.loads((agent / "routing/capability-policy.json").read_text())
        policy["activation"]["minimum_confidence"] = 60
        write_json(agent / "routing/capability-policy.json", policy)
        blocked = service.apply(planned["plan"]["plan_id"], True)
        results.append({"id": "stale-policy-blocked", "passed": reason(blocked, "STALE_POLICY_OR_EVAL_HASH")})

        project, agent, service = fixture(base, "tampered-plan")
        candidate_value, content = candidate()
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
        plan_path = service.plans / f"{planned['plan']['plan_id']}.json"
        tampered = json.loads(plan_path.read_text())
        tampered["input"]["capability_id"] = "tampered"
        write_json(plan_path, tampered)
        blocked = service.apply(planned["plan"]["plan_id"], True)
        results.append({"id": "tampered-plan-blocked", "passed": reason(blocked, "PLAN_INTEGRITY_FAILED")})

        project, agent, service = fixture(base, "failure-count")
        candidate_value, content = candidate()
        count_plan = service.plan_integration(candidate_value, assembly(candidate_value, content))
        write_count = len(count_plan["plan"]["input"]["changes"])
        boundary_results = []
        last_service = None
        for boundary in range(1, write_count + 1):
            project, agent, service = fixture(base, f"injected-failure-{boundary}")
            candidate_value, content = candidate()
            before = {path: (agent / path).read_bytes() for path in (REGISTRY, DESCRIPTORS, CAPABILITY_DECISIONS, CANDIDATES, MANIFEST)}
            protected_before = snapshot(agent)
            planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
            os.environ["AGENT_OS_TEST_MODE"] = "1"
            failed = service.apply(planned["plan"]["plan_id"], True, test_fail_after_write=boundary)
            os.environ.pop("AGENT_OS_TEST_MODE", None)
            after = {path: (agent / path).read_bytes() for path in before}
            boundary_results.append(bool(reason(failed, "APPLY_FAILED_ROLLED_BACK") and before == after and protected_before == snapshot(agent) and failed["receipt"]["rollback_verified"] is True))
            last_service = service
        results.append({"id": "failure-after-every-write-rolls-back-byte-for-byte", "passed": all(boundary_results) and len(boundary_results) == write_count})
        failed_candidate = next(item for item in last_service.runtime_candidate_records() if item["id"] == "widget-helper")
        results.append({"id": "failed-candidate-survives-release-rollback-in-runtime", "passed": failed_candidate["state"] == "failed" and failed_candidate["decision_history"][-1]["state"] == "failed"})

        project, agent, service = fixture(base, "crash-recovery")
        candidate_value, content = candidate()
        before = {path: (agent / path).read_bytes() for path in (REGISTRY, DESCRIPTORS, CAPABILITY_DECISIONS, CANDIDATES, MANIFEST)}
        protected_before = snapshot(agent)
        planned = service.plan_integration(candidate_value, assembly(candidate_value, content))
        os.environ["AGENT_OS_TEST_MODE"] = "1"
        interrupted = False
        try:
            service.apply(planned["plan"]["plan_id"], True, test_crash_after_write=3)
        except KeyboardInterrupt:
            interrupted = True
        os.environ.pop("AGENT_OS_TEST_MODE", None)
        second_apply = service.apply(planned["plan"]["plan_id"], True)
        confirmation = service.recover(False)
        recovered = service.recover(True)
        after = {path: (agent / path).read_bytes() for path in before}
        results.append({"id": "interrupted-transaction-recovery", "passed": bool(interrupted and reason(second_apply, "RECOVERY_REQUIRED") and reason(confirmation, "WRITE_CONFIRMATION_REQUIRED") and recovered.get("ok") and before == after and protected_before == snapshot(agent) and service.queue()["recovery_required"] is False)})

    passed = sum(1 for item in results if item.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
