#!/usr/bin/env python3
"""Transactional restore apply orchestration and rollback recovery."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    ContextMemoryService,
    json_bytes,
    parse_time,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity import doctor as continuity_doctor
from agent_os_continuity_portability_foundation import read_regular_bounded
from agent_os_continuity_transactions import strict_document
from agent_os_paths import safe_join
from continuity_portability_restore.contracts import _PLAN_ID, _RECEIPT_DIR_AGENT_REL


class RestoreApplyOrchestrationMixin:
    """Apply an admitted restore while preserving transactional recovery."""

    def apply_restore(
        self,
        plan_id: str,
        confirm: bool,
        *,
        test_fail_after: int = 0,
        test_fail_stage: str | None = None,
        test_fail_receipt_cleanup: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            return {
                "ok": False,
                "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"],
            }
        if _PLAN_ID.fullmatch(plan_id or "") is None:
            return {"ok": False, "reason_codes": ["PORTABILITY__PLAN_ID_INVALID"]}
        acquired, lock_error = self.acquire_domain_locks()
        if acquired is None:
            return {
                "ok": False,
                "reason_codes": [lock_error or "PORTABILITY_TRANSACTION_BUSY"],
            }
        backup_index: dict[str, Any] | None = None
        receipt_path: Path | None = None
        receipt_relative: str | None = None
        prepared_receipt_content: bytes | None = None
        final_receipt_content: bytes | None = None
        plan: dict[str, Any] | None = None
        plan_relative = f"_runtime/continuity-portability/plans/{plan_id}.json"
        plan_root = self.verified_owned_directory(
            "_runtime/continuity-portability/plans",
            create=False,
        )
        if plan_root is None:
            self.release_domain_locks(acquired)
            return {"ok": False, "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"]}
        plan_path = plan_root / f"{plan_id}.json"  # noqa: F841
        writes_started = False
        try:
            policy, policy_errors = self.policy()
            if policy is None:
                return {"ok": False, "reason_codes": policy_errors}
            content, _plan_error = self._read_scoped_regular(
                self.root,
                plan_relative,
                policy["bounds"]["max_manifest_bytes"] * 2,
            )
            if content is None:
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_NOT_FOUND_OR_TAMPERED"],
                }
            try:
                loaded = strict_document(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_NOT_FOUND_OR_TAMPERED"],
                }
            if (
                not isinstance(loaded, dict)
                or loaded.get("status") != "pending-approval"
            ):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_NOT_PENDING"],
                }
            plan = loaded
            errors = self.validate_restore_plan(plan, plan_id)
            if errors:
                return {"ok": False, "reason_codes": errors}
            if self.now() > parse_time(plan["expires_at"]):
                return {"ok": False, "reason_codes": ["PORTABILITY_PLAN_EXPIRED"]}
            contracts = self.contract_hashes()
            if (
                self.head() != plan["git_head"]
                or self.binding().get("project_id") != plan["project_id"]
                or contracts is None
                or any(contracts[field] != plan[field] for field in contracts)
            ):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_ENVIRONMENT_DRIFT"],
                }
            staged_path = self.agent_path(plan["bundle"]["staged_path"])
            inspected = self.inspect_bundle(staged_path)
            if not inspected.get("ok"):
                return inspected
            manifest = inspected["manifest"]
            compatibility = self.restore_compatibility(manifest)
            if compatibility:
                return {
                    "ok": False,
                    "reason_codes": list(
                        dict.fromkeys(item["code"] for item in compatibility)
                    ),
                    "issues": compatibility,
                }
            backup_index, backup_errors = self.create_restore_backup(plan)
            if backup_index is None:
                return {"ok": False, "reason_codes": backup_errors}
            entry_by_id = {entry["entry_id"]: entry for entry in manifest["entries"]}
            target_by_id = {target["entry_id"]: target for target in plan["targets"]}
            for index, entry_id in enumerate(plan["target_execution_order"], start=1):
                target = target_by_id[entry_id]
                entry = entry_by_id[entry_id]
                payload, _payload_error = read_regular_bounded(
                    safe_join(
                        staged_path,
                        entry["storage_path"],
                        canonical=True,
                    ),
                    target["bytes"],
                )
                if (
                    payload is None
                    or len(payload) != target["bytes"]
                    or sha256_bytes(payload) != target["after_sha256"]
                ):
                    raise RuntimeError("staged restore payload drift")
                self._atomic_scoped_bytes(
                    self.project_root,
                    target["path"],
                    payload,
                    create_parents=False,
                    expected_before_sha256=target["before_sha256"],
                )
                writes_started = True
                if (
                    test_fail_after == index
                    and os.environ.get("AGENT_OS_TEST_MODE") == "1"
                ):
                    raise RuntimeError(f"injected restore failure after write {index}")
            for target in plan["targets"]:
                payload, _payload_error = self._read_scoped_regular(
                    self.project_root,
                    target["path"],
                    target["bytes"],
                )
                if (
                    payload is None
                    or len(payload) != target["bytes"]
                    or sha256_bytes(payload) != target["after_sha256"]
                ):
                    raise RuntimeError("post-restore byte verification failed")
            context_health = ContextMemoryService(self.root, now=self.now).doctor()
            continuity_health = continuity_doctor(self.root)
            required_unavailable = [
                item
                for item in continuity_health.get("references", [])
                if item.get("lifecycle") == "active"
                and item.get("requirement") == "required"
                and item.get("readiness") != "available"
            ]
            if (
                context_health.get("state") != "FRESH"
                or continuity_health.get("topology_state") != "complete"
                or continuity_health.get("authority_state")
                not in {"available", "partial"}
                or required_unavailable
            ):
                raise RuntimeError("post-restore authority doctors failed")
            receipt = self.build_restore_receipt(
                plan,
                manifest,
                backup_index,
                context_health,
                continuity_health,
            )
            receipt_root = self.verified_owned_directory(
                _RECEIPT_DIR_AGENT_REL,
                create=True,
            )
            if receipt_root is None:
                raise RuntimeError("unsafe portability receipt root")
            receipt_path = receipt_root / f"{receipt['receipt_id']}.json"
            receipt_relative = f"{_RECEIPT_DIR_AGENT_REL}/{receipt['receipt_id']}.json"
            prepared_receipt = deepcopy(receipt)
            prepared_receipt["status"] = "prepared"
            prepared_receipt["content_sha256"] = receipt_hash(prepared_receipt)
            prepared_receipt_content = json_bytes(prepared_receipt)
            final_receipt_content = json_bytes(receipt)
            self._atomic_scoped_bytes(
                self.root,
                receipt_relative,
                prepared_receipt_content,
                create_parents=True,
            )
            if (
                test_fail_stage == "after-receipt"
                and os.environ.get("AGENT_OS_TEST_MODE") == "1"
            ):
                raise RuntimeError("injected restore failure after receipt")
            plan["status"] = "applied"
            plan["content_sha256"] = receipt_hash(plan)
            self._atomic_scoped_bytes(
                self.root,
                plan_relative,
                json_bytes(plan),
            )
            self._commit_scoped_bytes(
                self.root,
                receipt_relative,
                final_receipt_content,
            )
            return {
                "ok": True,
                "receipt": receipt,
                "context_health": context_health,
                "continuity_health": continuity_health,
            }
        except Exception as exc:  # noqa: BLE001
            receipt_removed = True
            if (
                receipt_path is not None
                and receipt_relative is not None
                and prepared_receipt_content is not None
            ):
                try:
                    current_receipt, _receipt_error = self._read_scoped_regular(
                        self.root,
                        receipt_relative,
                        max(
                            len(prepared_receipt_content),
                            len(final_receipt_content or b""),
                        ),
                    )
                    if _receipt_error == "PORTABILITY_FILE_NOT_FOUND":
                        receipt_removed = True
                    elif current_receipt is None:  # noqa: SIM114
                        receipt_removed = False
                    elif current_receipt != prepared_receipt_content:  # noqa: SIM114
                        receipt_removed = False
                    elif (
                        test_fail_receipt_cleanup
                        and os.environ.get("AGENT_OS_TEST_MODE") == "1"
                    ):
                        receipt_removed = False
                    else:
                        receipt_removed = self._unlink_scoped_file(
                            self.root,
                            receipt_relative,
                            expected_before_sha256=sha256_bytes(
                                prepared_receipt_content
                            ),
                        )
                except (OSError, ValueError):
                    receipt_removed = False
            bytes_restored = (
                backup_index is not None
                and plan is not None
                and self.restore_backup(plan, backup_index)
            )
            plan_failed_recorded = plan is None
            if plan is not None:
                plan["status"] = "failed"
                plan["content_sha256"] = receipt_hash(plan)
                failed_content = json_bytes(plan)
                try:
                    self._atomic_scoped_bytes(
                        self.root,
                        plan_relative,
                        failed_content,
                    )
                    persisted, _persist_error = self._read_scoped_regular(
                        self.root,
                        plan_relative,
                        len(failed_content),
                    )
                    plan_failed_recorded = persisted == failed_content
                except (OSError, ValueError):
                    plan_failed_recorded = False
            rollback_verified = (
                receipt_removed and bytes_restored and plan_failed_recorded
            )
            reason_code = (
                "PORTABILITY_RESTORE_FAILED_ROLLED_BACK"
                if rollback_verified
                else "PORTABILITY_RESTORE_ROLLBACK_INCOMPLETE"
            )
            return {
                "ok": False,
                "reason_codes": [reason_code],
                "rollback_verified": rollback_verified,
                "writes_started": writes_started,
                "false_receipt_removed": (receipt_removed),
                "failed_plan_recorded": plan_failed_recorded,
                "error": str(exc)[:480],
            }
        finally:
            self.release_domain_locks(acquired)
