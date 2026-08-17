#!/usr/bin/env python3
"""Focused deterministic recovery and rollback checks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.contracts import content_hash
from governed_reasoning.recovery import ReasoningRecovery
from governed_reasoning.test_transactions import plan_receipt, setup


def interrupted(agent: Path, service, identifier: str):
    receipt = plan_receipt(identifier); plan = service.plan_receipt("plan", receipt)["plan"]
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        service.transactions.apply(plan["plan_id"], True, test_crash_after_write=True)
    except KeyboardInterrupt:
        pass
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    directory = next(path for path in (agent / "_runtime/governed-reasoning/transactions").iterdir() if not (path / "receipt.json").exists())
    target = agent / plan["input"]["target"]; return plan, directory, target
def main() -> None:
    cases: list[dict[str, object]] = []
    def check(identifier: str, passed: object) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})
    with tempfile.TemporaryDirectory(prefix="reasoning-recovery-") as holder:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        plan, directory, target = interrupted(agent, service, "plan-" + "4" * 24)
        recovery = ReasoningRecovery(agent, service.transactions.inspect_authority, now=lambda: clock[0])
        check("recovery-requires-confirmation", recovery.recover(directory.name)["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and target.is_file())
        result = recovery.recover(directory.name, confirm=True)
        terminal = json.loads((directory / "receipt.json").read_text())
        updated_plan = json.loads((agent / f"_runtime/governed-reasoning/plans/{plan['plan_id']}.json").read_text())
        check("interrupted-create-recovers-byte-exact-before-state", result["ok"] and not target.exists() and terminal["rollback_verified"] is True)
        check("recovery-terminal-binds-original-plan", terminal["transaction_id"] == directory.name and terminal["plan_sha256"] == plan["content_sha256"] and updated_plan["status"] == "failed")
        check("stable-stale-lock-file-is-reacquired", (agent / "_runtime/governed-reasoning/apply.lock").is_file())
        plan_path = agent / f"_runtime/governed-reasoning/plans/{plan['plan_id']}.json"; plan_path.write_text(json.dumps(plan) + "\n")
        reconciled = recovery.recover(directory.name, confirm=True)
        check("terminal-receipt-plan-gap-reconciles", reconciled.get("reconciled") is True and json.loads(plan_path.read_text())["status"] == "failed")
        check("terminal-recovery-cannot-replay", recovery.recover(directory.name, confirm=True)["reason_codes"] == ["TRANSACTION_ALREADY_TERMINAL"])
    with tempfile.TemporaryDirectory(prefix="reasoning-partial-") as holder:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        _plan, directory, target = interrupted(agent, service, "plan-" + "5" * 24)
        target.unlink()
        recovery = ReasoningRecovery(agent, service.transactions.inspect_authority, now=lambda: clock[0])
        check("already-restored-partial-state-completes-recovery", recovery.recover(directory.name, confirm=True)["ok"] and not target.exists())
    with tempfile.TemporaryDirectory(prefix="reasoning-diverged-") as holder:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        _plan, directory, target = interrupted(agent, service, "plan-" + "6" * 24)
        target.write_text("foreign\n")
        recovery = ReasoningRecovery(agent, service.transactions.inspect_authority, now=lambda: clock[0])
        rejected = recovery.recover(directory.name, confirm=True)
        check("diverged-target-is-never-restored", rejected["reason_codes"] == ["RECOVERY_TARGET_DIVERGED"] and target.read_text() == "foreign\n" and not (directory / "receipt.json").exists())
    with tempfile.TemporaryDirectory(prefix="reasoning-corrupt-") as holder:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        _plan, directory, target = interrupted(agent, service, "plan-" + "7" * 24)
        index = directory / "backup-index.json"
        journal = json.loads(index.read_text())
        journal["target"] = "../escape.json"
        journal["content_sha256"] = content_hash(journal)
        index.write_text(json.dumps(journal) + "\n")
        recovery = ReasoningRecovery(agent, service.transactions.inspect_authority, now=lambda: clock[0])
        check("rehashed-invalid-journal-never-restores", recovery.recover(directory.name, confirm=True)["reason_codes"] == ["RECOVERY_JOURNAL_INVALID"] and target.is_file())
    with tempfile.TemporaryDirectory(prefix="reasoning-terminal-") as holder:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        receipt = plan_receipt("plan-" + "8" * 24)
        persisted = service.plan_receipt("plan", receipt)
        applied = service.apply_receipt(persisted["plan"]["plan_id"], confirm=True)
        target = agent / persisted["plan"]["input"]["target"]
        recovery = ReasoningRecovery(agent, service.transactions.inspect_authority, now=lambda: clock[0])
        result = recovery.recover(applied["receipt"]["transaction_id"], confirm=True)
        check("applied-durable-receipt-is-never-rolled-back", result["reason_codes"] == ["RECOVERY_JOURNAL_INVALID"] and target.is_file())
    result = {"ok": all(case["passed"] for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
if __name__ == "__main__":
    main()
