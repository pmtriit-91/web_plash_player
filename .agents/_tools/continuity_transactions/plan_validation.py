from __future__ import annotations

import difflib
import json
import re
from copy import deepcopy
from typing import Any

from agent_os_context_memory import (
    canonical_hash,
    decoded,
    parse_time,
    receipt_hash,
    sha256_bytes,
)
from continuity_transactions.contracts import (
    BACKUP_ID,
    CATALOG_REL,
    CHANGE_FIELDS,
    FULL_COMMIT,
    INVENTORY_FIELDS,
    MAX_PLAN_SECONDS,
    MIGRATION_PATH_FIELDS,
    OPERATIONS,
    PLAN_FIELDS,
    PLAN_ID,
    PLAN_METADATA_OPTIONAL,
    PLAN_METADATA_REQUIRED,
    SHA256,
    TARGETS,
    TRANSACTION_ID,
    strict_document,
)


# fmt: off
class PlanValidationMixin:
    @staticmethod
    def valid_time(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            parsed = parse_time(value)
        except (TypeError, ValueError):
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None

    @staticmethod
    def valid_hash(value: Any, *, nullable: bool = False) -> bool:
        return (nullable and value is None) or (
            isinstance(value, str) and SHA256.fullmatch(value) is not None
        )

    @staticmethod
    def valid_generation(value: Any) -> bool:
        return value is None or (type(value) is int and value >= 0)

    @staticmethod
    def valid_critical_set(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) <= 1024
            and len(value) == len(set(value))
            and all(isinstance(item, str) and 1 <= len(item) <= 128 for item in value)
        )

    @staticmethod
    def valid_migration_path(value: Any) -> bool:
        if not isinstance(value, list) or not 1 <= len(value) <= 8:
            return False
        identifiers: set[str] = set()
        previous_target: int | None = None
        for item in value:
            if not isinstance(item, dict) or set(item) != MIGRATION_PATH_FIELDS:
                return False
            identifier = item.get("migration_id")
            provider = item.get("provider")
            source = item.get("source_generation")
            target = item.get("target_generation")
            if (
                not isinstance(identifier, str)
                or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", identifier) is None
                or identifier in identifiers
                or not isinstance(provider, str)
                or re.fullmatch(r"builtin:[a-z0-9][a-z0-9-]{0,127}", provider) is None
                or type(source) is not int
                or type(target) is not int
                or source < 0
                or target <= source
                or (previous_target is not None and source != previous_target)
                or not PlanValidationMixin.valid_hash(item.get("unknown_fields_sha256"))
            ):
                return False
            identifiers.add(identifier)
            previous_target = target
        return True

    @staticmethod
    def render_exact_diff(changes: list[dict[str, Any]]) -> str:
        result = ""
        for change in changes:
            before = decoded(change.get("before_base64"))
            after = decoded(change.get("after_base64"))
            before_lines = (before or b"").decode(
                "utf-8", errors="replace"
            ).splitlines(keepends=True)
            after_lines = (after or b"").decode(
                "utf-8", errors="replace"
            ).splitlines(keepends=True)
            result += "".join(
                difflib.unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"a/.agents/{change['path']}",
                    tofile=f"b/.agents/{change['path']}",
                )
            )
        return result

    def validate_plan(self, plan: Any, plan_id: str) -> list[str]:
        if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS:
            return ["CONTINUITY_PLAN_FIELDS_INVALID"]
        expected_plan_id = canonical_hash(
            {
                key: value
                for key, value in plan.items()
                if key not in {"plan_id", "content_sha256"}
            }
        )[:24]
        try:
            created_at = parse_time(str(plan.get("created_at")))
            expires_at = parse_time(str(plan.get("expires_at")))
        except (TypeError, ValueError):
            return ["CONTINUITY_PLAN_INVALID"]
        if (
            plan.get("schema_version") != 1
            or plan.get("plan_id") != plan_id
            or not PLAN_ID.fullmatch(plan_id)
            or expected_plan_id != plan_id
            or plan.get("status") != "pending-approval"
            or plan.get("operation") not in OPERATIONS
            or not self.valid_time(plan.get("created_at"))
            or not self.valid_time(plan.get("expires_at"))
            or expires_at <= created_at
            or (expires_at - created_at).total_seconds() > MAX_PLAN_SECONDS
            or not isinstance(plan.get("git_head"), str)
            or FULL_COMMIT.fullmatch(plan["git_head"]) is None
            or plan.get("project_id") != self.binding().get("project_id")
            or plan.get("commit_created") is not False
            or plan.get("push_performed") is not False
            or plan.get("content_sha256") != receipt_hash(plan)
        ):
            return ["CONTINUITY_PLAN_INVALID"]
        for field in (
            "binding_sha256",
            "adapter_fingerprint_sha256",
            "core_manifest_sha256",
            "record_type_registry_sha256",
            "recovery_profile_sha256",
            "migration_registry_sha256",
            "source_inventory_sha256",
        ):
            if not self.valid_hash(plan.get(field)):
                return ["CONTINUITY_PLAN_INVALID"]
        inventory = plan.get("source_inventory")
        if not isinstance(inventory, list) or len(inventory) > 2048:
            return ["CONTINUITY_PLAN_INVENTORY_INVALID"]
        inventory_paths: set[str] = set()
        for item in inventory:
            if not isinstance(item, dict) or set(item) != INVENTORY_FIELDS:
                return ["CONTINUITY_PLAN_INVENTORY_INVALID"]
            relative = item.get("path")
            if not isinstance(relative, str) or relative in inventory_paths:
                return ["CONTINUITY_PLAN_INVENTORY_INVALID"]
            try:
                self.project_path(relative)
            except ValueError:
                return ["CONTINUITY_PLAN_INVENTORY_INVALID"]
            inventory_paths.add(relative)
            if (
                type(item.get("present")) is not bool
                or type(item.get("clean")) is not bool
                or not self.valid_hash(item.get("sha256"), nullable=True)
                or not self.valid_hash(item.get("head_sha256"), nullable=True)
            ):
                return ["CONTINUITY_PLAN_INVENTORY_INVALID"]
        if canonical_hash(inventory) != plan.get("source_inventory_sha256"):
            return ["CONTINUITY_PLAN_INVENTORY_INVALID"]
        changes = plan.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= len(TARGETS):
            return ["CONTINUITY_PLAN_CHANGES_INVALID"]
        change_paths: set[str] = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != CHANGE_FIELDS:
                return ["CONTINUITY_PLAN_CHANGES_INVALID"]
            relative = change.get("path")
            if relative not in TARGETS or relative in change_paths:
                return ["CONTINUITY_PLAN_CHANGES_INVALID"]
            change_paths.add(relative)
            try:
                before = decoded(change.get("before_base64"))
                after = decoded(change.get("after_base64"))
            except (TypeError, ValueError):
                return ["CONTINUITY_PLAN_CHANGES_INVALID"]
            if (
                not self.valid_hash(change.get("before_sha256"), nullable=True)
                or not self.valid_hash(change.get("after_sha256"), nullable=True)
                or (sha256_bytes(before) if before is not None else None)
                != change.get("before_sha256")
                or (sha256_bytes(after) if after is not None else None)
                != change.get("after_sha256")
                or before == after
            ):
                return ["CONTINUITY_PLAN_CHANGES_INVALID"]
        if plan.get("exact_diff") != self.render_exact_diff(changes):
            return ["CONTINUITY_PLAN_INVALID"]
        metadata = plan.get("metadata")
        if (
            not isinstance(metadata, dict)
            or not PLAN_METADATA_REQUIRED <= set(metadata)
            or set(metadata) - PLAN_METADATA_REQUIRED - PLAN_METADATA_OPTIONAL
        ):
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        if (
            not TRANSACTION_ID.fullmatch(str(metadata.get("transaction_id", "")))
            or not BACKUP_ID.fullmatch(str(metadata.get("backup_id", "")))
            or not self.valid_generation(metadata.get("source_generation"))
            or not self.valid_generation(metadata.get("target_generation"))
            or not self.valid_critical_set(metadata.get("critical_set_before"))
            or not self.valid_critical_set(metadata.get("critical_set_after"))
            or not self.valid_hash(metadata.get("unknown_fields_sha256"), nullable=True)
        ):
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        migration_path_present = "migration_path" in metadata
        migration_path_hash_present = "migration_path_sha256" in metadata
        if migration_path_present != migration_path_hash_present or (
            migration_path_present
            and (
                not self.valid_migration_path(metadata.get("migration_path"))
                or not self.valid_hash(metadata.get("migration_path_sha256"))
                or canonical_hash(metadata["migration_path"])
                != metadata["migration_path_sha256"]
            )
        ):
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        optional_patterns = {
            "migration_id": re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$"),
            "restored_backup_id": BACKUP_ID,
            "rolled_back_transaction_id": TRANSACTION_ID,
        }
        if any(
            field in metadata
            and (
                not isinstance(metadata[field], str)
                or pattern.fullmatch(metadata[field]) is None
            )
            for field, pattern in optional_patterns.items()
        ):
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        allowed_optional = {
            "initialize": set(),
            "refresh": set(),
            "migrate": {"migration_id", "migration_path", "migration_path_sha256"},
            "repair": {"restored_backup_id"},
            "rollback": {"rolled_back_transaction_id"},
        }[plan["operation"]]
        if (set(metadata) & PLAN_METADATA_OPTIONAL) - allowed_optional:
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        before_catalog: Any = None
        after_catalog: Any = None
        current_catalog = self.target_bytes(CATALOG_REL)
        if current_catalog is not None:
            try:
                before_catalog = strict_document(current_catalog)
                after_catalog = deepcopy(before_catalog)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                before_catalog = None
                after_catalog = None
        catalog_change = next(
            (change for change in changes if change["path"] == CATALOG_REL),
            None,
        )
        if catalog_change is not None:
            try:
                before_content = decoded(catalog_change["before_base64"])
                after_content = decoded(catalog_change["after_base64"])
                before_catalog = (
                    strict_document(before_content) if before_content is not None else None
                )
                after_catalog = (
                    strict_document(after_content) if after_content is not None else None
                )
            except (
                TypeError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
            ):
                return ["CONTINUITY_PLAN_CHANGES_INVALID"]
        if (
            metadata["source_generation"]
            != (
                before_catalog.get("schema_version")
                if isinstance(before_catalog, dict)
                else None
            )
            or metadata["target_generation"]
            != (
                after_catalog.get("schema_version")
                if isinstance(after_catalog, dict)
                else None
            )
            or metadata["critical_set_before"] != self.critical_set(before_catalog)
            or metadata["critical_set_after"] != self.critical_set(after_catalog)
            or inventory_paths != self.catalog_source_paths(after_catalog)
        ):
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        path = metadata.get("migration_path")
        generation_two_migration = (
            plan["operation"] == "migrate" and metadata["target_generation"] == 2
        )
        if generation_two_migration:
            extensions = (
                after_catalog.get("migration_extensions")
                if isinstance(after_catalog, dict)
                else None
            )
            if (
                not isinstance(path, list)
                or path[0]["source_generation"] != metadata["source_generation"]
                or path[-1]["target_generation"] != metadata["target_generation"]
                or not isinstance(extensions, list)
                or len(extensions) != len(path)
            ):
                return ["CONTINUITY_PLAN_METADATA_INVALID"]
            for hop, extension in zip(path, extensions, strict=True):
                fields = extension.get("fields") if isinstance(extension, dict) else None
                if (
                    not isinstance(extension, dict)
                    or set(extension)
                    != {"source_generation", "migration_id", "unknown_fields_sha256", "fields"}
                    or extension.get("source_generation") != hop["source_generation"]
                    or extension.get("migration_id") != hop["migration_id"]
                    or extension.get("unknown_fields_sha256")
                    != hop["unknown_fields_sha256"]
                    or not isinstance(fields, dict)
                    or canonical_hash(fields) != extension.get("unknown_fields_sha256")
                ):
                    return ["CONTINUITY_PLAN_METADATA_INVALID"]
            if metadata["unknown_fields_sha256"] != canonical_hash(
                [item["unknown_fields_sha256"] for item in path]
            ):
                return ["CONTINUITY_PLAN_METADATA_INVALID"]
        elif migration_path_present:
            return ["CONTINUITY_PLAN_METADATA_INVALID"]
        return []
