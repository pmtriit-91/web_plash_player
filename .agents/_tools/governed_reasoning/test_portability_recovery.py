"""Integrated portability and recovery acceptance for governed reasoning."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
AGENT_ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.contracts import canonical_bytes, content_hash
from governed_reasoning.recovery import ReasoningRecovery
from governed_reasoning.service import GovernedReasoningService
from governed_reasoning.test_recovery import interrupted
from governed_reasoning.test_transactions import plan_receipt, policy, seal, setup


def run_git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )

    with tempfile.TemporaryDirectory(prefix="reasoning-clean-clone-") as holder:
        holder_path = Path(holder)
        origin = holder_path / "origin"
        origin.mkdir()
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        origin_agent, authority, _service = setup(origin, clock)
        run_git(origin, "add", ".agents/project/reasoning/policy.json")
        run_git(origin, "commit", "-qm", "bind fixture policy")
        clone = holder_path / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(origin), str(clone)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        clone_agent = clone / ".agents"
        service = GovernedReasoningService(
            clone_agent,
            authority_inspector=lambda _: copy.deepcopy(authority),
            now=lambda: clock[0],
        )
        check(
            "clean-clone-retains-policy-bytes",
            (clone_agent / "project/reasoning/policy.json").read_bytes()
            == (origin_agent / "project/reasoning/policy.json").read_bytes(),
        )
        receipt = plan_receipt("plan-" + "a" * 24)
        planned = service.plan_receipt("plan", receipt)
        applied = service.apply_receipt(planned["plan"]["plan_id"], confirm=True)
        target = clone_agent / f"project/reasoning/receipts/{receipt['receipt_id']}.json"
        check(
            "clean-clone-plan-apply-succeeds",
            planned["ok"] and applied["ok"] and target.is_file(),
        )
        check(
            "clean-clone-receipt-is-byte-exact",
            read_json(target) == receipt
            and content_hash(read_json(target)) == receipt["content_sha256"],
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-source-clone-") as holder:
        clone = Path(holder) / "source"
        subprocess.run(
            ["git", "clone", "-q", str(AGENT_ROOT.parent), str(clone)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        shard_results = []
        for relative in (
            ".agents/_tools/governed_reasoning/test_transactions.py",
            ".agents/_tools/governed_reasoning/test_recovery.py",
        ):
            completed = subprocess.run(
                [sys.executable, relative],
                cwd=clone,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(completed.stdout) if completed.stdout else {}
            shard_results.append(completed.returncode == 0 and payload.get("ok") is True)
        check("actual-source-clean-clone-recovery-shards-pass", all(shard_results))

    with tempfile.TemporaryDirectory(prefix="reasoning-crlf-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, authority, _service = setup(Path(holder), clock)
        policy_path = agent / "project/reasoning/policy.json"
        crlf_policy = (json.dumps(policy(), ensure_ascii=False, indent=2) + "\n").replace(
            "\n", "\r\n"
        )
        policy_path.write_bytes(crlf_policy.encode("utf-8"))
        service = GovernedReasoningService(
            agent,
            authority_inspector=lambda _: copy.deepcopy(authority),
            now=lambda: clock[0],
        )
        receipt = plan_receipt("plan-" + "b" * 24)
        planned = service.plan_receipt("plan", receipt)
        applied = service.apply_receipt(planned["plan"]["plan_id"], confirm=True)
        target = agent / f"project/reasoning/receipts/{receipt['receipt_id']}.json"
        check("crlf-policy-is-portably-readable", planned["ok"] and applied["ok"])
        check(
            "persisted-receipt-uses-canonical-lf",
            b"\r\n" not in target.read_bytes() and target.read_bytes().endswith(b"\n"),
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-path-safety-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        planned = service.plan_receipt(
            "plan", plan_receipt("plan-" + "c" * 24)
        )["plan"]
        forged = copy.deepcopy(planned)
        forged["input"]["target"] = "../escape.json"
        forged["plan_id"] = hashlib.sha256(
            canonical_bytes(forged["input"])
        ).hexdigest()[:24]
        forged["content_sha256"] = content_hash(forged)
        plan_path = agent / f"_runtime/governed-reasoning/plans/{forged['plan_id']}.json"
        plan_path.write_text(json.dumps(forged) + "\n", encoding="utf-8")
        rejected = service.apply_receipt(forged["plan_id"], confirm=True)
        check(
            "traversal-target-fails-before-write",
            rejected["reason_codes"] == ["PLAN_INTEGRITY_FAILED"]
            and not (agent.parent / "escape.json").exists(),
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-symlink-safety-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        outside = Path(holder) / "outside"
        outside.mkdir()
        (agent / "project/reasoning/receipts").symlink_to(
            outside, target_is_directory=True
        )
        result = service.plan_receipt(
            "plan", plan_receipt("plan-" + "d" * 24)
        )
        check(
            "symlinked-receipt-root-fails-closed",
            result["reason_codes"] == ["TRANSACTION_PATH_UNSAFE"]
            and not list(outside.iterdir()),
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-wrong-project-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        _agent, _authority, service = setup(Path(holder), clock)
        foreign = plan_receipt("plan-" + "e" * 24)
        foreign["project_id"] = "foreign-project"
        seal(foreign)
        result = service.plan_receipt("plan", foreign)
        check(
            "wrong-project-fails-closed",
            result["reason_codes"] == ["WRONG_PROJECT"],
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-interruption-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        plan, directory, target = interrupted(
            agent, service, "plan-" + "f" * 24
        )
        recovery = ReasoningRecovery(
            agent,
            service.transactions.inspect_authority,
            now=lambda: clock[0],
        )
        refused = recovery.recover(directory.name)
        check(
            "interrupted-recovery-requires-confirmation",
            refused["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"]
            and target.is_file(),
        )
        result = recovery.recover(directory.name, confirm=True)
        terminal = read_json(directory / "receipt.json")
        updated_plan = read_json(
            agent / f"_runtime/governed-reasoning/plans/{plan['plan_id']}.json"
        )
        journal = read_json(directory / "backup-index.json")
        check(
            "interrupted-create-rolls-back-byte-exact",
            result["ok"]
            and not target.exists()
            and terminal["after_sha256"] == journal["after_sha256"],
        )
        critical_set = {
            "protected_target_absent": not target.exists(),
            "plan_terminal_failed": updated_plan.get("status") == "failed",
            "journal_hash_valid": journal.get("content_sha256")
            == content_hash(journal),
            "recovery_receipt_hash_valid": terminal.get("content_sha256")
            == content_hash(terminal),
            "rollback_verified": terminal.get("rollback_verified") is True,
        }
        check(
            "versioned-critical-set-recovers-five-of-five",
            len(critical_set) == 5 and all(critical_set.values()),
        )
        check(
            "terminal-recovery-cannot-replay",
            recovery.recover(directory.name, confirm=True)["reason_codes"]
            == ["TRANSACTION_ALREADY_TERMINAL"],
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-divergence-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        _plan, directory, target = interrupted(
            agent, service, "plan-" + "1" * 24
        )
        target.write_text("foreign\n", encoding="utf-8")
        recovery = ReasoningRecovery(
            agent,
            service.transactions.inspect_authority,
            now=lambda: clock[0],
        )
        rejected = recovery.recover(directory.name, confirm=True)
        check(
            "diverged-target-is-preserved",
            rejected["reason_codes"] == ["RECOVERY_TARGET_DIVERGED"]
            and target.read_text(encoding="utf-8") == "foreign\n",
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-stale-recovery-") as holder:
        root = Path(holder)
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, _authority, service = setup(root, clock)
        _plan, directory, target = interrupted(
            agent, service, "plan-" + "2" * 24
        )
        (root / "later").write_text("later\n", encoding="utf-8")
        run_git(root, "add", "later")
        run_git(root, "commit", "-qm", "move head")
        recovery = ReasoningRecovery(
            agent,
            service.transactions.inspect_authority,
            now=lambda: clock[0],
        )
        rejected = recovery.recover(directory.name, confirm=True)
        check(
            "stale-head-recovery-fails-closed",
            rejected["reason_codes"] == ["RECOVERY_GUARD_STALE"]
            and target.is_file(),
        )

    with tempfile.TemporaryDirectory(prefix="reasoning-rollback-") as holder:
        clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
        agent, _authority, service = setup(Path(holder), clock)
        receipt = plan_receipt("plan-" + "3" * 24)
        planned = service.plan_receipt("plan", receipt)["plan"]
        os.environ["AGENT_OS_TEST_MODE"] = "1"
        try:
            result = service.transactions.apply(
                planned["plan_id"], True, test_fail_after_write=True
            )
        finally:
            os.environ.pop("AGENT_OS_TEST_MODE", None)
        target = agent / f"project/reasoning/receipts/{receipt['receipt_id']}.json"
        check(
            "post-write-failure-rolls-back",
            not result["ok"]
            and result["receipt"]["rollback_verified"] is True
            and not target.exists(),
        )

    evidence_path = (
        AGENT_ROOT.parent
        / "docs/evolution/aos-16/evidence/w5-portability-recovery-verification.json"
    )
    evidence = (
        read_json(evidence_path)
        if evidence_path.is_file()
        else {}
    )
    check(
        "evidence-binds-declared-recovery-envelope",
        evidence.get("status") == "verified"
        and evidence.get("result", {}).get("passed") == 17
        and evidence.get("result", {}).get("total") == 17
        and evidence.get("result", {}).get("critical_set_recovered") == "5/5"
        and evidence.get("claims", {}).get("critical_set_recovery")
        == "100% observed recovery for the declared versioned critical set"
        and evidence.get("claims", {}).get("outside_envelope_guarantee") is False
        and evidence.get("claims", {}).get("hosted_or_platform_coverage") is False,
    )

    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
