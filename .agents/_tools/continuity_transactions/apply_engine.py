from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    atomic_bytes,
    decoded,
    iso_time,
    json_bytes,
    parse_time,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity import doctor, load_json
from agent_os_transaction_lock import (
    TransactionLockError,
    TransactionLockHandle,
    acquire_transaction_lock,
    release_transaction_lock,
)
from continuity_transactions.contracts import (
    CATALOG_REL,
    PLAN_ID,
    TRANSACTION_DIR_REL,
    TRANSACTION_ID,
)


# fmt: off
class ApplyEngineMixin:
    def acquire_lock(self) -> TransactionLockHandle:
        self.runtime.mkdir(parents=True, exist_ok=True)
        return acquire_transaction_lock(self.lock_path, "continuity-apply")

    def release_lock(self, handle: TransactionLockHandle) -> None:
        release_transaction_lock(handle)

    def verify_change_hashes(self, changes: list[dict[str, Any]], *, after: bool) -> bool:
        field = "after_sha256" if after else "before_sha256"
        for change in changes:
            content = self.target_bytes(str(change.get("path")))
            actual = sha256_bytes(content) if content is not None else None
            if actual != change.get(field):
                return False
        return True

    def restore_changes(self, changes: list[dict[str, Any]]) -> bool:
        ok = True
        for change in reversed(changes):
            path = self.path(str(change["path"]))
            content = decoded(change.get("before_base64"))
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, content)
            except OSError:
                ok = False
        return ok and self.verify_change_hashes(changes, after=False)

    def apply(
        self,
        plan_id: str,
        confirm: bool,
        *,
        test_fail_after: int = 0,
    ) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        if not PLAN_ID.fullmatch(plan_id or ""):
            return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_ID_INVALID"]}
        try:
            lock = self.acquire_lock()
        except TransactionLockError as error:
            reason_codes = [error.reason_code]
            if error.reason_code == "TRANSACTION_LOCK_BUSY":
                reason_codes.insert(0, "CONTINUITY_TRANSACTION_BUSY")
            return {"ok": False, "reason_codes": reason_codes}
        try:
            plan_path = self.plans / f"{plan_id}.json"
            try:
                plan = load_json(plan_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                plan = None
            validation_errors = self.validate_plan(plan, plan_id)
            if validation_errors:
                return {"ok": False, "reason_codes": validation_errors}
            try:
                expired = self.now() > parse_time(str(plan.get("expires_at")))
            except ValueError:
                expired = True
            if expired:
                return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_EXPIRED"]}
            if self.head() != plan.get("git_head"):
                return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_STALE_HEAD"]}
            contracts = self.contract_hashes()
            contract_fields = (
                "binding_sha256",
                "adapter_fingerprint_sha256",
                "core_manifest_sha256",
                "record_type_registry_sha256",
                "recovery_profile_sha256",
                "migration_registry_sha256",
            )
            if contracts is None or any(contracts.get(field) != plan.get(field) for field in contract_fields):
                return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_CORE_OR_BINDING_DRIFT"]}
            inventory_paths = {
                str(item.get("path"))
                for item in plan.get("source_inventory", [])
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            _inventory, inventory_hash = self.source_inventory(inventory_paths)
            if inventory_hash != plan.get("source_inventory_sha256"):
                return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_SOURCE_DRIFT"]}
            changes = plan.get("changes") if isinstance(plan.get("changes"), list) else []
            if not changes or not self.verify_change_hashes(changes, after=False):
                return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_TARGET_DRIFT"]}
            backup, backup_errors = self.create_backup(plan)
            if backup_errors or backup is None:
                return {"ok": False, "reason_codes": backup_errors}
            receipt_path: Path | None = None
            receipt_created = False
            try:
                ordered = sorted(changes, key=lambda item: item.get("path") == CATALOG_REL)
                for index, change in enumerate(ordered, start=1):
                    path = self.path(str(change["path"]))
                    content = decoded(change.get("after_base64"))
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_bytes(path, content)
                    injected = test_fail_after or int(os.environ.get("AGENT_OS_CONTINUITY_FAIL_AFTER", "0"))
                    if os.environ.get("AGENT_OS_TEST_MODE") == "1" and injected == index:
                        raise RuntimeError(f"injected continuity failure after write {index}")
                if not self.verify_change_hashes(changes, after=True):
                    raise RuntimeError("post-apply byte verification failed")
                metadata = plan.get("metadata", {})
                health = doctor(self.root)
                migration_required_predecessor = (
                    plan["operation"] == "rollback"
                    and metadata.get("source_generation") == 2
                    and metadata.get("target_generation") == 1
                    and health.get("state") == "MIGRATION_REQUIRED"
                    and health.get("topology_state") == "migration-required"
                    and health.get("authority_state") == "unavailable"
                    and health.get("reason_codes") == ["CONTINUITY_MIGRATION_REQUIRED"]
                    and health.get("errors") == [{
                        "code": "CONTINUITY_MIGRATION_REQUIRED",
                        "source_generation": 1,
                        "target_generation": 2,
                    }]
                )
                if plan["operation"] == "rollback" and self.target_bytes(CATALOG_REL) is None:
                    if health.get("state") != "UNCONFIGURED":
                        raise RuntimeError("rollback did not restore unconfigured state")
                elif health.get("topology_state") != "complete" and not migration_required_predecessor:
                    raise RuntimeError("post-apply continuity doctor failed")
                transaction_id = str(metadata.get("transaction_id", ""))
                if not TRANSACTION_ID.fullmatch(transaction_id):
                    raise RuntimeError("transaction id invalid")
                after_catalog = self.target_bytes(CATALOG_REL)
                receipt = {
                    "schema_version": 1,
                    "transaction_id": transaction_id,
                    "operation": plan["operation"],
                    "status": "applied",
                    "project_id": plan["project_id"],
                    "base_commit": plan["git_head"],
                    "applied_at": iso_time(self.now()),
                    "source_generation": metadata.get("source_generation"),
                    "target_generation": metadata.get("target_generation"),
                    "binding_sha256": plan["binding_sha256"],
                    "adapter_fingerprint_sha256": plan["adapter_fingerprint_sha256"],
                    "record_type_registry_sha256": plan["record_type_registry_sha256"],
                    "recovery_profile_sha256": plan["recovery_profile_sha256"],
                    "migration_registry_sha256": plan["migration_registry_sha256"],
                    "before_catalog_sha256": next(
                        (item.get("before_sha256") for item in changes if item.get("path") == CATALOG_REL),
                        sha256_bytes(after_catalog) if after_catalog is not None else None,
                    ),
                    "after_catalog_sha256": sha256_bytes(after_catalog) if after_catalog is not None else None,
                    "source_inventory_sha256": plan["source_inventory_sha256"],
                    "critical_set_before": metadata.get("critical_set_before", []),
                    "critical_set_after": metadata.get("critical_set_after", []),
                    "unknown_fields_sha256": metadata.get("unknown_fields_sha256"),
                    "backup": backup,
                    "semantic_completeness": {
                        "topology_state": health.get("topology_state", "unconfigured"),
                        "authority_state": health.get("authority_state", "unavailable"),
                        "reason_codes": list(dict.fromkeys(health.get("reason_codes", []))),
                    },
                    "rollback_verified": self.backup_contents(backup["backup_id"])[0] is not None,
                    "source_deleted": False,
                    "owner_confirmation_performed": False,
                    "raw_conversation_stored": False,
                    "commit_created": False,
                    "push_performed": False,
                }
                if plan["operation"] == "migrate" and metadata["target_generation"] == 2:
                    receipt["migration_path"] = metadata["migration_path"]
                    receipt["migration_path_sha256"] = metadata[
                        "migration_path_sha256"
                    ]
                receipt["content_sha256"] = receipt_hash(receipt)
                receipt_path = self.path(f"{TRANSACTION_DIR_REL}/{transaction_id}.json")
                if receipt_path.exists():
                    raise RuntimeError("transaction receipt already exists")
                atomic_bytes(receipt_path, json_bytes(receipt))
                receipt_created = True
                injected = test_fail_after or int(
                    os.environ.get("AGENT_OS_CONTINUITY_FAIL_AFTER", "0")
                )
                if (
                    os.environ.get("AGENT_OS_TEST_MODE") == "1"
                    and injected == len(ordered) + 1
                ):
                    raise RuntimeError("injected continuity failure after receipt write")
                verified_receipt, receipt_errors = self.transaction_receipt(transaction_id)
                if receipt_errors or verified_receipt is None:
                    raise RuntimeError("transaction receipt verification failed")
                plan["status"] = "applied"
                plan["content_sha256"] = receipt_hash(plan)
                atomic_bytes(plan_path, json_bytes(plan))
                return {
                    "ok": True,
                    "receipt": receipt,
                    "health": health,
                    "backup": backup,
                }
            except Exception as exc:  # noqa: BLE001 - transaction rollback boundary
                rollback_verified = self.restore_changes(changes)
                receipt_cleanup_verified = True
                if receipt_created and receipt_path is not None:
                    try:
                        receipt_path.unlink()
                        receipt_cleanup_verified = not receipt_path.exists()
                    except OSError:
                        receipt_cleanup_verified = False
                plan["status"] = "failed"
                plan["content_sha256"] = receipt_hash(plan)
                plan_failure_recorded = True
                try:
                    atomic_bytes(plan_path, json_bytes(plan))
                except OSError:
                    plan_failure_recorded = False
                recovery_complete = (
                    rollback_verified
                    and receipt_cleanup_verified
                    and plan_failure_recorded
                )
                return {
                    "ok": False,
                    "reason_codes": [
                        (
                            "CONTINUITY_APPLY_FAILED_ROLLED_BACK"
                            if recovery_complete
                            else "CONTINUITY_APPLY_FAILED_RECOVERY_INCOMPLETE"
                        )
                    ],
                    "error": str(exc)[:240],
                    "rollback_verified": rollback_verified,
                    "receipt_cleanup_verified": receipt_cleanup_verified,
                    "plan_failure_recorded": plan_failure_recorded,
                    "backup": backup,
                }
        finally:
            self.release_lock(lock)

    def list_transactions(self) -> dict[str, Any]:
        directory = self.path(TRANSACTION_DIR_REL)
        receipts: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if directory.is_dir() and not directory.is_symlink():
            for path in sorted(directory.glob("continuity-tx-*.json")):
                receipt, receipt_errors = self.transaction_receipt(path.stem)
                if receipt is not None:
                    receipts.append(receipt)
                else:
                    errors.append({"transaction_id": path.stem, "code": receipt_errors[0]})
        return {
            "ok": not errors,
            "transactions": receipts,
            "errors": errors,
            "raw_conversation_stored": False,
        }
