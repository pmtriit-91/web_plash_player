from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_os_context_memory import canonical_hash, receipt_hash, sha256_bytes
from continuity_transactions.contracts import (
    BACKUP_DIR_REL,
    BACKUP_FILE_FIELDS,
    BACKUP_ID,
    BACKUP_INDEX_FIELDS,
    BACKUP_REFERENCE_FIELDS,
    CATALOG_REL,
    FULL_COMMIT,
    MAX_JSON_BYTES,
    OPERATIONS,
    PROJECTION_REL,
    SEMANTIC_FIELDS,
    TARGETS,
    TRANSACTION_ID,
    TRANSACTION_RECEIPT_FIELDS,
    TRANSACTION_RECEIPT_MIGRATION_FIELDS,
)


def read_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


# fmt: off
class ReceiptValidationMixin:
    def validate_backup_index(self, index: Any, backup_id: str) -> list[str]:
        contracts = self.contract_hashes() or {}
        if not isinstance(index, dict) or set(index) != BACKUP_INDEX_FIELDS:
            return ["CONTINUITY_BACKUP_INDEX_INVALID"]
        if (
            index.get("schema_version") != 1
            or index.get("backup_id") != backup_id
            or not BACKUP_ID.fullmatch(backup_id)
            or index.get("project_id") != self.binding().get("project_id")
            or index.get("operation") not in OPERATIONS
            or not self.valid_time(index.get("created_at"))
            or not isinstance(index.get("git_head"), str)
            or FULL_COMMIT.fullmatch(index["git_head"]) is None
            or index.get("binding_sha256") != contracts.get("binding_sha256")
            or index.get("raw_conversation_stored") is not False
            or index.get("content_sha256") != receipt_hash(index)
        ):
            return ["CONTINUITY_BACKUP_INDEX_INVALID"]
        files = index.get("files")
        if not isinstance(files, list) or len(files) != len(TARGETS):
            return ["CONTINUITY_BACKUP_INDEX_INVALID"]
        by_path: dict[str, dict[str, Any]] = {}
        for item in files:
            if not isinstance(item, dict) or set(item) != BACKUP_FILE_FIELDS:
                return ["CONTINUITY_BACKUP_INDEX_INVALID"]
            relative = item.get("path")
            if relative not in TARGETS or relative in by_path:
                return ["CONTINUITY_BACKUP_INDEX_INVALID"]
            by_path[relative] = item
            expected_storage = {
                CATALOG_REL: f"{BACKUP_DIR_REL}/{backup_id}/catalog.bin",
                PROJECTION_REL: f"{BACKUP_DIR_REL}/{backup_id}/projection.bin",
            }[relative]
            present = item.get("present")
            if type(present) is not bool or type(item.get("bytes")) is not int:
                return ["CONTINUITY_BACKUP_INDEX_INVALID"]
            if present:
                if (
                    not self.valid_hash(item.get("sha256"))
                    or not 0 <= item["bytes"] <= MAX_JSON_BYTES
                    or item.get("storage_path") != expected_storage
                ):
                    return ["CONTINUITY_BACKUP_INDEX_INVALID"]
            elif (
                item.get("sha256") is not None
                or item.get("bytes") != 0
                or item.get("storage_path") is not None
            ):
                return ["CONTINUITY_BACKUP_INDEX_INVALID"]
        return []

    def validate_transaction_receipt(
        self,
        receipt: Any,
        transaction_id: str,
    ) -> list[str]:
        if not isinstance(receipt, dict):
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        receipt_fields = set(receipt)
        migration_fields_present = receipt_fields == (
            TRANSACTION_RECEIPT_FIELDS | TRANSACTION_RECEIPT_MIGRATION_FIELDS
        )
        if frozenset(receipt_fields) not in {
            frozenset(TRANSACTION_RECEIPT_FIELDS),
            frozenset(
                TRANSACTION_RECEIPT_FIELDS | TRANSACTION_RECEIPT_MIGRATION_FIELDS
            ),
        }:
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        hashes = (
            "binding_sha256",
            "adapter_fingerprint_sha256",
            "record_type_registry_sha256",
            "recovery_profile_sha256",
            "migration_registry_sha256",
            "source_inventory_sha256",
        )
        if (
            receipt.get("schema_version") != 1
            or receipt.get("transaction_id") != transaction_id
            or not TRANSACTION_ID.fullmatch(transaction_id)
            or receipt.get("operation") not in OPERATIONS
            or receipt.get("status") != "applied"
            or receipt.get("project_id") != self.binding().get("project_id")
            or not isinstance(receipt.get("base_commit"), str)
            or FULL_COMMIT.fullmatch(receipt["base_commit"]) is None
            or not self.valid_time(receipt.get("applied_at"))
            or not self.valid_generation(receipt.get("source_generation"))
            or not self.valid_generation(receipt.get("target_generation"))
            or any(not self.valid_hash(receipt.get(field)) for field in hashes)
            or not self.valid_hash(receipt.get("before_catalog_sha256"), nullable=True)
            or not self.valid_hash(receipt.get("after_catalog_sha256"), nullable=True)
            or not self.valid_hash(receipt.get("unknown_fields_sha256"), nullable=True)
            or not self.valid_critical_set(receipt.get("critical_set_before"))
            or not self.valid_critical_set(receipt.get("critical_set_after"))
            or type(receipt.get("rollback_verified")) is not bool
            or receipt.get("source_deleted") is not False
            or receipt.get("owner_confirmation_performed") is not False
            or receipt.get("raw_conversation_stored") is not False
            or receipt.get("commit_created") is not False
            or receipt.get("push_performed") is not False
            or receipt.get("content_sha256") != receipt_hash(receipt)
        ):
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        generation_two_migration = (
            receipt["operation"] == "migrate" and receipt["target_generation"] == 2
        )
        migration_path = receipt.get("migration_path")
        if generation_two_migration != migration_fields_present or (
            generation_two_migration
            and (
                not self.valid_migration_path(migration_path)
                or not self.valid_hash(receipt.get("migration_path_sha256"))
                or canonical_hash(migration_path)
                != receipt["migration_path_sha256"]
                or migration_path[0]["source_generation"]
                != receipt["source_generation"]
                or migration_path[-1]["target_generation"]
                != receipt["target_generation"]
                or receipt["unknown_fields_sha256"]
                != canonical_hash(
                    [item["unknown_fields_sha256"] for item in migration_path]
                )
            )
        ):
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        backup = receipt.get("backup")
        if not isinstance(backup, dict) or set(backup) != BACKUP_REFERENCE_FIELDS:
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        backup_id = str(backup.get("backup_id", ""))
        expected_index = f"{BACKUP_DIR_REL}/{backup_id}/index.json"
        if (
            not BACKUP_ID.fullmatch(backup_id)
            or backup.get("index_path") != expected_index
            or not self.valid_hash(backup.get("index_sha256"))
        ):
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        index_content = read_bytes(self.path(expected_index))
        if (
            index_content is None
            or sha256_bytes(index_content) != backup["index_sha256"]
        ):
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        index, index_errors = self.backup_index(backup_id)
        if index_errors or index is None:
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        semantic = receipt.get("semantic_completeness")
        if (
            not isinstance(semantic, dict)
            or set(semantic) != SEMANTIC_FIELDS
            or semantic.get("topology_state")
            not in {
                "complete",
                "incomplete",
                "corrupt",
                "contaminated",
                "migration-required",
                "unsupported",
                "unconfigured",
            }
            or semantic.get("authority_state") not in {"available", "partial", "unavailable"}
            or not isinstance(semantic.get("reason_codes"), list)
            or len(semantic["reason_codes"]) > 256
            or len(semantic["reason_codes"]) != len(set(semantic["reason_codes"]))
            or any(not isinstance(item, str) or not item for item in semantic["reason_codes"])
        ):
            return ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        return []
