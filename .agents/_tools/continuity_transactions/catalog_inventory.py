from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_os_context_memory import canonical_hash, sha256_bytes
from agent_os_continuity import load_json
from agent_os_continuity_migration_chain import (
    MigrationChainError,
    resolve_migration_chain,
)
from continuity_transactions.contracts import (
    DEFAULT_SOURCE_PATHS,
    MIGRATION_FIELDS,
    MIGRATION_REGISTRY_FIELDS,
    MIGRATION_REGISTRY_REL,
    strict_document,
)

SUPPORTED_MIGRATION_PROVIDERS = {
    (0, 1): "builtin:continuity-catalog-draft-v0-to-v1",
    (1, 2): "builtin:continuity-catalog-v1-to-v2",
}


def read_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


# fmt: off
class CatalogInventoryMixin:
    def migration_registry(self) -> tuple[dict[tuple[int, int], dict[str, Any]], list[str]]:
        errors: list[str] = []
        try:
            document = load_json(self.path(MIGRATION_REGISTRY_REL))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {}, ["CONTINUITY_MIGRATION_REGISTRY_UNREADABLE"]
        if not isinstance(document, dict) or set(document) != MIGRATION_REGISTRY_FIELDS:
            return {}, ["CONTINUITY_MIGRATION_REGISTRY_FIELDS_INVALID"]
        if (
            document.get("schema_version") != 1
            or document.get("registry_id") != "universal-continuity-migrations"
            or type(document.get("registry_version")) is not int
            or document["registry_version"] < 1
        ):
            errors.append("CONTINUITY_MIGRATION_REGISTRY_INVALID")
        migrations = document.get("migrations")
        if not isinstance(migrations, list) or len(migrations) > 64:
            return {}, [*errors, "CONTINUITY_MIGRATION_REGISTRY_INVALID"]
        by_generation: dict[tuple[int, int], dict[str, Any]] = {}
        for entry in migrations:
            if not isinstance(entry, dict) or set(entry) != MIGRATION_FIELDS:
                errors.append("CONTINUITY_MIGRATION_ENTRY_INVALID")
                continue
            source = entry.get("source_generation")
            target = entry.get("target_generation")
            fields = entry.get("source_fields")
            key = (source, target)
            if (
                type(source) is not int
                or type(target) is not int
                or source < 0
                or target <= source
                or key in by_generation
                or not isinstance(entry.get("migration_id"), str)
                or entry.get("provider") != SUPPORTED_MIGRATION_PROVIDERS.get(key)
                or not isinstance(fields, list)
                or not fields
                or len(fields) != len(set(fields))
                or any(not isinstance(item, str) or not item for item in fields)
                or entry.get("preserve_reference_bytes") is not True
                or entry.get("reject_unknown_fields") is not True
                or entry.get("requires_backup") is not True
            ):
                errors.append("CONTINUITY_MIGRATION_ENTRY_INVALID")
                continue
            by_generation[key] = entry
        return by_generation, errors

    def migration_chain(
        self,
        source_generation: int,
        target_generation: int,
    ) -> tuple[list[dict[str, Any]] | None, list[str]]:
        migrations, errors = self.migration_registry()
        if errors:
            return None, errors
        try:
            chain = resolve_migration_chain(
                list(migrations.values()),
                source_generation,
                target_generation,
            )
        except MigrationChainError as error:
            return None, [error.reason_code]
        return chain, []

    def source_inventory(self, paths: set[str]) -> tuple[list[dict[str, Any]], str]:
        head = self.head()
        entries: list[dict[str, Any]] = []
        for relative in sorted(paths):
            path = self.project_path(relative)
            current = read_bytes(path)
            committed = self.git_blob(head, relative) if head else None
            entries.append(
                {
                    "path": relative,
                    "present": current is not None,
                    "sha256": sha256_bytes(current) if current is not None else None,
                    "head_sha256": sha256_bytes(committed) if committed is not None else None,
                    "clean": self.git_path_clean(relative),
                }
            )
        return entries, canonical_hash(entries)

    @staticmethod
    def critical_set(catalog: Any) -> list[str]:
        if not isinstance(catalog, dict) or not isinstance(catalog.get("references"), list):
            return []
        return sorted(
            {
                str(item.get("reference_id"))
                for item in catalog["references"]
                if isinstance(item, dict)
                and item.get("requirement") != "advisory"
                and item.get("lifecycle") == "active"
                and isinstance(item.get("reference_id"), str)
            }
        )

    @staticmethod
    def catalog_source_paths(catalog: Any) -> set[str]:
        paths = set(DEFAULT_SOURCE_PATHS)
        if not isinstance(catalog, dict):
            return paths
        for reference in catalog.get("references", []):
            if not isinstance(reference, dict):
                continue
            source = reference.get("source")
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                paths.add(source["path"])
        extension = catalog.get("project_record_type_registry")
        if isinstance(extension, dict) and isinstance(extension.get("path"), str):
            paths.add(extension["path"])
        return paths

    def head_document(self, relative: str) -> tuple[bytes | None, Any]:
        head = self.head()
        content = self.git_blob(head, relative) if head else None
        if content is None:
            return None, None
        try:
            return content, strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return content, None

    def source_descriptor(
        self,
        relative: str,
        schema_id: str | None,
        schema_version: int | None,
        *,
        missing_allowed: bool = False,
    ) -> tuple[dict[str, Any] | None, Any, list[str]]:
        content, document = self.head_document(relative)
        if content is None:
            if missing_allowed:
                return {
                    "path": relative,
                    "sha256": None,
                    "git_commit": None,
                    "schema_id": schema_id,
                    "schema_version": schema_version,
                }, None, []
            return None, None, ["CONTINUITY_REQUIRED_SOURCE_NOT_COMMITTED"]
        if schema_id is not None and not isinstance(document, dict):
            return None, None, ["CONTINUITY_SOURCE_DOCUMENT_INVALID"]
        return {
            "path": relative,
            "sha256": sha256_bytes(content),
            "git_commit": self.head(),
            "schema_id": schema_id,
            "schema_version": schema_version,
        }, document, []
