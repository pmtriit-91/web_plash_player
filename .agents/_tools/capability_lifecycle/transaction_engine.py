"""Capability lifecycle transaction, recovery, and rollback contracts."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

from capability_lifecycle.platform_privacy import PLAN_ID
from capability_lifecycle.shared import (
    CAPABILITY_DECISIONS,
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    MANIFEST,
    ROUTING_CORPUS,
    atomic_bytes,
    atomic_json,
    canonical_hash,
    decoded,
    iso_time,
    json_bytes,
    load_json,
    parse_time,
    receipt_hash,
    receipt_valid,
    sha256_bytes,
)
from capability_lifecycle.state_planning import StatePlanningMixin


# fmt: off
class TransactionEngineMixin(StatePlanningMixin):
    def acquire_lock(self) -> int | None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        try:
            return os.open(self.runtime / "apply.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None

    def release_lock(self, descriptor: int) -> None:
        os.close(descriptor)
        try:
            (self.runtime / "apply.lock").unlink()
        except FileNotFoundError:
            pass

    def restore_changes(self, changes: list[dict[str, Any]], use_before: bool) -> bool:
        success = True
        ordered = list(reversed(changes)) if use_before else sorted(changes, key=lambda item: item.get("path") == MANIFEST)
        for item in ordered:
            path = self.path(item["path"])
            content = decoded(item["before_base64"] if use_before else item["after_base64"])
            try:
                if content is None:
                    if path.exists() or path.is_symlink():
                        path.unlink()
                else:
                    atomic_bytes(path, content)
            except OSError:
                success = False
        return success

    def write_after_changes(self, changes: list[dict[str, Any]], fail_after: int = 0, crash_after: int = 0) -> None:
        ordered = sorted(changes, key=lambda item: item.get("path") == MANIFEST)
        for index, item in enumerate(ordered, start=1):
            path = self.path(item["path"])
            content = decoded(item.get("after_base64"))
            if content is None:
                if path.exists() or path.is_symlink():
                    path.unlink()
            else:
                atomic_bytes(path, content)
            if fail_after == index and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                raise RuntimeError(f"injected failure after write {index}")
            if crash_after == index and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                raise KeyboardInterrupt(f"injected interruption after write {index}")

    def verify_changes(self, changes: list[dict[str, Any]], after: bool) -> bool:
        field = "after_sha256" if after else "before_sha256"
        for item in changes:
            content = self.read_bytes(item["path"])
            actual = sha256_bytes(content) if content is not None else None
            if actual != item.get(field):
                return False
        return True

    def apply(self, plan_id: str, confirm: bool, test_fail_after_write: bool = False, expected_operations: set[str] | None = None, test_crash_after_write: int = 0) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        if not PLAN_ID.fullmatch(plan_id or ""):
            return {"ok": False, "reason_codes": ["PLAN_ID_INVALID"]}
        lock = self.acquire_lock()
        if lock is None:
            return {"ok": False, "reason_codes": ["TRANSACTION_BUSY"]}
        try:
            if self.journal.is_file():
                return {"ok": False, "reason_codes": ["RECOVERY_REQUIRED"]}
            plan_path = self.plans / f"{plan_id}.json"
            plan = load_json(plan_path, None)
            if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
                return {"ok": False, "reason_codes": ["PLAN_NOT_FOUND"]}
            if plan.get("status") != "pending-approval":
                return {"ok": False, "reason_codes": ["PLAN_NOT_PENDING"]}
            inputs = plan.get("input") if isinstance(plan.get("input"), dict) else {}
            if canonical_hash(inputs)[:24] != plan_id:
                return {"ok": False, "reason_codes": ["PLAN_INTEGRITY_FAILED"]}
            if expected_operations is not None and inputs.get("operation") not in expected_operations:
                return {"ok": False, "reason_codes": ["PLAN_OPERATION_MISMATCH"], "operation": inputs.get("operation")}
            if self.now() > parse_time(str(inputs.get("expires_at"))):
                return {"ok": False, "reason_codes": ["PLAN_EXPIRED"]}
            if self.git("rev-parse", "HEAD") != inputs.get("git_head"):
                return {"ok": False, "reason_codes": ["STALE_GIT_HEAD"]}
            if self.protected_digest() != inputs.get("protected_digest"):
                return {"ok": False, "reason_codes": ["PROTECTED_SCOPE_CHANGED"]}
            for relative, expected in (inputs.get("guard_hashes") or {}).items():
                if sha256_bytes(self.read_bytes(str(relative)) or b"") != expected:
                    return {"ok": False, "reason_codes": ["STALE_POLICY_OR_EVAL_HASH"], "path": relative}
            changes = inputs.get("changes") if isinstance(inputs.get("changes"), list) else []
            if not changes or not self.verify_changes(changes, after=False):
                return {"ok": False, "reason_codes": ["STALE_TARGET_HASH"]}
            expected_diff = "".join(
                self.diff_for(decoded(item.get("before_base64")), decoded(item.get("after_base64")), item["path"])
                for item in changes
            )
            if plan.get("exact_diff") != expected_diff:
                return {"ok": False, "reason_codes": ["PLAN_DISPLAY_DIFF_INVALID"]}
            transaction_id = canonical_hash({"plan": plan_id, "at": iso_time(self.now()), "nonce": os.urandom(16).hex()})[:24]
            receipt = {
                "schema_version": 1,
                "transaction_id": transaction_id,
                "plan_id": plan_id,
                "operation": inputs.get("operation"),
                "status": "applying",
                "git_head": inputs.get("git_head"),
                "protected_digest": inputs.get("protected_digest"),
                "changes": changes,
                "applied_at": iso_time(self.now()),
                "manifest_refresh_required": True,
                "commit_created": False,
                "push_performed": False,
                "candidate_id": inputs.get("candidate_id"),
                "capability_id": inputs.get("capability_id"),
                "runtime_candidate": inputs.get("runtime_candidate"),
            }
            journal = {
                "schema_version": 1,
                "plan_id": plan_id,
                "transaction_id": transaction_id,
                "git_head": inputs.get("git_head"),
                "protected_digest": inputs.get("protected_digest"),
                "changes": changes,
                "started_at": iso_time(self.now()),
            }
            journal["content_sha256"] = receipt_hash(journal)
            atomic_json(self.journal, journal)
            try:
                failure_boundary = int(test_fail_after_write) if test_fail_after_write else 0
                self.write_after_changes(changes, failure_boundary, test_crash_after_write)
                if (
                    not self.verify_changes(changes, after=True)
                    or self.protected_digest() != inputs.get("protected_digest")
                    or not self.verify_working_manifest()
                ):
                    raise RuntimeError("post-apply byte verification failed")
                runtime_candidate = inputs.get("runtime_candidate")
                runtime_decision = inputs.get("runtime_decision")
                if isinstance(runtime_candidate, dict):
                    self.persist_runtime_candidate(runtime_candidate)
                if isinstance(runtime_decision, dict):
                    self.persist_runtime_decision(runtime_decision)
                receipt["status"] = "applied"
                receipt["verification"] = "passed"
                receipt["content_sha256"] = receipt_hash(receipt)
                plan["status"] = "applied"
                plan["transaction_id"] = transaction_id
                atomic_json(self.receipts / f"{transaction_id}.json", receipt)
                atomic_json(plan_path, plan)
                self.journal.unlink(missing_ok=True)
                return {"ok": True, "receipt": receipt}
            except Exception as exc:  # noqa: BLE001 - rollback must catch any apply failure
                restored = self.restore_changes(changes, use_before=True)
                runtime_candidate = deepcopy(inputs.get("runtime_candidate"))
                if isinstance(runtime_candidate, dict):
                    original_history = [
                        item for item in runtime_candidate.get("decision_history", [])
                        if item.get("state") not in {"active"}
                    ]
                    if not original_history or original_history[-1].get("state") != "integrating":
                        original_history.append({"state": "integrating", "at": iso_time(self.now()), "actor": "capability-lifecycle"})
                    original_history.append({"state": "failed", "at": iso_time(self.now()), "actor": "capability-lifecycle"})
                    runtime_candidate["decision_history"] = original_history
                    runtime_candidate["state"] = "failed"
                    try:
                        self.persist_runtime_candidate(runtime_candidate)
                    except OSError:
                        pass
                receipt["status"] = "rolled-back"
                receipt["verification"] = "failed"
                receipt["error"] = str(exc)
                receipt["rollback_verified"] = restored and self.verify_changes(changes, after=False) and self.protected_digest() == inputs.get("protected_digest")
                receipt["content_sha256"] = receipt_hash(receipt)
                plan["status"] = "failed"
                plan["transaction_id"] = transaction_id
                atomic_json(self.receipts / f"{transaction_id}.json", receipt)
                atomic_json(plan_path, plan)
                if receipt["rollback_verified"]:
                    self.journal.unlink(missing_ok=True)
                return {"ok": False, "reason_codes": ["APPLY_FAILED_ROLLED_BACK"], "receipt": receipt}
        finally:
            self.release_lock(lock)

    def recover(self, confirm: bool) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        lock = self.acquire_lock()
        if lock is None:
            return {"ok": False, "reason_codes": ["TRANSACTION_BUSY"]}
        try:
            journal = load_json(self.journal, None)
            if not isinstance(journal, dict):
                return {"ok": False, "reason_codes": ["RECOVERY_JOURNAL_NOT_FOUND"]}
            if not receipt_valid(journal):
                return {"ok": False, "reason_codes": ["RECOVERY_JOURNAL_INVALID"]}
            changes = journal.get("changes") if isinstance(journal.get("changes"), list) else []
            restored = self.restore_changes(changes, use_before=True)
            verified = (
                restored
                and self.verify_changes(changes, after=False)
                and self.protected_digest() == journal.get("protected_digest")
            )
            receipt = {
                "schema_version": 1,
                "transaction_id": canonical_hash({"recovery_of": journal.get("transaction_id"), "at": iso_time(self.now())})[:24],
                "operation": "capability-crash-recovery",
                "status": "recovered" if verified else "recovery-failed",
                "recovery_of": journal.get("transaction_id"),
                "plan_id": journal.get("plan_id"),
                "recovered_at": iso_time(self.now()),
                "rollback_verified": verified,
                "commit_created": False,
                "push_performed": False,
            }
            receipt["content_sha256"] = receipt_hash(receipt)
            atomic_json(self.receipts / f"{receipt['transaction_id']}.json", receipt)
            if verified:
                self.journal.unlink(missing_ok=True)
            return {"ok": verified, "receipt": receipt, **({} if verified else {"reason_codes": ["RECOVERY_FAILED"]})}
        finally:
            self.release_lock(lock)

    def plan_rollback(self, transaction_id: str, expiry_seconds: int = 900) -> dict[str, Any]:
        receipt = load_json(self.receipts / f"{transaction_id}.json", None)
        if not isinstance(receipt, dict) or receipt.get("transaction_id") != transaction_id or receipt.get("status") != "applied" or not receipt_valid(receipt):
            return {"ok": False, "reason_codes": ["TRANSACTION_NOT_ROLLBACK_ELIGIBLE"]}
        changes = receipt.get("changes") if isinstance(receipt.get("changes"), list) else []
        if not self.verify_changes(changes, after=True):
            return {"ok": False, "reason_codes": ["ROLLBACK_TARGET_DIVERGED"]}
        desired = {
            item["path"]: decoded(item.get("before_base64"))
            for item in changes
            if item.get("path") not in {MANIFEST, CAPABILITY_DECISIONS, LIFECYCLE_LEDGER, ROUTING_CORPUS}
        }
        current_decisions = self.document(CAPABILITY_DECISIONS, {"schema_version": 1, "receipts": []})
        current_lifecycle = self.document(LIFECYCLE_LEDGER, {"schema_version": 1, "append_only": True, "receipts": []})
        current_corpus = self.document(ROUTING_CORPUS, {"schema_version": 1, "cases": []})
        runtime_candidate = deepcopy(receipt.get("runtime_candidate"))
        if isinstance(runtime_candidate, dict):
            runtime_candidate["state"] = "deprecated"
            runtime_candidate.setdefault("decision_history", []).append(
                {"state": "deprecated", "at": iso_time(self.now()), "actor": "capability-rollback"}
            )
        rollback_at = iso_time(self.now())
        previous_descriptor_bytes = desired.get(DESCRIPTORS)
        previous_descriptor_document = json.loads(previous_descriptor_bytes) if isinstance(previous_descriptor_bytes, bytes) else {"capabilities": []}
        previous_descriptor = next(
            (item for item in previous_descriptor_document.get("capabilities", []) if item.get("id") == receipt.get("capability_id")),
            {},
        )
        rollback_receipt = {
            "schema_version": 1,
            "id": f"lifecycle-{canonical_hash({'rollback_of': transaction_id, 'at': rollback_at})[:24]}",
            "candidate_id": receipt.get("candidate_id"),
            "capability_id": receipt.get("capability_id"),
            "action": "rollback",
            "state": previous_descriptor.get("lifecycle_state", "deprecated"),
            "integration_mode": previous_descriptor.get("integration_mode") or "native",
            "at": rollback_at,
            "decision_ref": previous_descriptor.get("decision_ref"),
            "source_snapshot_sha256": runtime_candidate.get("source", {}).get("snapshot_sha256") if isinstance(runtime_candidate, dict) else None,
            "eval_case_ids": previous_descriptor.get("eval", {}).get("case_ids", []),
            "rollback_of": transaction_id,
            "manifest_refresh_required": True,
            "commit_created": False,
            "push_performed": False,
        }
        rollback_receipt["content_sha256"] = receipt_hash(rollback_receipt)
        current_lifecycle.setdefault("receipts", []).append(rollback_receipt)
        desired[CAPABILITY_DECISIONS] = json_bytes(current_decisions)
        desired[LIFECYCLE_LEDGER] = json_bytes(current_lifecycle)
        desired[ROUTING_CORPUS] = json_bytes(current_corpus)
        desired[MANIFEST] = self.render_working_manifest(desired, rollback_at, f"rollback-{transaction_id}")
        return self.create_plan(
            desired,
            {
                "operation": "capability-rollback",
                "rollback_of": transaction_id,
                "candidate_id": receipt.get("candidate_id"),
                "capability_id": receipt.get("capability_id"),
                "runtime_candidate": runtime_candidate,
            },
            expiry_seconds,
            allow_dirty=True,
        )
# fmt: on
