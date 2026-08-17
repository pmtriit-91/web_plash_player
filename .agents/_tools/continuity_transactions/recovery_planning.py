from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    atomic_bytes,
    iso_time,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity import doctor
from continuity_transactions.contracts import (
    BACKUP_DIR_REL,
    BACKUP_ID,
    CATALOG_REL,
    PROJECTION_REL,
    TARGETS,
    TRANSACTION_DIR_REL,
    TRANSACTION_ID,
    strict_document,
)


def read_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


# fmt: off
class RecoveryPlanningMixin:
    def backup_index(self, backup_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        if not BACKUP_ID.fullmatch(backup_id):
            return None, ["CONTINUITY_BACKUP_ID_INVALID"]
        index_path = self.path(f"{BACKUP_DIR_REL}/{backup_id}/index.json")
        content = read_bytes(index_path)
        if content is None:
            return None, ["CONTINUITY_BACKUP_NOT_FOUND"]
        try:
            index = strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, ["CONTINUITY_BACKUP_INDEX_INVALID"]
        validation_errors = self.validate_backup_index(index, backup_id)
        if validation_errors:
            return None, validation_errors
        return index, []

    def backup_contents(self, backup_id: str) -> tuple[dict[str, bytes | None] | None, list[str]]:
        index, errors = self.backup_index(backup_id)
        if errors or index is None:
            return None, errors
        result: dict[str, bytes | None] = {}
        for item in index["files"]:
            relative = item.get("path")
            if item["present"]:
                storage_path = item.get("storage_path")
                content = read_bytes(self.path(storage_path))
                if (
                    content is None
                    or sha256_bytes(content) != item.get("sha256")
                    or len(content) != item.get("bytes")
                ):
                    return None, ["CONTINUITY_BACKUP_CONTENT_INVALID"]
                result[relative] = content
            else:
                if item.get("sha256") is not None or item.get("storage_path") is not None or item.get("bytes") != 0:
                    return None, ["CONTINUITY_BACKUP_INDEX_INVALID"]
                result[relative] = None
        return result, []

    def plan_repair(self, backup_id: str | None = None) -> dict[str, Any]:
        health = doctor(self.root)
        if health.get("topology_state") == "contaminated":
            return {"ok": False, "reason_codes": ["CONTINUITY_REPAIR_CONTAMINATED_BLOCKED"]}
        if backup_id is None:
            if health.get("topology_state") in {"complete", "incomplete"}:
                return self.plan_refresh("repair")
            return {"ok": False, "reason_codes": ["CONTINUITY_REPAIR_BACKUP_REQUIRED"]}
        desired, errors = self.backup_contents(backup_id)
        if errors or desired is None:
            return {"ok": False, "reason_codes": errors}
        catalog_content = desired.get(CATALOG_REL)
        if catalog_content is None:
            return {"ok": False, "reason_codes": ["CONTINUITY_REPAIR_BACKUP_CATALOG_MISSING"]}
        try:
            catalog = strict_document(catalog_content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"ok": False, "reason_codes": ["CONTINUITY_REPAIR_BACKUP_CATALOG_INVALID"]}
        if not isinstance(catalog, dict):
            return {"ok": False, "reason_codes": ["CONTINUITY_REPAIR_BACKUP_CATALOG_INVALID"]}
        projection, _health, projection_errors = self.projection_for(catalog)
        if projection_errors or projection is None:
            return {"ok": False, "reason_codes": projection_errors}
        desired[PROJECTION_REL] = projection
        before = None
        current = self.target_bytes(CATALOG_REL)
        if current is not None:
            try:
                before = strict_document(current)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                before = None
        return self.create_plan(
            "repair",
            desired,
            before_catalog=before,
            after_catalog=catalog,
            source_paths=self.catalog_source_paths(catalog),
            metadata={"restored_backup_id": backup_id},
        )

    def transaction_receipt(self, transaction_id: str) -> tuple[dict[str, Any] | None, list[str]]:
        if not TRANSACTION_ID.fullmatch(transaction_id):
            return None, ["CONTINUITY_TRANSACTION_ID_INVALID"]
        content = read_bytes(self.path(f"{TRANSACTION_DIR_REL}/{transaction_id}.json"))
        if content is None:
            return None, ["CONTINUITY_TRANSACTION_NOT_FOUND"]
        try:
            receipt = strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]
        validation_errors = self.validate_transaction_receipt(receipt, transaction_id)
        if validation_errors:
            return None, validation_errors
        return receipt, []

    def plan_rollback(self, transaction_id: str) -> dict[str, Any]:
        receipt, errors = self.transaction_receipt(transaction_id)
        if errors or receipt is None:
            return {"ok": False, "reason_codes": errors}
        backup = receipt.get("backup")
        if not isinstance(backup, dict):
            return {"ok": False, "reason_codes": ["CONTINUITY_TRANSACTION_RECEIPT_INVALID"]}
        desired, backup_errors = self.backup_contents(str(backup.get("backup_id", "")))
        if backup_errors or desired is None:
            return {"ok": False, "reason_codes": backup_errors}
        before = None
        after = None
        current = self.target_bytes(CATALOG_REL)
        if current is not None:
            try:
                before = strict_document(current)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                before = None
        restored = desired.get(CATALOG_REL)
        if restored is not None:
            try:
                after = strict_document(restored)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return {"ok": False, "reason_codes": ["CONTINUITY_ROLLBACK_CATALOG_INVALID"]}
        return self.create_plan(
            "rollback",
            desired,
            before_catalog=before,
            after_catalog=after,
            source_paths=self.catalog_source_paths(after),
            metadata={"rolled_back_transaction_id": transaction_id},
        )

    def create_backup(
        self,
        plan: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        backup_id = str(plan.get("metadata", {}).get("backup_id", ""))
        if not BACKUP_ID.fullmatch(backup_id):
            return None, ["CONTINUITY_BACKUP_ID_INVALID"]
        directory_rel = f"{BACKUP_DIR_REL}/{backup_id}"
        directory = self.path(directory_rel)
        if directory.exists():
            return None, ["CONTINUITY_BACKUP_ALREADY_EXISTS"]
        files: list[dict[str, Any]] = []
        storage_names = {
            CATALOG_REL: "catalog.bin",
            PROJECTION_REL: "projection.bin",
        }
        for relative in TARGETS:
            content = self.target_bytes(relative)
            storage_path = f"{directory_rel}/{storage_names[relative]}" if content is not None else None
            if content is not None:
                atomic_bytes(self.path(str(storage_path)), content)
            files.append(
                {
                    "path": relative,
                    "present": content is not None,
                    "sha256": sha256_bytes(content) if content is not None else None,
                    "bytes": len(content) if content is not None else 0,
                    "storage_path": storage_path,
                }
            )
        index = {
            "schema_version": 1,
            "backup_id": backup_id,
            "project_id": plan["project_id"],
            "operation": plan["operation"],
            "created_at": iso_time(self.now()),
            "git_head": plan["git_head"],
            "binding_sha256": plan["binding_sha256"],
            "files": files,
            "raw_conversation_stored": False,
        }
        index["content_sha256"] = receipt_hash(index)
        index_path = f"{directory_rel}/index.json"
        atomic_bytes(self.path(index_path), json_bytes(index))
        restored, errors = self.backup_contents(backup_id)
        if errors or restored is None:
            return None, errors or ["CONTINUITY_BACKUP_VERIFICATION_FAILED"]
        return {
            "backup_id": backup_id,
            "index_path": index_path,
            "index_sha256": sha256_bytes(self.path(index_path).read_bytes()),
        }, []
