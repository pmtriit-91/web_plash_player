#!/usr/bin/env python3
"""Restore backup creation and byte-exact rollback lifecycle."""

from __future__ import annotations

from typing import Any

from agent_os_context_memory import (
    iso_time,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity_portability_foundation import (
    RESTORE_BACKUP_DIR_AGENT_REL,
    read_regular_bounded,
)
from agent_os_paths import safe_join
from continuity_portability_restore.backup_validation import (
    RestoreBackupValidationMixin,
)


class RestoreBackupLifecycleMixin(RestoreBackupValidationMixin):
    """Create validated backups and restore them in reverse dependency order."""

    def create_restore_backup(
        self,
        plan: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        backup_root = self.verified_restore_backup_root(create=True)
        if backup_root is None:
            return None, ["PORTABILITY_RESTORE_BACKUP_ROOT_INVALID"]
        backup_path = backup_root / plan["backup_id"]
        if backup_path.exists() or self.path_is_link_like(backup_path):
            return None, ["PORTABILITY_RESTORE_BACKUP_EXISTS"]
        backup_relative = f"{RESTORE_BACKUP_DIR_AGENT_REL}/{plan['backup_id']}"
        policy, policy_errors = self.policy()
        if policy is None:
            return None, policy_errors
        files: list[dict[str, Any]] = []
        try:
            created_backup = self._create_scoped_directory(
                self.root,
                backup_relative,
                create_parents=True,
            )
            if (
                created_backup != backup_path
                or self.verified_restore_backup_root() != backup_root
                or self._safe_directory_stat(backup_path) is None
                or not backup_path.is_dir()
            ):
                raise ValueError("restore backup root changed during creation")
            for target in plan["targets"]:
                target_path = self.project_path(target["path"])
                content, content_error = read_regular_bounded(
                    target_path,
                    policy["bounds"]["max_file_bytes"],
                )
                if target_path.exists() and content is None:
                    raise ValueError(f"backup target unreadable: {content_error}")
                content_sha256 = sha256_bytes(content) if content is not None else None
                if content_sha256 != target["before_sha256"]:
                    raise ValueError("restore target changed before backup")
                if content is not None:
                    privacy_error = self.privacy_error(content, target["path"])
                    if privacy_error:
                        raise ValueError(
                            f"backup target privacy gate failed: {privacy_error}"
                        )
                present = content is not None
                storage_path = f"files/{target['entry_id']}.bin" if present else None
                if content is not None:
                    self._atomic_scoped_bytes(
                        self.root,
                        f"{backup_relative}/{storage_path}",
                        content,
                        create_parents=True,
                    )
                files.append(
                    {
                        "entry_id": target["entry_id"],
                        "path": target["path"],
                        "present": present,
                        "sha256": content_sha256,
                        "bytes": len(content) if content is not None else 0,
                        "storage_path": storage_path,
                    }
                )
            index: dict[str, Any] = {
                "schema_version": 1,
                "backup_id": plan["backup_id"],
                "plan_id": plan["plan_id"],
                "project_id": plan["project_id"],
                "created_at": iso_time(self.now()),
                "files": files,
                "raw_conversation_stored": False,
                "prompt_stored": False,
                "chain_of_thought_stored": False,
                "secret_stored": False,
            }
            index["content_sha256"] = receipt_hash(index)
            self._atomic_scoped_bytes(
                self.root,
                f"{backup_relative}/index.json",
                json_bytes(index),
                create_parents=True,
            )
            validation = self.validate_restore_backup_index(
                index,
                plan,
                backup_path,
            )
            if validation:
                raise ValueError(f"backup validation failed: {validation}")
            return index, []
        except Exception:  # noqa: BLE001 - preserve fail-closed parity
            try:
                self._remove_scoped_tree(self.root, backup_relative)
            except (OSError, ValueError):
                pass
            return None, ["PORTABILITY_RESTORE_BACKUP_FAILED"]

    def restore_backup(
        self,
        plan: dict[str, Any],
        index: dict[str, Any],
    ) -> bool:
        backup_root = self.verified_restore_backup_root()
        if backup_root is None:
            return False
        backup_path = backup_root / plan["backup_id"]
        if self.validate_restore_backup_index(index, plan, backup_path):
            return False
        target_by_id = {target["entry_id"]: target for target in plan["targets"]}
        indexed_by_id = {item["entry_id"]: item for item in index["files"]}
        ok = True
        for entry_id in reversed(plan["target_execution_order"]):
            item = indexed_by_id[entry_id]
            if (
                self.verified_restore_backup_root() != backup_root
                or self._safe_directory_stat(backup_path) is None
                or not backup_path.is_dir()
            ):
                return False
            try:
                target = target_by_id[item["entry_id"]]
                current, current_error = self._read_scoped_regular(
                    self.project_root,
                    item["path"],
                    max(item["bytes"], target["bytes"], 1),
                )
                current_sha256 = sha256_bytes(current) if current is not None else None
                if current_sha256 == item["sha256"]:  # noqa: SIM102 - AST parity
                    if (
                        current is not None
                        or current_error == "PORTABILITY_FILE_NOT_FOUND"
                    ):
                        continue
                if (
                    current is None
                    or current_error is not None
                    or current_sha256 != target["after_sha256"]
                ):
                    ok = False
                    continue
                if item["present"]:
                    content, _content_error = read_regular_bounded(
                        safe_join(
                            backup_path,
                            item["storage_path"],
                            canonical=True,
                        ),
                        item["bytes"],
                    )
                    if content is None or sha256_bytes(content) != item["sha256"]:
                        ok = False
                        continue
                    self._atomic_scoped_bytes(
                        self.project_root,
                        item["path"],
                        content,
                        create_parents=False,
                        expected_before_sha256=target["after_sha256"],
                    )
                else:
                    if not self._unlink_scoped_file(
                        self.project_root,
                        item["path"],
                        expected_before_sha256=target["after_sha256"],
                    ):
                        ok = False
            except (OSError, ValueError):
                ok = False
        for item in index["files"]:
            try:
                content, _content_error = self._read_scoped_regular(
                    self.project_root,
                    item["path"],
                    max(item["bytes"], 1),
                )
            except (OSError, ValueError):
                content = None
            digest = sha256_bytes(content) if content is not None else None
            if digest != item["sha256"]:
                ok = False
        return ok
