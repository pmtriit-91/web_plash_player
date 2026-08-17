"""Fail-closed recovery and explicit rollback for governed reasoning writes."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_transaction_lock import (
    TransactionLockError,
    acquire_transaction_lock,
    release_transaction_lock,
)
from governed_reasoning.contracts import (
    canonical_bytes,
    content_hash,
    validate_artifact,
)
from governed_reasoning.receipts import receipt_kind
from governed_reasoning.transactions import (
    PLAN_ID_LENGTH,
    _atomic,
    _hash_bytes,
    _json_bytes,
    _load,
    _safe_parent,
)

TRANSACTION_ID_LENGTH = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and len(value) == TRANSACTION_ID_LENGTH and all(character in "0123456789abcdef" for character in value)


class ReasoningRecovery:
    """Recover interrupted creates and plan confirmed rollback of applied creates."""

    def __init__(
        self,
        agent_root: Path,
        authority_inspector: Callable[[Path], dict[str, Any]],
        now: Callable[[], datetime] = _now,
    ) -> None:
        self.root = agent_root.resolve()
        self.runtime = self.root / "_runtime/governed-reasoning"
        self.plans = self.runtime / "plans"
        self.transactions = self.runtime / "transactions"
        self.policy = self.root / "project/reasoning/policy.json"
        self.inspect_authority = authority_inspector
        self.now = now

    def _guard(self) -> dict[str, Any] | None:
        authority, policy = self.inspect_authority(self.root), _load(self.policy)
        required = {"project_id", "binding_sha256", "genesis_revision", "genesis_source_sha256"}
        if (
            not authority.get("available")
            or not required <= set(authority)
            or validate_artifact("policy", policy)
            or policy.get("project_id") != authority.get("project_id")
        ):
            return None
        return {
            "project_id": authority["project_id"],
            "binding_sha256": authority["binding_sha256"],
            "genesis_revision": authority["genesis_revision"],
            "genesis_source_sha256": authority["genesis_source_sha256"],
            "policy_sha256": content_hash(policy),
        }

    def _git_head(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.root.parent,
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _lock(self, owner: str):
        if not _safe_parent(self.root, self.runtime / "apply.lock"):
            raise TransactionLockError("TRANSACTION_PATH_UNSAFE", str(self.runtime))
        self.runtime.mkdir(parents=True, exist_ok=True)
        return acquire_transaction_lock(self.runtime / "apply.lock", owner)

    def _plan(self, plan_id: Any) -> dict[str, Any] | None:
        if not _identifier(plan_id):
            return None
        plan = _load(self.plans / f"{plan_id}.json")
        if (
            not isinstance(plan, dict)
            or plan.get("plan_id") != plan_id
            or plan.get("content_sha256") != content_hash(plan)
        ):
            return None
        return plan

    def _journal(self, transaction_id: str, *, terminal: bool) -> tuple[dict[str, Any], dict[str, Any], Path] | None:
        directory = self.transactions / transaction_id
        if not _identifier(transaction_id) or not directory.is_dir() or directory.is_symlink():
            return None
        receipt_path = directory / "receipt.json"
        if terminal != receipt_path.is_file() or receipt_path.is_symlink():
            return None
        index_path = directory / "backup-index.json"
        journal = _load(index_path)
        expected = {
            "schema_version", "transaction_id", "plan_id", "plan_sha256",
            "project_id", "git_head", "target", "before_sha256",
            "after_sha256", "existed", "content_sha256",
        }
        if (
            not isinstance(journal, dict)
            or set(journal) != expected
            or journal.get("schema_version") != 1
            or journal.get("transaction_id") != transaction_id
            or journal.get("content_sha256") != content_hash(journal)
            or journal.get("existed") is not False
            or journal.get("before_sha256") is not None
        ):
            return None
        plan = self._plan(journal.get("plan_id"))
        inputs = plan.get("input") if plan else None
        receipt = inputs.get("receipt") if isinstance(inputs, dict) else None
        target = inputs.get("target") if isinstance(inputs, dict) else None
        preapply = dict(plan) if plan else {}
        preapply.pop("transaction_id", None)
        preapply.pop("recovery_status", None)
        preapply["status"] = "pending-approval"
        preapply["content_sha256"] = content_hash(preapply)
        if (
            not isinstance(inputs, dict)
            or inputs.get("operation") != "persist-reasoning-receipt"
            or inputs.get("before_sha256") is not None
            or hashlib.sha256(canonical_bytes(inputs)).hexdigest()[:PLAN_ID_LENGTH] != plan.get("plan_id")
            or journal.get("plan_sha256") != preapply.get("content_sha256")
            or journal.get("project_id") != inputs.get("authority", {}).get("project_id")
            or journal.get("git_head") != inputs.get("git_head")
            or journal.get("target") != target
            or journal.get("after_sha256") != inputs.get("after_sha256")
            or receipt_kind(receipt) != inputs.get("kind")
            or validate_artifact(inputs.get("kind"), receipt)
            or target != f"project/reasoning/receipts/{receipt.get('receipt_id', '')}.json"
            or _hash_bytes(_json_bytes(receipt)) != journal.get("after_sha256")
        ):
            return None
        target_path = self.root / target
        if not _safe_parent(self.root, target_path):
            return None
        return journal, plan, target_path

    def recover(self, transaction_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        try:
            lock = self._lock(f"governed-reasoning-recovery:{transaction_id}")
        except TransactionLockError as error:
            return {"ok": False, "reason_codes": [error.reason_code]}
        try:
            directory = self.transactions / transaction_id
            terminal = _load(directory / "receipt.json")
            if isinstance(terminal, dict):
                if (
                    terminal.get("transaction_id") == transaction_id
                    and terminal.get("status") == "recovered-rolled-back"
                    and terminal.get("content_sha256") == content_hash(terminal)
                ):
                    validated = self._journal(transaction_id, terminal=True)
                    if validated is None:
                        return {"ok": False, "reason_codes": ["RECOVERY_JOURNAL_INVALID"]}
                    journal, plan, target = validated
                    bound = all(terminal.get(key) == journal.get(key) for key in ("plan_id", "plan_sha256", "target", "after_sha256"))
                    if not bound:
                        return {"ok": False, "reason_codes": ["RECOVERY_JOURNAL_INVALID"]}
                    if plan.get("status") == "pending-approval" and not target.exists() and not target.is_symlink():
                        plan.update(status="failed", transaction_id=transaction_id, recovery_status="recovered-rolled-back")
                        plan["content_sha256"] = content_hash(plan)
                        _atomic(self.plans / f"{journal['plan_id']}.json", _json_bytes(plan))
                        return {"ok": True, "receipt": terminal, "reconciled": True}
                    return {"ok": False, "reason_codes": ["TRANSACTION_ALREADY_TERMINAL"]}
                return {"ok": False, "reason_codes": ["RECOVERY_JOURNAL_INVALID"]}
            validated = self._journal(transaction_id, terminal=False)
            if validated is None:
                return {"ok": False, "reason_codes": ["RECOVERY_JOURNAL_INVALID"]}
            journal, plan, target = validated
            if (
                plan.get("status") != "pending-approval"
                or self._guard() != plan["input"].get("authority")
                or self._git_head() != journal["git_head"]
            ):
                return {"ok": False, "reason_codes": ["RECOVERY_GUARD_STALE"]}
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file() or _hash_bytes(target.read_bytes()) != journal["after_sha256"]:
                    return {"ok": False, "reason_codes": ["RECOVERY_TARGET_DIVERGED"]}
                target.unlink()
            if target.exists() or target.is_symlink():
                return {"ok": False, "reason_codes": ["RECOVERY_FAILED"]}
            receipt = {
                "schema_version": 1,
                "transaction_id": transaction_id,
                "plan_id": journal["plan_id"],
                "plan_sha256": journal["plan_sha256"],
                "operation": "recover-interrupted-reasoning-receipt",
                "status": "recovered-rolled-back",
                "project_id": journal["project_id"],
                "target": journal["target"],
                "before_sha256": None,
                "after_sha256": journal["after_sha256"],
                "recovered_at": self.now().isoformat().replace("+00:00", "Z"),
                "rollback_verified": True,
            }
            receipt["content_sha256"] = content_hash(receipt)
            _atomic(directory / "receipt.json", _json_bytes(receipt))
            plan.update(status="failed", transaction_id=transaction_id, recovery_status="recovered-rolled-back")
            plan["content_sha256"] = content_hash(plan)
            _atomic(self.plans / f"{journal['plan_id']}.json", _json_bytes(plan))
            return {"ok": True, "receipt": receipt}
        finally:
            release_transaction_lock(lock)
