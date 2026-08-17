#!/usr/bin/env python3
"""Focused plan/apply transaction checks."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.contracts import canonical_bytes, content_hash
from governed_reasoning.service import GovernedReasoningService

HEX = "0" * 64


def seal(value: dict) -> dict:
    value["content_sha256"] = content_hash(value)
    return value


def policy(project: str = "universal-agent-os") -> dict:
    return seal({"schema_version": 1, "policy_id": "policy-default", "project_id": project, "overlay_mode": "restrict-only", "fail_closed": True, "authority": {"binding_required": True, "confirmed_genesis_required": True, "matching_intent_required": True, "matching_approval_when_required": True, "transaction_gates_required": True, "scores_cannot_override": True}, "risk": {"unknown_reversibility": "escalate", "irreversible_without_approval": "block", "constitution_conflict": "block", "low_confidence": "escalate"}, "limits": {"max_options": 16, "max_steps": 32, "max_findings": 32, "max_evidence_refs": 32, "max_retry_budget": 8, "max_artifact_bytes": 131072}})


def plan_receipt(identifier: str = "plan-" + "1" * 24) -> dict:
    return seal({"schema_version": 1, "receipt_id": identifier, "project_id": "universal-agent-os", "created_at": "2026-08-14T00:00:00Z", "request_sha256": HEX, "authority_sha256": "a" * 64, "steps": [{"step_id": "step-1", "action": "Persist one receipt.", "depends_on": [], "acceptance": ["Exact bytes exist."], "evidence_refs": []}], "alternatives": [], "uncertainties": [], "confidence": "high", "supersedes": None, "privacy": {"raw_conversation_stored": False, "raw_prompt_stored": False, "chain_of_thought_stored": False, "secret_stored": False}})


def setup(root: Path, clock: list[datetime]):
    agent = root / ".agents"
    (agent / "project/reasoning").mkdir(parents=True)
    (agent / "project/reasoning/policy.json").write_text(json.dumps(policy()) + "\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "seed").write_text("seed\n")
    subprocess.run(["git", "add", "seed"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
    authority = {"available": True, "project_id": "universal-agent-os", "binding_sha256": "b" * 64, "genesis_revision": 2, "genesis_source_sha256": "c" * 64}
    service = GovernedReasoningService(agent, authority_inspector=lambda _: copy.deepcopy(authority), now=lambda: clock[0])
    return agent, authority, service


def main() -> None:
    cases = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    with tempfile.TemporaryDirectory(prefix="governed-transactions-") as directory:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(directory), clock)
        receipt = plan_receipt()
        planned = service.plan_receipt("plan", receipt)
        target = agent / f"project/reasoning/receipts/{receipt['receipt_id']}.json"
        check("plan-is-pending-with-exact-new-file-diff", planned["ok"] and planned["plan"]["status"] == "pending-approval" and planned["plan"]["exact_diff"].startswith("--- /dev/null") and not target.exists())
        plan_id = planned["plan"]["plan_id"]
        refused = service.apply_receipt(plan_id)
        check("apply-requires-explicit-confirmation", refused["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and not target.exists())
        applied = service.apply_receipt(plan_id, confirm=True)
        transaction = applied["receipt"]
        transaction_dir = agent / "_runtime/governed-reasoning/transactions" / transaction["transaction_id"]
        check("confirmed-apply-writes-exact-receipt", applied["ok"] and target.read_bytes() == (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode())
        check("backup-index-precedes-bounded-transaction-receipt", (transaction_dir / "backup-index.json").is_file() and (transaction_dir / "receipt.json").is_file() and transaction["target"] == f"project/reasoning/receipts/{receipt['receipt_id']}.json")
        check("applied-plan-cannot-replay", service.apply_receipt(plan_id, confirm=True)["reason_codes"] == ["PLAN_NOT_PENDING"])
        duplicate = service.plan_receipt("plan", receipt)
        check("immutable-target-cannot-be-replanned", duplicate["reason_codes"] == ["IMMUTABLE_RECEIPT_EXISTS"])

    with tempfile.TemporaryDirectory(prefix="governed-stale-") as directory:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(directory), clock)
        receipt = plan_receipt()
        stale_head = service.plan_receipt("plan", receipt)["plan"]["plan_id"]
        root = agent.parent
        (root / "later").write_text("later\n")
        subprocess.run(["git", "add", "later"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "later"], cwd=root, check=True)
        check("changed-head-rejects-before-project-write", service.apply_receipt(stale_head, confirm=True)["reason_codes"] == ["STALE_GIT_HEAD"] and not (agent / f"project/reasoning/receipts/{receipt['receipt_id']}.json").exists())
        newer = service.plan_receipt("plan", receipt, expiry_seconds=60)["plan"]["plan_id"]
        clock[0] += timedelta(seconds=61)
        check("expired-plan-rejects-before-project-write", service.apply_receipt(newer, confirm=True)["reason_codes"] == ["PLAN_EXPIRED"])

    with tempfile.TemporaryDirectory(prefix="governed-guards-") as directory:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(directory), clock)
        receipt = plan_receipt()
        policy_planned = service.plan_receipt("plan", receipt)
        policy_plan = policy_planned["plan"]["plan_id"]
        forged = copy.deepcopy(policy_planned["plan"]); forged["input"]["target"] = "../escape.json"
        forged["plan_id"] = hashlib.sha256(canonical_bytes(forged["input"])).hexdigest()[:24]; forged["content_sha256"] = content_hash(forged)
        forged_path = agent / f"_runtime/governed-reasoning/plans/{forged['plan_id']}.json"
        forged_path.write_text(json.dumps(forged, ensure_ascii=False, indent=2) + "\n")
        check("forged-target-path-fails-before-write", service.apply_receipt(forged["plan_id"], confirm=True)["reason_codes"] == ["PLAN_INTEGRITY_FAILED"] and not (agent.parent / "escape.json").exists())
        changed = policy(); changed["limits"]["max_steps"] = 31; seal(changed)
        (agent / "project/reasoning/policy.json").write_text(json.dumps(changed) + "\n")
        check("changed-policy-rejects-before-project-write", service.apply_receipt(policy_plan, confirm=True)["reason_codes"] == ["STALE_AUTHORITY_OR_POLICY"])
        (agent / "project/reasoning/policy.json").write_text(json.dumps(policy()) + "\n")
        source = plan_receipt("plan-" + "2" * 24)
        source_path = agent / f"project/reasoning/receipts/{source['receipt_id']}.json"
        source_path.parent.mkdir(parents=True, exist_ok=True); source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")
        successor = plan_receipt("plan-" + "3" * 24); successor["supersedes"] = source["receipt_id"]; seal(successor)
        source_plan = service.plan_receipt("plan", successor, [source["receipt_id"]])["plan"]["plan_id"]
        source_path.write_text(source_path.read_text().replace("Persist one", "Tamper one"))
        check("changed-source-receipt-rejects", service.apply_receipt(source_plan, confirm=True)["reason_codes"] == ["STALE_SOURCE_RECEIPT"])
        foreign = {**receipt, "project_id": "foreign"}; seal(foreign)
        check("wrong-project-and-dangling-graph-reject", service.plan_receipt("plan", foreign)["reason_codes"] == ["WRONG_PROJECT"] and not service.plan_receipt("plan", successor)["ok"])

    with tempfile.TemporaryDirectory(prefix="governed-path-") as directory:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(directory), clock)
        outside = Path(directory) / "outside"; outside.mkdir()
        (agent / "project/reasoning/receipts").symlink_to(outside, target_is_directory=True)
        unsafe = service.plan_receipt("plan", plan_receipt())
        check("symlinked-project-receipt-root-fails-closed", unsafe["reason_codes"] == ["TRANSACTION_PATH_UNSAFE"] and not list(outside.iterdir()))

    with tempfile.TemporaryDirectory(prefix="governed-runtime-path-") as directory:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(directory), clock)
        outside = Path(directory) / "outside"; outside.mkdir()
        (agent / "_runtime").symlink_to(outside, target_is_directory=True)
        unsafe = service.apply_receipt("0" * 24, confirm=True)
        check("symlinked-runtime-root-fails-before-lock-write", unsafe["reason_codes"] == ["TRANSACTION_PATH_UNSAFE"] and not list(outside.iterdir()))

    with tempfile.TemporaryDirectory(prefix="governed-rollback-") as directory:
        clock = [datetime(2026, 8, 14, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(directory), clock)
        planned = service.plan_receipt("plan", plan_receipt())
        os.environ["AGENT_OS_TEST_MODE"] = "1"
        failed = service.transactions.apply(planned["plan"]["plan_id"], True, test_fail_after_write=True)
        os.environ.pop("AGENT_OS_TEST_MODE", None)
        target = agent / "project/reasoning/receipts" / plan_receipt()["receipt_id"]
        check("post-write-failure-rolls-back-created-target", not failed["ok"] and failed["receipt"]["rollback_verified"] and not target.exists())
        crash_receipt = plan_receipt("plan-" + "4" * 24); crash_plan = service.plan_receipt("plan", crash_receipt)["plan"]
        os.environ["AGENT_OS_TEST_MODE"] = "1"
        try:
            service.transactions.apply(crash_plan["plan_id"], True, test_crash_after_write=True)
        except KeyboardInterrupt:
            pass
        os.environ.pop("AGENT_OS_TEST_MODE", None)
        incomplete = [path for path in (agent / "_runtime/governed-reasoning/transactions").iterdir() if not (path / "receipt.json").exists()]
        journal = json.loads((incomplete[0] / "backup-index.json").read_text())
        check("crash-journal-binds-plan-transaction-and-bytes", len(incomplete) == 1 and journal["transaction_id"] == incomplete[0].name and journal["plan_id"] == crash_plan["plan_id"] and journal["plan_sha256"] == crash_plan["content_sha256"] and journal["after_sha256"] == crash_plan["input"]["after_sha256"] and service.apply_receipt(crash_plan["plan_id"], confirm=True)["reason_codes"] == ["STALE_TARGET_OR_DIFF"])

    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
