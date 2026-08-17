#!/usr/bin/env python3
"""Shared restore field, identifier, hash, time, and collision contracts."""

from __future__ import annotations

import re
from typing import Any

from agent_os_context_memory import parse_time
from agent_os_paths import portable_collision_key

BACKUP_ID = re.compile(r"^continuity-restore-backup-[0-9a-f]{24}$")
RESTORE_RECEIPT_ID = re.compile(r"^continuity-restore-[0-9a-f]{24}$")
RESTORE_PLAN_FIELDS = {
    "schema_version",
    "plan_id",
    "status",
    "operation",
    "created_at",
    "expires_at",
    "git_head",
    "project_id",
    "binding_sha256",
    "adapter_fingerprint_sha256",
    "core_manifest_sha256",
    "record_type_registry_sha256",
    "recovery_profile_sha256",
    "retention_policy_sha256",
    "bundle",
    "targets",
    "target_inventory_sha256",
    "target_execution_order",
    "backup_id",
    "exact_diff",
    "commit_created",
    "push_performed",
    "content_sha256",
}
RESTORE_TARGET_FIELDS = {
    "entry_id",
    "path",
    "action",
    "before_sha256",
    "after_sha256",
    "bytes",
    "backup_required",
}
RESTORE_BACKUP_FIELDS = {
    "schema_version",
    "backup_id",
    "plan_id",
    "project_id",
    "created_at",
    "files",
    "raw_conversation_stored",
    "prompt_stored",
    "chain_of_thought_stored",
    "secret_stored",
    "content_sha256",
}
RESTORE_BACKUP_FILE_FIELDS = {
    "entry_id",
    "path",
    "present",
    "sha256",
    "bytes",
    "storage_path",
}
RESTORE_RECEIPT_FIELDS = {
    "schema_version",
    "receipt_id",
    "plan_id",
    "operation",
    "status",
    "project_id",
    "base_commit",
    "applied_at",
    "binding_sha256",
    "adapter_fingerprint_sha256",
    "core_manifest_sha256",
    "record_type_registry_sha256",
    "recovery_profile_sha256",
    "retention_policy_sha256",
    "bundle",
    "targets",
    "target_inventory_sha256",
    "target_execution_order",
    "backup",
    "post_apply",
    "backup_verified",
    "rollback_ready",
    "source_deleted",
    "core_overwritten",
    "owner_confirmation_performed",
    "raw_conversation_stored",
    "prompt_stored",
    "chain_of_thought_stored",
    "secret_stored",
    "commit_created",
    "push_performed",
    "content_sha256",
}

_PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
_RECEIPT_DIR_AGENT_REL = "project/context/continuity-portability-receipts"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _valid_hash(value: Any, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (
        isinstance(value, str) and _SHA256.fullmatch(value) is not None
    )


def _valid_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = parse_time(value)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _has_portable_path_collision(items: list[Any]) -> bool:
    collision_paths: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not 1 <= len(path) <= 512:
            continue
        try:
            collision_key = portable_collision_key(path, canonical=True)
        except ValueError:
            continue
        colliding_path = collision_paths.get(collision_key)
        if colliding_path is not None and colliding_path != path:
            return True
        collision_paths[collision_key] = path
    return False
