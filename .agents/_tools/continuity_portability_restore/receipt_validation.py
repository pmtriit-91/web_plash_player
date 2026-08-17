#!/usr/bin/env python3
"""Bounded durable restore-receipt validation for continuity portability."""

from __future__ import annotations

import json
from typing import Any

from agent_os_context_memory import (
    canonical_hash,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity_portability_export import BUNDLE_ID, ENTRY_ID
from agent_os_continuity_portability_foundation import (
    FULL_COMMIT,
    RESTORE_BACKUP_DIR_AGENT_REL,
    artifact_id,
    read_regular_bounded,
)
from agent_os_continuity_transactions import strict_document
from agent_os_paths import portable_relative
from continuity_portability_restore.backup_validation import (
    RestoreBackupValidationMixin,
)
from continuity_portability_restore.contracts import (
    _PLAN_ID,
    BACKUP_ID,
    RESTORE_RECEIPT_FIELDS,
    RESTORE_RECEIPT_ID,
    RESTORE_TARGET_FIELDS,
    _has_portable_path_collision,
    _valid_hash,
    _valid_time,
)


class RestoreReceiptValidationMixin(RestoreBackupValidationMixin):
    def validate_restore_receipt(self, receipt: Any) -> list[str]:
        policy, policy_errors = self.policy()
        if policy is None:
            return policy_errors
        if not isinstance(receipt, dict) or set(receipt) != RESTORE_RECEIPT_FIELDS:
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        try:
            receipt_bytes = json_bytes(receipt)
            expected_id = artifact_id(
                receipt,
                "continuity-restore-",
                "receipt_id",
            )
            content_hash_valid = receipt.get("content_sha256") == receipt_hash(receipt)
        except (TypeError, ValueError):
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        if (
            len(receipt_bytes) > policy["bounds"]["max_manifest_bytes"] * 2
            or receipt.get("schema_version") != 1
            or receipt.get("receipt_id") != expected_id
            or RESTORE_RECEIPT_ID.fullmatch(str(receipt.get("receipt_id", ""))) is None
            or _PLAN_ID.fullmatch(str(receipt.get("plan_id", ""))) is None
            or receipt.get("operation") != "restore"
            or receipt.get("status") != "applied"
            or not isinstance(receipt.get("project_id"), str)
            or not 1 <= len(receipt["project_id"]) <= 128
            or FULL_COMMIT.fullmatch(str(receipt.get("base_commit", ""))) is None
            or not _valid_time(receipt.get("applied_at"))
            or any(
                not _valid_hash(receipt.get(field))
                for field in (
                    "binding_sha256",
                    "adapter_fingerprint_sha256",
                    "core_manifest_sha256",
                    "record_type_registry_sha256",
                    "recovery_profile_sha256",
                    "retention_policy_sha256",
                    "target_inventory_sha256",
                )
            )
            or receipt.get("backup_verified") is not True
            or receipt.get("rollback_ready") is not True
            or any(
                receipt.get(field) is not False
                for field in (
                    "source_deleted",
                    "core_overwritten",
                    "owner_confirmation_performed",
                    "raw_conversation_stored",
                    "prompt_stored",
                    "chain_of_thought_stored",
                    "secret_stored",
                    "commit_created",
                    "push_performed",
                )
            )
            or not content_hash_valid
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        contract_fields = (
            "binding_sha256",
            "adapter_fingerprint_sha256",
            "core_manifest_sha256",
            "record_type_registry_sha256",
            "recovery_profile_sha256",
            "retention_policy_sha256",
        )
        if not self.validate_git_contract_provenance(
            receipt["base_commit"],
            receipt["project_id"],
            {field: receipt[field] for field in contract_fields},
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_PROVENANCE_UNVERIFIABLE"]
        bundle = receipt.get("bundle")
        backup = receipt.get("backup")
        post_apply = receipt.get("post_apply")
        reason_codes = (
            post_apply.get("reason_codes") if isinstance(post_apply, dict) else None
        )
        if (
            not isinstance(bundle, dict)
            or set(bundle) != {"bundle_id", "manifest_sha256", "inventory_sha256"}
            or BUNDLE_ID.fullmatch(str(bundle.get("bundle_id", ""))) is None
            or not _valid_hash(bundle.get("manifest_sha256"))
            or not _valid_hash(bundle.get("inventory_sha256"))
            or not isinstance(backup, dict)
            or set(backup) != {"backup_id", "index_path", "index_sha256"}
            or BACKUP_ID.fullmatch(str(backup.get("backup_id", ""))) is None
            or backup.get("index_path")
            != (
                f".agents/{RESTORE_BACKUP_DIR_AGENT_REL}/"
                f"{backup.get('backup_id')}/index.json"
            )
            or not _valid_hash(backup.get("index_sha256"))
            or not isinstance(post_apply, dict)
            or set(post_apply)
            != {
                "context_memory_state",
                "continuity_topology_state",
                "continuity_authority_state",
                "reason_codes",
            }
            or post_apply.get("context_memory_state") != "FRESH"
            or post_apply.get("continuity_topology_state") != "complete"
            or post_apply.get("continuity_authority_state")
            not in {"available", "partial"}
            or not isinstance(reason_codes, list)
            or len(reason_codes) > policy["bounds"]["max_entries"]
            or len(reason_codes) != len(set(reason_codes))
            or any(
                not isinstance(code, str) or not 1 <= len(code) <= 128
                for code in reason_codes
            )
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        targets = receipt.get("targets")
        receipt_target_fields = RESTORE_TARGET_FIELDS - {"backup_required"}
        if (
            not isinstance(targets, list)
            or not 1 <= len(targets) <= policy["bounds"]["max_entries"]
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        if _has_portable_path_collision(targets):
            return ["PORTABILITY_RESTORE_RECEIPT_TARGET_PATH_COLLISION"]
        paths: list[str] = []
        total_bytes = 0
        for target in targets:
            if not isinstance(target, dict):
                return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
            try:
                canonical_target = portable_relative(
                    str(target.get("path", "")),
                    canonical=True,
                )
            except ValueError:
                return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
            if (
                not isinstance(target, dict)
                or set(target) != receipt_target_fields
                or ENTRY_ID.fullmatch(str(target.get("entry_id", ""))) is None
                or not isinstance(target.get("path"), str)
                or not 1 <= len(target["path"]) <= 512
                or canonical_target != target.get("path")
                or self.derived_owner_mode(canonical_target)
                != ("application", "replace")
                or target["path"] in paths
                or target.get("action")
                != ("create" if target.get("before_sha256") is None else "replace")
                or not _valid_hash(target.get("before_sha256"), nullable=True)
                or not _valid_hash(target.get("after_sha256"))
                or type(target.get("bytes")) is not int
                or not 0 <= target["bytes"] <= policy["bounds"]["max_file_bytes"]
            ):
                return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
            paths.append(target["path"])
            total_bytes += target["bytes"]
        if (
            paths != sorted(paths)
            or receipt.get("target_inventory_sha256") != canonical_hash(targets)
            or total_bytes > policy["bounds"]["max_total_bytes"]
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        target_ids = [target["entry_id"] for target in targets]
        execution_order = receipt.get("target_execution_order")
        if (
            not isinstance(execution_order, list)
            or len(execution_order) != len(target_ids)
            or any(
                not isinstance(entry_id, str) or ENTRY_ID.fullmatch(entry_id) is None
                for entry_id in execution_order
            )
            or len(execution_order) != len(set(execution_order))
            or set(execution_order) != set(target_ids)
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_INVALID"]
        try:
            index_path = self.project_path(backup["index_path"])
            backup_path = index_path.parent
        except ValueError:
            return ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
        backup_root = self.verified_restore_backup_root()
        if (
            backup_root is None
            or backup_path.parent != backup_root
            or backup_path.name != backup["backup_id"]
            or self._safe_directory_stat(backup_path) is None
            or not backup_path.is_dir()
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
        raw_index, index_error = read_regular_bounded(
            index_path,
            policy["bounds"]["max_manifest_bytes"],
        )
        if (
            raw_index is None
            or index_error is not None
            or sha256_bytes(raw_index) != backup["index_sha256"]
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
        try:
            index = strict_document(raw_index)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
        plan_targets = [{**target, "backup_required": True} for target in targets]
        plan_reference = {
            "backup_id": backup["backup_id"],
            "plan_id": receipt["plan_id"],
            "project_id": receipt["project_id"],
            "targets": plan_targets,
        }
        if self.validate_restore_backup_index(
            index,
            plan_reference,
            backup_path,
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
        indexed_by_id = {item["entry_id"]: item for item in index["files"]}
        if any(
            indexed_by_id.get(target["entry_id"], {}).get("sha256")
            != target["before_sha256"]
            or indexed_by_id.get(target["entry_id"], {}).get("present")
            is (target["before_sha256"] is None)
            for target in targets
        ):
            return ["PORTABILITY_RESTORE_RECEIPT_BACKUP_UNVERIFIABLE"]
        return []
