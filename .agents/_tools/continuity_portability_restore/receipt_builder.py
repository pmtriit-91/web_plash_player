#!/usr/bin/env python3
"""Deterministic durable restore-receipt construction."""

from __future__ import annotations

from typing import Any

from agent_os_context_memory import (
    canonical_hash,
    iso_time,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity_portability_foundation import (
    RESTORE_BACKUP_DIR_AGENT_REL,
    artifact_id,
)


class RestoreReceiptBuilderMixin:
    """Build the stable receipt shape without owning apply orchestration."""

    def build_restore_receipt(
        self,
        plan: dict[str, Any],
        manifest: dict[str, Any],
        backup_index: dict[str, Any],
        context_health: dict[str, Any],
        continuity_health: dict[str, Any],
    ) -> dict[str, Any]:
        targets = [
            {
                key: target[key]
                for key in (
                    "entry_id",
                    "path",
                    "action",
                    "before_sha256",
                    "after_sha256",
                    "bytes",
                )
            }
            for target in plan["targets"]
        ]
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "receipt_id": "",
            "plan_id": plan["plan_id"],
            "operation": "restore",
            "status": "applied",
            "project_id": plan["project_id"],
            "base_commit": plan["git_head"],
            "applied_at": iso_time(self.now()),
            "binding_sha256": plan["binding_sha256"],
            "adapter_fingerprint_sha256": plan["adapter_fingerprint_sha256"],
            "core_manifest_sha256": plan["core_manifest_sha256"],
            "record_type_registry_sha256": plan["record_type_registry_sha256"],
            "recovery_profile_sha256": plan["recovery_profile_sha256"],
            "retention_policy_sha256": plan["retention_policy_sha256"],
            "bundle": {
                "bundle_id": manifest["bundle_id"],
                "manifest_sha256": plan["bundle"]["manifest_sha256"],
                "inventory_sha256": manifest["inventory_sha256"],
            },
            "targets": targets,
            "target_inventory_sha256": canonical_hash(targets),
            "target_execution_order": list(plan["target_execution_order"]),
            "backup": {
                "backup_id": plan["backup_id"],
                "index_path": (
                    f".agents/{RESTORE_BACKUP_DIR_AGENT_REL}/"
                    f"{plan['backup_id']}/index.json"
                ),
                "index_sha256": sha256_bytes(json_bytes(backup_index)),
            },
            "post_apply": {
                "context_memory_state": context_health["state"],
                "continuity_topology_state": continuity_health["topology_state"],
                "continuity_authority_state": continuity_health["authority_state"],
                "reason_codes": continuity_health.get("reason_codes", []),
            },
            "backup_verified": True,
            "rollback_ready": True,
            "source_deleted": False,
            "core_overwritten": False,
            "owner_confirmation_performed": False,
            "raw_conversation_stored": False,
            "prompt_stored": False,
            "chain_of_thought_stored": False,
            "secret_stored": False,
            "commit_created": False,
            "push_performed": False,
        }
        receipt["receipt_id"] = artifact_id(
            receipt,
            "continuity-restore-",
            "receipt_id",
        )
        receipt["content_sha256"] = receipt_hash(receipt)
        return receipt
