#!/usr/bin/env python3
"""Shared contracts for transactional continuity operations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_os_continuity import MAX_JSON_BYTES

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_REL = "project/context/continuity.json"
PROJECTION_REL = "project/context/continuity-projection.json"
BACKUP_DIR_REL = "project/context/continuity-backups"
TRANSACTION_DIR_REL = "project/context/continuity-transactions"
BINDING_REL = "project/project-binding.json"
FINGERPRINT_REL = "project/adapter-fingerprint.json"
CORE_MANIFEST_REL = "_manifest/base-release-manifest.json"
REGISTRY_REL = "memory/continuity-record-types.json"
PROFILE_REL = "memory/continuity-recovery-profiles.json"
MIGRATION_REGISTRY_REL = "memory/continuity-migrations.json"

PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
BACKUP_ID = re.compile(r"^continuity-backup-[0-9a-f]{24}$")
TRANSACTION_ID = re.compile(r"^continuity-tx-[0-9a-f]{24}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OPERATIONS = {"initialize", "refresh", "migrate", "repair", "rollback"}
TARGETS = (CATALOG_REL, PROJECTION_REL)
MAX_PLAN_SECONDS = 3600

DEFAULT_SOURCE_PATHS = {
    ".agents/project/project-binding.json",
    ".agents/_manifest/base-release-manifest.json",
    ".agents/project/genesis.json",
    ".agents/project/context/context-manifest.json",
    "docs/roadmap.md",
    "docs/context/current-status.md",
    ".agents/project/context/active-tasks.json",
}
MIGRATION_REGISTRY_FIELDS = {
    "schema_version",
    "registry_id",
    "registry_version",
    "migrations",
}
MIGRATION_FIELDS = {
    "migration_id",
    "source_generation",
    "target_generation",
    "provider",
    "source_fields",
    "preserve_reference_bytes",
    "reject_unknown_fields",
    "requires_backup",
}
PLAN_FIELDS = {
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
    "migration_registry_sha256",
    "source_inventory",
    "source_inventory_sha256",
    "changes",
    "exact_diff",
    "metadata",
    "commit_created",
    "push_performed",
    "content_sha256",
}
CHANGE_FIELDS = {
    "path",
    "before_sha256",
    "after_sha256",
    "before_base64",
    "after_base64",
}
INVENTORY_FIELDS = {"path", "present", "sha256", "head_sha256", "clean"}
PLAN_METADATA_REQUIRED = {
    "transaction_id",
    "backup_id",
    "source_generation",
    "target_generation",
    "critical_set_before",
    "critical_set_after",
    "unknown_fields_sha256",
}
PLAN_METADATA_OPTIONAL = {
    "migration_id",
    "migration_path",
    "migration_path_sha256",
    "restored_backup_id",
    "rolled_back_transaction_id",
}
MIGRATION_PATH_FIELDS = {
    "migration_id",
    "provider",
    "source_generation",
    "target_generation",
    "unknown_fields_sha256",
}
BACKUP_INDEX_FIELDS = {
    "schema_version",
    "backup_id",
    "project_id",
    "operation",
    "created_at",
    "git_head",
    "binding_sha256",
    "files",
    "raw_conversation_stored",
    "content_sha256",
}
BACKUP_FILE_FIELDS = {"path", "present", "sha256", "bytes", "storage_path"}
TRANSACTION_RECEIPT_FIELDS = {
    "schema_version",
    "transaction_id",
    "operation",
    "status",
    "project_id",
    "base_commit",
    "applied_at",
    "source_generation",
    "target_generation",
    "binding_sha256",
    "adapter_fingerprint_sha256",
    "record_type_registry_sha256",
    "recovery_profile_sha256",
    "migration_registry_sha256",
    "before_catalog_sha256",
    "after_catalog_sha256",
    "source_inventory_sha256",
    "critical_set_before",
    "critical_set_after",
    "unknown_fields_sha256",
    "backup",
    "semantic_completeness",
    "rollback_verified",
    "source_deleted",
    "owner_confirmation_performed",
    "raw_conversation_stored",
    "commit_created",
    "push_performed",
    "content_sha256",
}
TRANSACTION_RECEIPT_MIGRATION_FIELDS = {
    "migration_path",
    "migration_path_sha256",
}
BACKUP_REFERENCE_FIELDS = {"backup_id", "index_path", "index_sha256"}
SEMANTIC_FIELDS = {"topology_state", "authority_state", "reason_codes"}


def strict_document(content: bytes) -> Any:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    if len(content) > MAX_JSON_BYTES:
        raise ValueError("JSON document exceeds the read boundary")
    return json.loads(
        content.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
