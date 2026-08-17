"""Two-phase persistence for immutable governed reasoning receipts."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
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
from governed_reasoning.receipts import receipt_kind, validate_receipt_graph

PLAN_ID_LENGTH = 24


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def _atomic(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load(path: Path) -> Any:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 131072:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _safe_parent(root: Path, path: Path) -> bool:
    """Reject paths whose existing ancestry escapes through a non-directory/symlink."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if any(part in {".", ".."} for part in relative.parts):
        return False
    cursor = root
    for part in relative.parts[:-1]:
        cursor /= part
        if cursor.is_symlink() or cursor.exists() and not cursor.is_dir():
            return False
    return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReasoningTransactions:
    """Plan and apply one exact, immutable project receipt write."""

    def __init__(
        self,
        agent_root: Path,
        authority_inspector: Callable[[Path], dict[str, Any]],
        now: Callable[[], datetime] = _now,
    ) -> None:
        self.root = agent_root.resolve()
        self.project_root = self.root.parent
        self.runtime = self.root / "_runtime/governed-reasoning"
        self.plans = self.runtime / "plans"
        self.transactions = self.runtime / "transactions"
        self.receipts = self.root / "project/reasoning/receipts"
        self.policy = self.root / "project/reasoning/policy.json"
        self.inspect_authority = authority_inspector
        self.now = now

    def _git_head(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.project_root,
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _source_documents(self, source_ids: list[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        documents, guards = [], {}
        if len(source_ids) != len(set(source_ids)) or len(source_ids) > 16:
            raise ValueError("SOURCE_RECEIPT_SET_INVALID")
        for identifier in source_ids:
            if receipt_kind({"receipt_id": identifier}) is None:
                raise ValueError("SOURCE_RECEIPT_ID_INVALID")
            relative = f"project/reasoning/receipts/{identifier}.json"
            path = self.root / relative
            document = _load(path)
            kind = receipt_kind(document)
            if kind is None or validate_artifact(kind, document):
                raise ValueError("SOURCE_RECEIPT_INVALID")
            documents.append(document)
            guards[relative] = _hash_bytes(path.read_bytes())
        return documents, guards

    def _guard(self, authority: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
        required = {"project_id", "binding_sha256", "genesis_revision", "genesis_source_sha256"}
        if not authority.get("available") or not required <= set(authority) or validate_artifact("policy", policy):
            return None
        if policy.get("project_id") != authority.get("project_id"):
            return None
        return {
            "project_id": authority["project_id"],
            "binding_sha256": authority["binding_sha256"],
            "genesis_revision": authority["genesis_revision"],
            "genesis_source_sha256": authority["genesis_source_sha256"],
            "policy_sha256": content_hash(policy),
        }

    def plan(self, kind: str, receipt: Any, source_ids: list[str], expiry_seconds: int = 900) -> dict[str, Any]:
        head, authority, policy = self._git_head(), self.inspect_authority(self.root), _load(self.policy)
        guard = self._guard(authority, policy)
        if head is None or guard is None:
            return {"ok": False, "reason_codes": ["TRANSACTION_AUTHORITY_UNAVAILABLE"]}
        if not 60 <= expiry_seconds <= 3600 or receipt_kind(receipt) != kind or validate_artifact(kind, receipt):
            return {"ok": False, "reason_codes": ["TRANSACTION_INPUT_INVALID"]}
        if receipt["project_id"] != guard["project_id"]:
            return {"ok": False, "reason_codes": ["WRONG_PROJECT"]}
        try:
            sources, source_guards = self._source_documents(source_ids)
        except ValueError as error:
            return {"ok": False, "reason_codes": [str(error)]}
        graph = validate_receipt_graph(
            [*sources, receipt], project_id=guard["project_id"],
            request_sha256=receipt["request_sha256"], authority_sha256=receipt["authority_sha256"],
        )
        if not graph["ok"]:
            return graph
        target = f"project/reasoning/receipts/{receipt['receipt_id']}.json"
        target_path = self.root / target
        if not _safe_parent(self.root, target_path):
            return {"ok": False, "reason_codes": ["TRANSACTION_PATH_UNSAFE"]}
        if target_path.exists() or target_path.is_symlink():
            return {"ok": False, "reason_codes": ["IMMUTABLE_RECEIPT_EXISTS"]}
        after = _json_bytes(receipt)
        created = self.now()
        plan_input = {
            "operation": "persist-reasoning-receipt", "kind": kind, "git_head": head,
            "authority": guard, "source_receipt_hashes": source_guards, "target": target,
            "before_sha256": None, "after_sha256": _hash_bytes(after), "receipt": receipt,
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "expires_at": (created + timedelta(seconds=expiry_seconds)).isoformat().replace("+00:00", "Z"),
        }
        plan_id = hashlib.sha256(canonical_bytes(plan_input)).hexdigest()[:PLAN_ID_LENGTH]
        diff = "".join(difflib.unified_diff([], after.decode().splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/.agents/{target}"))
        plan = {"schema_version": 1, "plan_id": plan_id, "status": "pending-approval", "input": plan_input, "exact_diff": diff}
        plan["content_sha256"] = content_hash(plan)
        if not _safe_parent(self.root, self.plans / f"{plan_id}.json"):
            return {"ok": False, "reason_codes": ["TRANSACTION_PATH_UNSAFE"]}
        _atomic(self.plans / f"{plan_id}.json", _json_bytes(plan))
        return {"ok": True, "plan": plan}

    def _validate_pending(self, plan_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        if len(plan_id) != PLAN_ID_LENGTH or any(character not in "0123456789abcdef" for character in plan_id):
            return None, ["PLAN_ID_INVALID"]
        plan = _load(self.plans / f"{plan_id}.json")
        if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
            return None, ["PLAN_NOT_FOUND"]
        if plan.get("content_sha256") != content_hash(plan):
            return None, ["PLAN_INTEGRITY_FAILED"]
        if plan.get("status") != "pending-approval":
            return None, ["PLAN_NOT_PENDING"]
        inputs = plan.get("input", {})
        expected = {"operation", "kind", "git_head", "authority", "source_receipt_hashes", "target", "before_sha256", "after_sha256", "receipt", "created_at", "expires_at"}
        if not isinstance(inputs, dict) or set(inputs) != expected or inputs.get("operation") != "persist-reasoning-receipt" or inputs.get("before_sha256") is not None:
            return None, ["PLAN_INTEGRITY_FAILED"]
        try:
            expired = self.now() > datetime.fromisoformat(inputs["expires_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return None, ["PLAN_INTEGRITY_FAILED"]
        if expired:
            return None, ["PLAN_EXPIRED"]
        if hashlib.sha256(canonical_bytes(inputs)).hexdigest()[:PLAN_ID_LENGTH] != plan_id:
            return None, ["PLAN_INTEGRITY_FAILED"]
        return plan, []

    def apply(self, plan_id: str, confirm: bool, *, test_fail_after_write: bool = False, test_crash_after_write: bool = False) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        if not _safe_parent(self.root, self.runtime / "apply.lock"):
            return {"ok": False, "reason_codes": ["TRANSACTION_PATH_UNSAFE"]}
        self.runtime.mkdir(parents=True, exist_ok=True)
        try:
            lock = acquire_transaction_lock(self.runtime / "apply.lock", f"governed-reasoning:{plan_id}")
        except TransactionLockError as error:
            return {"ok": False, "reason_codes": [error.reason_code]}
        try:
            plan, reasons = self._validate_pending(plan_id)
            if plan is None:
                return {"ok": False, "reason_codes": reasons}
            inputs = plan["input"]
            if self._git_head() != inputs["git_head"]:
                return {"ok": False, "reason_codes": ["STALE_GIT_HEAD"]}
            authority, policy = self.inspect_authority(self.root), _load(self.policy)
            if self._guard(authority, policy) != inputs["authority"]:
                return {"ok": False, "reason_codes": ["STALE_AUTHORITY_OR_POLICY"]}
            receipt, kind = inputs.get("receipt"), inputs.get("kind")
            expected_target = f"project/reasoning/receipts/{receipt.get('receipt_id', '')}.json" if isinstance(receipt, dict) else ""
            source_hashes = inputs.get("source_receipt_hashes")
            if receipt_kind(receipt) != kind or validate_artifact(kind, receipt) or inputs.get("target") != expected_target or not isinstance(source_hashes, dict):
                return {"ok": False, "reason_codes": ["PLAN_INTEGRITY_FAILED"]}
            source_ids = []
            for relative in source_hashes:
                candidate = Path(relative)
                if candidate.parent.as_posix() != "project/reasoning/receipts" or candidate.suffix != ".json":
                    return {"ok": False, "reason_codes": ["PLAN_INTEGRITY_FAILED"]}
                source_ids.append(candidate.stem)
            try:
                sources, current_source_hashes = self._source_documents(source_ids)
            except ValueError:
                return {"ok": False, "reason_codes": ["STALE_SOURCE_RECEIPT"]}
            if current_source_hashes != source_hashes:
                return {"ok": False, "reason_codes": ["STALE_SOURCE_RECEIPT"]}
            graph = validate_receipt_graph([*sources, receipt], project_id=inputs["authority"]["project_id"], request_sha256=receipt["request_sha256"], authority_sha256=receipt["authority_sha256"])
            if not graph["ok"]:
                return graph
            target, after = self.root / expected_target, _json_bytes(receipt)
            expected_diff = "".join(difflib.unified_diff([], after.decode().splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/.agents/{inputs['target']}"))
            if not _safe_parent(self.root, target) or not _safe_parent(self.root, self.transactions / "placeholder"):
                return {"ok": False, "reason_codes": ["TRANSACTION_PATH_UNSAFE"]}
            if target.exists() or target.is_symlink() or _hash_bytes(after) != inputs["after_sha256"] or plan["exact_diff"] != expected_diff:
                return {"ok": False, "reason_codes": ["STALE_TARGET_OR_DIFF"]}
            transaction_id = secrets.token_hex(12)
            directory = self.transactions / transaction_id
            backup = {"schema_version": 1, "transaction_id": transaction_id, "plan_id": plan_id, "plan_sha256": plan["content_sha256"], "project_id": inputs["authority"]["project_id"], "git_head": inputs["git_head"], "target": inputs["target"], "before_sha256": None, "after_sha256": inputs["after_sha256"], "existed": False}
            backup["content_sha256"] = content_hash(backup)
            _atomic(directory / "backup-index.json", _json_bytes(backup))
            transaction = {"schema_version": 1, "transaction_id": transaction_id, "plan_id": plan_id, "plan_sha256": plan["content_sha256"], "project_id": inputs["authority"]["project_id"], "policy_sha256": inputs["authority"]["policy_sha256"], "source_receipt_hashes": inputs["source_receipt_hashes"], "status": "applying", "target": inputs["target"], "after_sha256": inputs["after_sha256"], "git_head": inputs["git_head"]}
            try:
                _atomic(target, after)
                if test_crash_after_write and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                    raise KeyboardInterrupt("injected crash after write")
                if test_fail_after_write and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                    raise OSError("injected post-write failure")
                if _hash_bytes(target.read_bytes()) != inputs["after_sha256"]:
                    raise OSError("post-write verification failed")
                transaction["status"] = "applied"
                plan["status"], plan["transaction_id"] = "applied", transaction_id
                plan["content_sha256"] = content_hash(plan)
            except OSError as error:
                if target.is_file() and not target.is_symlink() and _hash_bytes(target.read_bytes()) == inputs["after_sha256"]:
                    target.unlink()
                transaction.update(status="rolled-back", error=str(error), rollback_verified=not target.exists())
                plan["status"], plan["transaction_id"] = "failed", transaction_id
                plan["content_sha256"] = content_hash(plan)
            transaction["content_sha256"] = content_hash(transaction)
            _atomic(directory / "receipt.json", _json_bytes(transaction))
            _atomic(self.plans / f"{plan_id}.json", _json_bytes(plan))
            return {"ok": transaction["status"] == "applied", "receipt": transaction, **({} if transaction["status"] == "applied" else {"reason_codes": ["APPLY_FAILED_ROLLED_BACK"]})}
        finally:
            release_transaction_lock(lock)
