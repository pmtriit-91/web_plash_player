#!/usr/bin/env python3
"""Transactional settings acceptance tests using disposable Git repositories."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_transactions import TransactionService
from control_center.test_support import BASE_SETTINGS, git


def repository(parent: Path, name: str) -> tuple[Path, Path]:
    root = parent / name
    agent_root = root / ".agents"
    (agent_root / "project").mkdir(parents=True)
    (agent_root / "skills" / "project-memory").mkdir(parents=True)
    (agent_root / "project" / "skill-config.json").write_text(json.dumps(BASE_SETTINGS, indent=2) + "\n", encoding="utf-8")
    (agent_root / "skills" / "project-memory" / "SKILL.md").write_text("protected memory\n", encoding="utf-8")
    (root / ".gitignore").write_text(".agents/_runtime/\n", encoding="utf-8")
    (root / "marker.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Agent OS Test")
    git(root, "config", "user.email", "agent-os@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture baseline")
    return root, agent_root


def desired(mode: str = "FAST") -> dict:
    value = deepcopy(BASE_SETTINGS)
    value["default_mode"] = mode
    return value


def reason(result: dict, code: str) -> bool:
    return code in result.get("reason_codes", [])


def main() -> None:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-control-transactions-") as temporary:
        base = Path(temporary)

        _, agent_root = repository(base, "success")
        service = TransactionService(agent_root)
        protected_before = (agent_root / "skills" / "project-memory" / "SKILL.md").read_bytes()
        plan = service.plan_settings(desired())
        applied = service.apply_settings(plan.get("plan", {}).get("plan_id", ""), True)
        protected_after = (agent_root / "skills" / "project-memory" / "SKILL.md").read_bytes()
        results.append({"id": "settings-plan-apply", "passed": bool(plan.get("ok") and applied.get("ok") and protected_before == protected_after and applied.get("receipt", {}).get("commit_created") is False)})

        _, agent_root = repository(base, "hard-lock")
        service = TransactionService(agent_root)
        unsafe = desired()
        unsafe["automation"]["auto_push"] = True
        rejected = service.plan_settings(unsafe)
        results.append({"id": "hard-safety-cannot-be-disabled", "passed": reason(rejected, "SETTINGS_VALIDATION_FAILED")})

        root, agent_root = repository(base, "dirty")
        service = TransactionService(agent_root)
        (root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        rejected = service.plan_settings(desired())
        results.append({"id": "dirty-git-rejected", "passed": reason(rejected, "DIRTY_GIT")})

        root, agent_root = repository(base, "stale-head")
        service = TransactionService(agent_root)
        plan = service.plan_settings(desired())
        (root / "marker.txt").write_text("new commit\n", encoding="utf-8")
        git(root, "add", "marker.txt")
        git(root, "commit", "-qm", "move head")
        rejected = service.apply_settings(plan["plan"]["plan_id"], True)
        results.append({"id": "stale-head-rejected", "passed": reason(rejected, "STALE_GIT_HEAD")})

        _, agent_root = repository(base, "stale-target")
        service = TransactionService(agent_root)
        plan = service.plan_settings(desired())
        (agent_root / "project" / "skill-config.json").write_text(json.dumps(desired("STANDARD"), indent=2) + "\n", encoding="utf-8")
        rejected = service.apply_settings(plan["plan"]["plan_id"], True)
        results.append({"id": "stale-target-rejected", "passed": reason(rejected, "STALE_TARGET_HASH")})

        _, agent_root = repository(base, "expired")
        clock = [datetime(2026, 7, 19, tzinfo=timezone.utc)]
        service = TransactionService(agent_root, now=lambda: clock[0])
        plan = service.plan_settings(desired(), expiry_seconds=60)
        clock[0] += timedelta(seconds=61)
        rejected = service.apply_settings(plan["plan"]["plan_id"], True)
        results.append({"id": "expired-plan-rejected", "passed": reason(rejected, "PLAN_EXPIRED")})

        _, agent_root = repository(base, "concurrent")
        service = TransactionService(agent_root)
        first = service.plan_settings(desired("FAST"))
        second = service.plan_settings(desired("STANDARD"))
        first_result = service.apply_settings(first["plan"]["plan_id"], True)
        second_result = service.apply_settings(second["plan"]["plan_id"], True)
        results.append({"id": "concurrent-plan-invalidated", "passed": bool(first_result.get("ok") and reason(second_result, "STALE_TARGET_HASH"))})

        _, agent_root = repository(base, "rollback")
        service = TransactionService(agent_root)
        before = (agent_root / "project" / "skill-config.json").read_bytes()
        plan = service.plan_settings(desired())
        os.environ["AGENT_OS_TEST_MODE"] = "1"
        failed = service.apply_settings(plan["plan"]["plan_id"], True, test_fail_after_write=True)
        os.environ.pop("AGENT_OS_TEST_MODE", None)
        after = (agent_root / "project" / "skill-config.json").read_bytes()
        results.append({"id": "post-write-failure-rolls-back", "passed": bool(reason(failed, "APPLY_FAILED_ROLLED_BACK") and before == after and failed.get("receipt", {}).get("rollback_verified") is True)})

        _, agent_root = repository(base, "confirmation")
        service = TransactionService(agent_root)
        plan = service.plan_settings(desired())
        rejected = service.apply_settings(plan["plan"]["plan_id"], False)
        results.append({"id": "confirmation-required", "passed": reason(rejected, "WRITE_CONFIRMATION_REQUIRED")})

        _, agent_root = repository(base, "tampered-plan")
        service = TransactionService(agent_root)
        plan = service.plan_settings(desired())
        plan_path = service.plans / f"{plan['plan']['plan_id']}.json"
        tampered = json.loads(plan_path.read_text(encoding="utf-8"))
        tampered["input"]["desired"]["default_mode"] = "STANDARD"
        plan_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
        rejected = service.apply_settings(plan["plan"]["plan_id"], True)
        results.append({"id": "tampered-plan-rejected", "passed": reason(rejected, "PLAN_INTEGRITY_FAILED")})

    passed = sum(1 for item in results if item.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
