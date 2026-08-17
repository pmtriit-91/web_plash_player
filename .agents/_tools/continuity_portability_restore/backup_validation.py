#!/usr/bin/env python3
"""Restore backup-index validation with bounded file and payload checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_os_context_memory import receipt_hash, sha256_bytes
from agent_os_continuity_portability_export import ENTRY_ID
from agent_os_continuity_portability_foundation import (
    read_regular_bounded,
    scan_tree_bounded,
)
from agent_os_paths import safe_join
from continuity_portability_restore.contracts import (
    BACKUP_ID,
    RESTORE_BACKUP_FIELDS,
    RESTORE_BACKUP_FILE_FIELDS,
    _has_portable_path_collision,
    _valid_hash,
    _valid_time,
)


class RestoreBackupValidationMixin:
    """Validate a restore backup without owning creation or rollback."""

    def validate_restore_backup_index(
        self,
        index: Any,
        plan: dict[str, Any],
        backup_path: Path,
    ) -> list[str]:
        policy, policy_errors = self.policy()
        if policy is None:
            return policy_errors
        backup_root = self.verified_restore_backup_root()
        if (
            backup_root is None
            or backup_path.parent != backup_root
            or backup_path.name != str(plan.get("backup_id", ""))
            or self._safe_directory_stat(backup_path) is None
            or not backup_path.is_dir()
        ):
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        if not isinstance(index, dict) or set(index) != RESTORE_BACKUP_FIELDS:
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        if (
            index.get("schema_version") != 1
            or index.get("backup_id") != plan.get("backup_id")
            or BACKUP_ID.fullmatch(str(index.get("backup_id", ""))) is None
            or index.get("plan_id") != plan.get("plan_id")
            or index.get("project_id") != plan.get("project_id")
            or not _valid_time(index.get("created_at"))
            or index.get("raw_conversation_stored") is not False
            or index.get("prompt_stored") is not False
            or index.get("chain_of_thought_stored") is not False
            or index.get("secret_stored") is not False
            or index.get("content_sha256") != receipt_hash(index)
        ):
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        files = index.get("files")
        if (
            not isinstance(files, list)
            or not 1 <= len(files) <= policy["bounds"]["max_entries"]
            or len(files) != len(plan.get("targets", []))
        ):
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        if _has_portable_path_collision(files):
            return ["PORTABILITY_RESTORE_BACKUP_PATH_COLLISION"]
        target_by_id = {item["entry_id"]: item for item in plan.get("targets", [])}
        paths: list[str] = []
        storage_paths: set[str] = set()
        total_bytes = 0
        for item in files:
            if not isinstance(item, dict) or set(item) != RESTORE_BACKUP_FILE_FIELDS:
                return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
            path = item.get("path")
            if not isinstance(path, str) or not 1 <= len(path) <= 512:
                return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
            target = target_by_id.get(item.get("entry_id"))
            present = item.get("present")
            digest = item.get("sha256")
            size = item.get("bytes")
            storage_path = item.get("storage_path")
            if (
                target is None
                or item.get("path") != target["path"]
                or item["path"] in paths
                or ENTRY_ID.fullmatch(str(item.get("entry_id", ""))) is None
                or type(present) is not bool
                or type(size) is not int
                or not 0 <= size <= policy["bounds"]["max_file_bytes"]
                or digest != target.get("before_sha256")
                or present is not (target.get("before_sha256") is not None)
            ):
                return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
            if present:
                expected_storage = f"files/{item['entry_id']}.bin"
                payload, _payload_error = read_regular_bounded(
                    safe_join(backup_path, expected_storage, canonical=True),
                    size,
                )
                if (
                    storage_path != expected_storage
                    or storage_path in storage_paths
                    or not _valid_hash(digest)
                    or payload is None
                    or len(payload) != size
                    or sha256_bytes(payload) != digest
                ):
                    return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
                storage_paths.add(storage_path)
            elif digest is not None or size != 0 or storage_path is not None:
                return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
            paths.append(item["path"])
            total_bytes += size
        if paths != sorted(paths) or total_bytes > policy["bounds"]["max_total_bytes"]:
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        expected_files = {"index.json", *storage_paths}
        files, _visited, scan_error, _error_path = scan_tree_bounded(
            backup_path,
            policy["bounds"]["max_entries"] * 2 + 16,
        )
        if scan_error is not None:
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        actual_files = {path.relative_to(backup_path).as_posix() for path in files}
        if actual_files != expected_files:
            return ["PORTABILITY_RESTORE_BACKUP_INVALID"]
        return []
