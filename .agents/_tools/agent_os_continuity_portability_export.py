#!/usr/bin/env python3
"""Export domain behavior for AOS-15 continuity portability.

This internal mixin owns provider-driven export closure, deterministic manifests,
Git provenance, bundle inspection, export planning, apply preparation, cleanup
selection, and external-unverified receipt binding. It does not own restore writes.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    canonical_hash,
    json_bytes,
    parse_time,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity import validate_catalog_shape
from agent_os_continuity_portability_foundation import (
    FULL_COMMIT,
    artifact_entry_id,
    artifact_id,
    lexical_absolute,
    project_relative_from_agent,
    read_regular,
    read_regular_bounded,
    scan_tree_bounded,
)
from agent_os_continuity_portability_retention_archive import (
    POLICY_AGENT_REL,
    RETENTION_CLASSES,
)
from agent_os_continuity_transactions import strict_document
from agent_os_paths import portable_collision_key, portable_relative, safe_join

EXPORT_MANIFEST_NAME = "continuity-export-manifest.json"
BUNDLE_ID = re.compile(r"^continuity-export-[0-9a-f]{24}$")
ENTRY_ID = re.compile(r"^continuity-entry-[0-9a-f]{24}$")
PRIVACY_CLASSES = {
    "public-metadata",
    "project-internal",
    "sensitive-reference",
}
EXPORT_FIELDS = {
    "schema_version",
    "bundle_id",
    "bundle_version",
    "project_id",
    "created_at",
    "source_git_head",
    "binding_sha256",
    "adapter_fingerprint_sha256",
    "core_manifest_sha256",
    "record_type_registry",
    "recovery_profile",
    "retention_policy",
    "catalog",
    "entries",
    "entry_count",
    "total_bytes",
    "inventory_sha256",
    "raw_conversation_stored",
    "prompt_stored",
    "chain_of_thought_stored",
    "secret_stored",
    "source_deleted",
    "commit_created",
    "push_performed",
    "content_sha256",
}
EXPORT_ENTRY_FIELDS = {
    "entry_id",
    "canonical_path",
    "storage_path",
    "canonical_owner",
    "restore_mode",
    "present",
    "bytes",
    "sha256",
    "privacy_class",
    "retention_class",
    "reference_ids",
}
CATALOG_DESCRIPTOR_FIELDS = {
    "schema_version",
    "catalog_revision",
    "catalog_sha256",
    "migration_extensions_sha256",
}
ACTIVE_CATALOG_GENERATION = 2
RECOVERY_AUTHORITY_PREFIXES = (
    ".agents/project/context/continuity-archives/",
    ".agents/project/context/continuity-backups/",
    ".agents/project/context/continuity-portability-receipts/",
    ".agents/project/context/continuity-restore-backups/",
    ".agents/project/context/continuity-transactions/",
)

_CATALOG_AGENT_REL = "project/context/continuity.json"
_PROJECTION_AGENT_REL = "project/context/continuity-projection.json"
_BINDING_AGENT_REL = "project/project-binding.json"
_FINGERPRINT_AGENT_REL = "project/adapter-fingerprint.json"
_CORE_MANIFEST_AGENT_REL = "_manifest/base-release-manifest.json"
_REGISTRY_AGENT_REL = "memory/continuity-record-types.json"
_PROFILE_AGENT_REL = "memory/continuity-recovery-profiles.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _valid_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = parse_time(value)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


class ContinuityExportMixin:
    def add_inventory_source(
        self,
        inventory: dict[str, dict[str, Any]],
        path: str,
        *,
        privacy_class: str,
        retention_class: str,
        reference_id: str,
        required: bool,
        force_verify_only: bool = False,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        try:
            canonical = portable_relative(path, canonical=True)
            source = self.project_path(canonical)
        except ValueError:
            return [{"code": "PORTABILITY_SOURCE_PATH_UNSAFE", "path": path}]
        if self.path_is_link_like(source):
            return [{"code": "PORTABILITY_SOURCE_SYMLINK", "path": canonical}]
        policy, _policy_errors = self.policy()
        maximum = (
            policy["bounds"]["max_file_bytes"]
            if policy is not None
            else 8388608
        )
        content, read_error = read_regular_bounded(source, maximum)
        if (
            read_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
            and source.exists()
        ):
            return [
                {
                    "code": "PORTABILITY_FILE_BOUND_EXCEEDED",
                    "path": canonical,
                }
            ]
        if content is None and source.exists():
            return [
                {
                    "code": "PORTABILITY_SOURCE_NOT_REGULAR",
                    "path": canonical,
                }
            ]
        if content is None and required:
            return [{"code": "PORTABILITY_REQUIRED_SOURCE_MISSING", "path": canonical}]
        self.merge_inventory_content(
            inventory,
            canonical,
            content,
            privacy_class=privacy_class,
            retention_class=retention_class,
            reference_id=reference_id,
            force_verify_only=force_verify_only,
        )
        return issues

    def merge_inventory_content(
        self,
        inventory: dict[str, dict[str, Any]],
        canonical: str,
        content: bytes | None,
        *,
        privacy_class: str,
        retention_class: str,
        reference_id: str,
        force_verify_only: bool = False,
    ) -> None:
        owner, restore_mode = self.derived_owner_mode(canonical)
        if force_verify_only:
            restore_mode = "verify-only"
        existing = inventory.get(canonical)
        if existing is None:
            inventory[canonical] = {
                "content": content,
                "canonical_owner": owner,
                "restore_mode": restore_mode,
                "privacy_class": privacy_class,
                "retention_class": retention_class,
                "reference_ids": {reference_id} if reference_id else set(),
            }
        else:
            existing["reference_ids"].add(reference_id)
            if owner == "core" or restore_mode == "verify-only":
                existing["restore_mode"] = "verify-only"
            if owner == "core":
                existing["canonical_owner"] = "core"
            privacy_rank = {
                "public-metadata": 0,
                "project-internal": 1,
                "sensitive-reference": 2,
            }
            retention_rank = {
                "advisory": 0,
                "operational": 1,
                "evidence": 2,
                "critical-history": 3,
                "critical-active": 4,
            }
            if privacy_rank[privacy_class] > privacy_rank[existing["privacy_class"]]:
                existing["privacy_class"] = privacy_class
            if (
                retention_rank[retention_class]
                > retention_rank[existing["retention_class"]]
            ):
                existing["retention_class"] = retention_class

    def context_closure(
        self,
        inventory: dict[str, dict[str, Any]],
        context_reference_id: str,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        policy, policy_errors = self.policy()
        if policy is None:
            return [{"code": code} for code in policy_errors]
        manifest_path = self.agent_path("project/context/context-manifest.json")
        content, content_error = read_regular_bounded(
            manifest_path,
            policy["bounds"]["max_manifest_bytes"],
        )
        if content is None:
            return [
                {
                    "code": (
                        "PORTABILITY_CONTEXT_MANIFEST_BOUND_EXCEEDED"
                        if content_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
                        else "PORTABILITY_CONTEXT_MANIFEST_MISSING"
                    )
                }
            ]
        try:
            manifest = strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return [{"code": "PORTABILITY_CONTEXT_MANIFEST_INVALID"}]
        if not isinstance(manifest, dict):
            return [{"code": "PORTABILITY_CONTEXT_MANIFEST_INVALID"}]
        agent_paths: list[tuple[str, str]] = []
        for source in manifest.get("sources", []):
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                agent_paths.append((source["path"], "critical-active"))
        for field in ("active_task_ledger", "projection"):
            if isinstance(manifest.get(field), str):
                agent_paths.append((manifest[field], "critical-active"))
        for relative, retention_class in agent_paths:
            issues.extend(
                self.add_inventory_source(
                    inventory,
                    project_relative_from_agent(relative),
                    privacy_class="project-internal",
                    retention_class=retention_class,
                    reference_id=context_reference_id,
                    required=True,
                )
            )
        handoff_directory = manifest.get("handoff_directory")
        handoff_paths: list[Path] = []
        if isinstance(handoff_directory, str):
            try:
                handoff_root = self.agent_path(handoff_directory)
            except ValueError:
                issues.append({"code": "PORTABILITY_HANDOFF_DIRECTORY_UNSAFE"})
            else:
                if self.path_is_link_like(handoff_root) or not handoff_root.is_dir():
                    issues.append({"code": "PORTABILITY_HANDOFF_DIRECTORY_INVALID"})
                else:
                    try:
                        visited = 0
                        with os.scandir(handoff_root) as iterator:
                            for item in iterator:
                                visited += 1
                                if visited > policy["bounds"]["max_entries"]:
                                    issues.append(
                                        {
                                            "code": "PORTABILITY_ENTRY_BOUND_EXCEEDED"
                                        }
                                    )
                                    handoff_paths = []
                                    break
                                if not item.name.endswith(".json"):
                                    continue
                                handoff_paths.append(Path(item.path))
                    except OSError:
                        issues.append(
                            {"code": "PORTABILITY_HANDOFF_DIRECTORY_INVALID"}
                        )
                    handoff_paths = sorted(handoff_paths)
                    if any(self.path_is_link_like(path) for path in handoff_paths):
                        issues.append({"code": "PORTABILITY_HANDOFF_SYMLINK"})
                    for path in handoff_paths:
                        relative = path.relative_to(self.root).as_posix()
                        issues.extend(
                            self.add_inventory_source(
                                inventory,
                                project_relative_from_agent(relative),
                                privacy_class="project-internal",
                                retention_class="critical-history",
                                reference_id=context_reference_id,
                                required=True,
                            )
                        )
        transitive_documents: list[tuple[str, bytes]] = []
        for relative, _retention in agent_paths:
            candidate, _candidate_error = read_regular_bounded(
                self.agent_path(relative),
                policy["bounds"]["max_file_bytes"],
            )
            if candidate is not None and relative.endswith(".json"):
                transitive_documents.append(
                    (project_relative_from_agent(relative), candidate)
                )
        for path in handoff_paths:
            candidate, _candidate_error = read_regular_bounded(
                path,
                policy["bounds"]["max_file_bytes"],
            )
            if candidate is not None:
                transitive_documents.append(
                    (path.relative_to(self.project_root).as_posix(), candidate)
                )
        for parent_path, raw in transitive_documents:
            try:
                document = strict_document(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                continue
            evidence_paths: set[str] = set()
            if isinstance(document, dict):
                for record in document.get("records", []):
                    if isinstance(record, dict):
                        for reference in record.get("source_refs", []):
                            if isinstance(reference, dict) and isinstance(
                                reference.get("path"), str
                            ):
                                evidence_paths.add(reference["path"])
                for task in document.get("tasks", []):
                    if isinstance(task, dict):
                        evidence_paths.update(
                            item
                            for item in task.get("evidence", [])
                            if isinstance(item, str)
                        )
                evidence_paths.update(
                    item.get("path")
                    for item in document.get("evidence", [])
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                )
            for evidence_path in sorted(evidence_paths):
                issues.extend(
                    self.add_inventory_source(
                        inventory,
                        evidence_path,
                        privacy_class="project-internal",
                        retention_class="evidence",
                        reference_id=context_reference_id,
                        required=True,
                    )
                )
        return issues

    def recovery_closure(
        self,
        inventory: dict[str, dict[str, Any]],
        maximum_entries: int,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        discovered: list[str] = []
        walked = 0
        maximum_walked = maximum_entries * 2 + 16
        for prefix in RECOVERY_AUTHORITY_PREFIXES:
            directory = self.project_path(prefix.rstrip("/"))
            if not directory.exists():
                continue
            if self.path_is_link_like(directory) or not directory.is_dir():
                issues.append(
                    {
                        "code": "PORTABILITY_RECOVERY_DIRECTORY_INVALID",
                        "path": prefix.rstrip("/"),
                    }
                )
                continue
            files, visited, scan_error, error_path = scan_tree_bounded(
                directory,
                maximum_walked - walked,
            )
            walked += visited
            if scan_error == "bound":
                return [
                    *issues,
                    {"code": "PORTABILITY_ENTRY_BOUND_EXCEEDED"},
                ]
            if scan_error is not None:
                code = (
                    "PORTABILITY_RECOVERY_SYMLINK"
                    if scan_error == "symlink"
                    else "PORTABILITY_RECOVERY_DIRECTORY_INVALID"
                )
                issue: dict[str, Any] = {"code": code}
                if error_path is not None:
                    try:
                        issue["path"] = error_path.relative_to(
                            self.project_root
                        ).as_posix()
                    except ValueError:
                        issue["path"] = prefix.rstrip("/")
                issues.append(issue)
                continue
            for path in files:
                discovered.append(path.relative_to(self.project_root).as_posix())
                if len(discovered) > maximum_entries:
                    return [
                        *issues,
                        {"code": "PORTABILITY_ENTRY_BOUND_EXCEEDED"},
                    ]
        for path in sorted(discovered):
            issues.extend(
                self.add_inventory_source(
                    inventory,
                    path,
                    privacy_class="project-internal",
                    retention_class="critical-history",
                    reference_id="continuity-recovery-artifact",
                    required=True,
                )
            )
        return issues

    def export_inventory(
        self,
        preflight: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        catalog = preflight["catalog"]
        policy = preflight["policy"]
        registry = self.document(_REGISTRY_AGENT_REL)
        owner_by_type = {
            item["record_type"]: item["canonical_owner"]
            for item in registry.get("types", [])
            if isinstance(item, dict)
        }
        inventory: dict[str, dict[str, Any]] = {}
        issues: list[dict[str, Any]] = []
        context_reference_id: str | None = None
        for reference in catalog["references"]:
            source = reference["source"]
            path = source["path"]
            required = (
                reference["requirement"] == "required"
                or source.get("sha256") is not None
            )
            force_verify = owner_by_type.get(reference["record_type"]) == "core"
            issues.extend(
                self.add_inventory_source(
                    inventory,
                    path,
                    privacy_class=reference["privacy_class"],
                    retention_class=reference["retention_class"],
                    reference_id=reference["reference_id"],
                    required=required,
                    force_verify_only=force_verify,
                )
            )
            if reference["record_type"] == "context-manifest":
                context_reference_id = reference["reference_id"]
        extras = [
            (
                project_relative_from_agent(_CATALOG_AGENT_REL),
                "project-internal",
                "critical-active",
                "continuity-catalog",
                False,
            ),
            (
                project_relative_from_agent(_PROJECTION_AGENT_REL),
                "project-internal",
                "critical-active",
                "continuity-projection",
                False,
            ),
            (
                project_relative_from_agent(_FINGERPRINT_AGENT_REL),
                "project-internal",
                "critical-active",
                "adapter-fingerprint",
                True,
            ),
            (
                project_relative_from_agent(_REGISTRY_AGENT_REL),
                "public-metadata",
                "critical-active",
                "continuity-registry",
                True,
            ),
            (
                project_relative_from_agent(_PROFILE_AGENT_REL),
                "public-metadata",
                "critical-active",
                "continuity-profile",
                True,
            ),
            (
                project_relative_from_agent(POLICY_AGENT_REL),
                "public-metadata",
                "critical-active",
                "retention-policy",
                True,
            ),
        ]
        for path, privacy, retention, reference_id, force_verify in extras:
            required = path != project_relative_from_agent(_PROJECTION_AGENT_REL)
            issues.extend(
                self.add_inventory_source(
                    inventory,
                    path,
                    privacy_class=privacy,
                    retention_class=retention,
                    reference_id=reference_id,
                    required=required,
                    force_verify_only=force_verify,
                )
            )
        if context_reference_id is None:
            issues.append({"code": "PORTABILITY_CONTEXT_PROVIDER_MISSING"})
        else:
            issues.extend(self.context_closure(inventory, context_reference_id))
        issues.extend(
            self.recovery_closure(
                inventory,
                policy["bounds"]["max_entries"],
            )
        )
        collision_paths: dict[str, str] = {}
        for path in sorted(inventory):
            try:
                collision_key = portable_collision_key(path, canonical=True)
            except ValueError:
                issues.append({"code": "PORTABILITY_SOURCE_PATH_UNSAFE", "path": path})
                continue
            previous = collision_paths.get(collision_key)
            if previous is not None and previous != path:
                issues.append(
                    {
                        "code": "PORTABILITY_SOURCE_PATH_COLLISION",
                        "path": path,
                        "collides_with": previous,
                    }
                )
            else:
                collision_paths[collision_key] = path
        entries: list[dict[str, Any]] = []
        total_bytes = 0
        bounds = policy["bounds"]
        for path in sorted(inventory):
            item = inventory[path]
            content = item["content"]
            present = content is not None
            digest = sha256_bytes(content) if content is not None else None
            size = len(content) if content is not None else 0
            if size > bounds["max_file_bytes"]:
                issues.append(
                    {
                        "code": "PORTABILITY_FILE_BOUND_EXCEEDED",
                        "path": path,
                        "bytes": size,
                    }
                )
            if item["privacy_class"] == "sensitive-reference" and present:
                issues.append(
                    {"code": "PORTABILITY_SENSITIVE_PLAINTEXT_FORBIDDEN", "path": path}
                )
            if content is not None:
                privacy_error = self.privacy_error(content, path)
                if privacy_error:
                    issues.append({"code": privacy_error, "path": path})
            entry_id = artifact_entry_id(path, present, digest)
            entries.append(
                {
                    "entry_id": entry_id,
                    "canonical_path": path,
                    "storage_path": f"files/{entry_id}.bin" if present else None,
                    "canonical_owner": item["canonical_owner"],
                    "restore_mode": item["restore_mode"],
                    "present": present,
                    "bytes": size,
                    "sha256": digest,
                    "privacy_class": item["privacy_class"],
                    "retention_class": item["retention_class"],
                    "reference_ids": sorted(
                        ref for ref in item["reference_ids"] if ref
                    ),
                }
            )
            total_bytes += size
        if len(entries) > bounds["max_entries"]:
            issues.append(
                {
                    "code": "PORTABILITY_ENTRY_BOUND_EXCEEDED",
                    "entries": len(entries),
                }
            )
        if total_bytes > bounds["max_total_bytes"]:
            issues.append(
                {
                    "code": "PORTABILITY_TOTAL_BOUND_EXCEEDED",
                    "bytes": total_bytes,
                }
            )
        return entries, issues

    def validate_export_git_provenance(
        self,
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        commit = str(manifest.get("source_git_head", ""))
        tree = self.git_tree(commit)
        if tree is None:
            return [{"code": "PORTABILITY_SOURCE_COMMIT_NOT_REACHABLE"}]
        policy, policy_errors = self.policy()
        if policy is None:
            return [{"code": code} for code in policy_errors]

        cache: dict[str, bytes | None] = {}
        issues: list[dict[str, Any]] = []
        inventory: dict[str, dict[str, Any]] = {}

        def source(path: str) -> bytes | None:
            try:
                canonical = portable_relative(path, canonical=True)
            except ValueError:
                issues.append(
                    {"code": "PORTABILITY_SOURCE_PATH_UNSAFE", "path": path}
                )
                return None
            if canonical in cache:
                return cache[canonical]
            content, error = self.git_blob_at(commit, canonical, tree)
            if error:
                issues.append({"code": error, "path": canonical})
            cache[canonical] = content
            return content

        def add(
            path: str,
            *,
            privacy_class: str,
            retention_class: str,
            reference_id: str,
            required: bool,
            force_verify_only: bool = False,
        ) -> None:
            try:
                canonical = portable_relative(path, canonical=True)
            except ValueError:
                issues.append(
                    {"code": "PORTABILITY_SOURCE_PATH_UNSAFE", "path": path}
                )
                return
            content = source(canonical)
            if content is None and required:
                issues.append(
                    {
                        "code": "PORTABILITY_REQUIRED_SOURCE_MISSING_AT_COMMIT",
                        "path": canonical,
                    }
                )
            self.merge_inventory_content(
                inventory,
                canonical,
                content,
                privacy_class=privacy_class,
                retention_class=retention_class,
                reference_id=reference_id,
                force_verify_only=force_verify_only,
            )

        catalog_path = project_relative_from_agent(_CATALOG_AGENT_REL)
        registry_path = project_relative_from_agent(_REGISTRY_AGENT_REL)
        profile_path = project_relative_from_agent(_PROFILE_AGENT_REL)
        policy_path = project_relative_from_agent(POLICY_AGENT_REL)
        binding_path = project_relative_from_agent(_BINDING_AGENT_REL)
        fingerprint_path = project_relative_from_agent(_FINGERPRINT_AGENT_REL)
        core_manifest_path = project_relative_from_agent(_CORE_MANIFEST_AGENT_REL)
        authority_paths = {
            "binding_sha256": binding_path,
            "adapter_fingerprint_sha256": fingerprint_path,
            "core_manifest_sha256": core_manifest_path,
        }
        authority_bytes = {
            field: source(path) for field, path in authority_paths.items()
        }
        raw_catalog = source(catalog_path)
        raw_registry = source(registry_path)
        raw_profile = source(profile_path)
        raw_policy = source(policy_path)
        if any(
            content is None
            for content in (
                raw_catalog,
                raw_registry,
                raw_profile,
                raw_policy,
                *authority_bytes.values(),
            )
        ):
            issues.append({"code": "PORTABILITY_SOURCE_AUTHORITY_INCOMPLETE"})
            return issues
        try:
            catalog = strict_document(raw_catalog)
            registry = strict_document(raw_registry)
            source_policy = strict_document(raw_policy)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return [*issues, {"code": "PORTABILITY_SOURCE_AUTHORITY_INVALID"}]
        if (
            not isinstance(catalog, dict)
            or validate_catalog_shape(catalog)
            or not isinstance(registry, dict)
            or not isinstance(source_policy, dict)
        ):
            return [*issues, {"code": "PORTABILITY_SOURCE_AUTHORITY_INVALID"}]
        owner_by_type = {
            item["record_type"]: item["canonical_owner"]
            for item in registry.get("types", [])
            if isinstance(item, dict)
            and isinstance(item.get("record_type"), str)
            and isinstance(item.get("canonical_owner"), str)
        }
        header_expectations = {
            "project_id": catalog.get("project_id"),
            "created_at": catalog.get("updated_at"),
            "binding_sha256": sha256_bytes(authority_bytes["binding_sha256"]),
            "adapter_fingerprint_sha256": sha256_bytes(
                authority_bytes["adapter_fingerprint_sha256"]
            ),
            "core_manifest_sha256": sha256_bytes(
                authority_bytes["core_manifest_sha256"]
            ),
        }
        if any(manifest.get(field) != expected for field, expected in header_expectations.items()):
            issues.append({"code": "PORTABILITY_SOURCE_AUTHORITY_MISMATCH"})
        manifest_catalog = manifest.get("catalog", {})
        if (
            manifest_catalog.get("schema_version")
            != catalog.get("schema_version")
            or manifest_catalog.get("catalog_revision")
            != catalog.get("catalog_revision")
            or manifest_catalog.get("catalog_sha256") != sha256_bytes(raw_catalog)
            or manifest_catalog.get("migration_extensions_sha256")
            != canonical_hash(catalog.get("migration_extensions", []))
            or manifest.get("record_type_registry")
            != catalog.get("record_type_registry")
            or manifest.get("record_type_registry", {}).get("registry_sha256")
            != sha256_bytes(raw_registry)
            or manifest.get("recovery_profile")
            != catalog.get("recovery_profile")
            or manifest.get("recovery_profile", {}).get("profile_sha256")
            != sha256_bytes(raw_profile)
            or manifest.get("retention_policy", {}).get("policy_sha256")
            != sha256_bytes(raw_policy)
            or manifest.get("retention_policy", {}).get("policy_id")
            != source_policy.get("policy_id")
            or manifest.get("retention_policy", {}).get("policy_version")
            != source_policy.get("policy_version")
        ):
            issues.append({"code": "PORTABILITY_SOURCE_AUTHORITY_MISMATCH"})

        context_reference_id: str | None = None
        for reference in catalog["references"]:
            source_reference = reference["source"]
            reference_path = source_reference["path"]
            required = (
                reference["requirement"] == "required"
                or source_reference.get("sha256") is not None
            )
            force_verify = owner_by_type.get(reference["record_type"]) == "core"
            add(
                reference_path,
                privacy_class=reference["privacy_class"],
                retention_class=reference["retention_class"],
                reference_id=reference["reference_id"],
                required=required,
                force_verify_only=force_verify,
            )
            content = source(reference_path)
            if source_reference.get("sha256") is not None and (
                content is None
                or sha256_bytes(content) != source_reference.get("sha256")
            ):
                issues.append(
                    {
                        "code": "PORTABILITY_SOURCE_CATALOG_HASH_MISMATCH",
                        "path": reference_path,
                    }
                )
            if reference["record_type"] == "context-manifest":
                context_reference_id = reference["reference_id"]

        extras = (
            (catalog_path, "project-internal", "critical-active", "continuity-catalog", False, True),
            (
                project_relative_from_agent(_PROJECTION_AGENT_REL),
                "project-internal",
                "critical-active",
                "continuity-projection",
                False,
                False,
            ),
            (fingerprint_path, "project-internal", "critical-active", "adapter-fingerprint", True, True),
            (registry_path, "public-metadata", "critical-active", "continuity-registry", True, True),
            (profile_path, "public-metadata", "critical-active", "continuity-profile", True, True),
            (policy_path, "public-metadata", "critical-active", "retention-policy", True, True),
        )
        for (
            path,
            privacy_class,
            retention_class,
            reference_id,
            force_verify,
            required,
        ) in extras:
            add(
                path,
                privacy_class=privacy_class,
                retention_class=retention_class,
                reference_id=reference_id,
                required=required,
                force_verify_only=force_verify,
            )

        if context_reference_id is None:
            issues.append({"code": "PORTABILITY_CONTEXT_PROVIDER_MISSING"})
        else:
            context_manifest_path = next(
                (
                    item["source"]["path"]
                    for item in catalog["references"]
                    if item["record_type"] == "context-manifest"
                ),
                project_relative_from_agent("project/context/context-manifest.json"),
            )
            raw_context_manifest = source(context_manifest_path)
            try:
                context_manifest = (
                    strict_document(raw_context_manifest)
                    if raw_context_manifest is not None
                    else None
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                context_manifest = None
            if not isinstance(context_manifest, dict):
                issues.append({"code": "PORTABILITY_CONTEXT_MANIFEST_INVALID"})
            else:
                transitive_paths: list[str] = []
                for item in context_manifest.get("sources", []):
                    if isinstance(item, dict) and isinstance(item.get("path"), str):
                        transitive_paths.append(project_relative_from_agent(item["path"]))
                for field in ("active_task_ledger", "projection"):
                    if isinstance(context_manifest.get(field), str):
                        transitive_paths.append(
                            project_relative_from_agent(context_manifest[field])
                        )
                for path in transitive_paths:
                    add(
                        path,
                        privacy_class="project-internal",
                        retention_class="critical-active",
                        reference_id=context_reference_id,
                        required=True,
                    )
                handoff_paths: list[str] = []
                handoff_directory = context_manifest.get("handoff_directory")
                if isinstance(handoff_directory, str):
                    try:
                        handoff_prefix = (
                            project_relative_from_agent(handoff_directory).rstrip("/")
                            + "/"
                        )
                    except ValueError:
                        issues.append({"code": "PORTABILITY_HANDOFF_DIRECTORY_UNSAFE"})
                    else:
                        prefix_error = self.populate_git_tree_prefixes(
                            commit,
                            [handoff_prefix.rstrip("/")],
                            tree,
                            maximum_entries=policy["bounds"]["max_entries"],
                            maximum_output_bytes=min(
                                policy["bounds"]["max_total_bytes"],
                                policy["bounds"]["max_manifest_bytes"] * 2,
                            ),
                        )
                        if prefix_error is not None:
                            issues.append({"code": prefix_error})
                        else:
                            handoff_paths = sorted(
                                path
                                for path, (mode, object_type) in tree.items()
                                if path.startswith(handoff_prefix)
                                and path.endswith(".json")
                                and mode in {"100644", "100755"}
                                and object_type == "blob"
                            )
                        for path in handoff_paths:
                            add(
                                path,
                                privacy_class="project-internal",
                                retention_class="critical-history",
                                reference_id=context_reference_id,
                                required=True,
                            )
                for parent_path in [*transitive_paths, *handoff_paths]:
                    raw = source(parent_path)
                    if raw is None or not parent_path.endswith(".json"):
                        continue
                    try:
                        document = strict_document(raw)
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                        continue
                    evidence_paths: set[str] = set()
                    if isinstance(document, dict):
                        for record in document.get("records", []):
                            if isinstance(record, dict):
                                for reference in record.get("source_refs", []):
                                    if isinstance(reference, dict) and isinstance(
                                        reference.get("path"), str
                                    ):
                                        evidence_paths.add(reference["path"])
                        for task in document.get("tasks", []):
                            if isinstance(task, dict):
                                evidence_paths.update(
                                    item
                                    for item in task.get("evidence", [])
                                    if isinstance(item, str)
                                )
                        evidence_paths.update(
                            item.get("path")
                            for item in document.get("evidence", [])
                            if isinstance(item, dict)
                            and isinstance(item.get("path"), str)
                        )
                    for evidence_path in sorted(evidence_paths):
                        add(
                            evidence_path,
                            privacy_class="project-internal",
                            retention_class="evidence",
                            reference_id=context_reference_id,
                            required=True,
                        )

        recovery_prefix_error = self.populate_git_tree_prefixes(
            commit,
            [prefix.rstrip("/") for prefix in RECOVERY_AUTHORITY_PREFIXES],
            tree,
            maximum_entries=policy["bounds"]["max_entries"],
            maximum_output_bytes=min(
                policy["bounds"]["max_total_bytes"],
                policy["bounds"]["max_manifest_bytes"] * 2,
            ),
        )
        if recovery_prefix_error is not None:
            issues.append({"code": recovery_prefix_error})
        else:
            for path, (mode, object_type) in sorted(tree.items()):
                if not path.startswith(RECOVERY_AUTHORITY_PREFIXES):
                    continue
                if mode not in {"100644", "100755"} or object_type != "blob":
                    issues.append(
                        {"code": "PORTABILITY_RECOVERY_SYMLINK", "path": path}
                    )
                    continue
                add(
                    path,
                    privacy_class="project-internal",
                    retention_class="critical-history",
                    reference_id="continuity-recovery-artifact",
                    required=True,
                )

        entries: list[dict[str, Any]] = []
        total_bytes = 0
        bounds = policy["bounds"]
        for path in sorted(inventory):
            item = inventory[path]
            content = item["content"]
            present = content is not None
            digest = sha256_bytes(content) if content is not None else None
            size = len(content) if content is not None else 0
            if size > bounds["max_file_bytes"]:
                issues.append(
                    {
                        "code": "PORTABILITY_FILE_BOUND_EXCEEDED",
                        "path": path,
                        "bytes": size,
                    }
                )
            if item["privacy_class"] == "sensitive-reference" and present:
                issues.append(
                    {"code": "PORTABILITY_SENSITIVE_PLAINTEXT_FORBIDDEN", "path": path}
                )
            if content is not None:
                privacy_error = self.privacy_error(content, path)
                if privacy_error:
                    issues.append({"code": privacy_error, "path": path})
            entry_id = artifact_entry_id(path, present, digest)
            entries.append(
                {
                    "entry_id": entry_id,
                    "canonical_path": path,
                    "storage_path": f"files/{entry_id}.bin" if present else None,
                    "canonical_owner": item["canonical_owner"],
                    "restore_mode": item["restore_mode"],
                    "present": present,
                    "bytes": size,
                    "sha256": digest,
                    "privacy_class": item["privacy_class"],
                    "retention_class": item["retention_class"],
                    "reference_ids": sorted(
                        reference_id
                        for reference_id in item["reference_ids"]
                        if reference_id
                    ),
                }
            )
            total_bytes += size
        if (
            len(entries) > bounds["max_entries"]
            or total_bytes > bounds["max_total_bytes"]
        ):
            issues.append({"code": "PORTABILITY_SOURCE_CLOSURE_BOUND_EXCEEDED"})
        if entries != manifest.get("entries"):
            issues.append({"code": "PORTABILITY_SOURCE_CLOSURE_MISMATCH"})
        return issues

    def build_export_manifest(self) -> dict[str, Any]:
        preflight = self.preflight()
        if not preflight["ok"]:
            return {
                "ok": False,
                "reason_codes": preflight["reason_codes"],
                "preflight": {
                    "context_state": preflight["context_health"].get("state"),
                    "continuity_topology_state": preflight[
                        "continuity_health"
                    ].get("topology_state"),
                    "required_unavailable": preflight["required_unavailable"],
                },
            }
        entries, issues = self.export_inventory(preflight)
        if issues:
            return {
                "ok": False,
                "reason_codes": list(dict.fromkeys(item["code"] for item in issues)),
                "issues": issues,
            }
        catalog = preflight["catalog"]
        contracts = preflight["contracts"]
        policy = preflight["policy"]
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "bundle_id": "",
            "bundle_version": 1,
            "project_id": catalog["project_id"],
            "created_at": catalog["updated_at"],
            "source_git_head": preflight["head"],
            "binding_sha256": contracts["binding_sha256"],
            "adapter_fingerprint_sha256": contracts[
                "adapter_fingerprint_sha256"
            ],
            "core_manifest_sha256": contracts["core_manifest_sha256"],
            "record_type_registry": deepcopy(catalog["record_type_registry"]),
            "recovery_profile": deepcopy(catalog["recovery_profile"]),
            "retention_policy": {
                "policy_id": policy["policy_id"],
                "policy_version": policy["policy_version"],
                "policy_sha256": contracts["retention_policy_sha256"],
            },
            "catalog": {
                "schema_version": catalog["schema_version"],
                "catalog_revision": catalog["catalog_revision"],
                "catalog_sha256": sha256_bytes(
                    read_regular(self.agent_path(_CATALOG_AGENT_REL)) or b""
                ),
                "migration_extensions_sha256": canonical_hash(
                    catalog.get("migration_extensions", [])
                ),
            },
            "entries": entries,
            "entry_count": len(entries),
            "total_bytes": sum(item["bytes"] for item in entries),
            "inventory_sha256": canonical_hash(entries),
            "raw_conversation_stored": False,
            "prompt_stored": False,
            "chain_of_thought_stored": False,
            "secret_stored": False,
            "source_deleted": False,
            "commit_created": False,
            "push_performed": False,
        }
        manifest["bundle_id"] = artifact_id(
            manifest, "continuity-export-", "bundle_id"
        )
        manifest["content_sha256"] = receipt_hash(manifest)
        errors = self.validate_export_manifest(manifest)
        if errors:
            return {
                "ok": False,
                "reason_codes": errors,
            }
        provenance_issues = self.validate_export_git_provenance(manifest)
        if provenance_issues:
            return {
                "ok": False,
                "reason_codes": list(
                    dict.fromkeys(item["code"] for item in provenance_issues)
                ),
                "issues": provenance_issues,
            }
        if len(json_bytes(manifest)) > policy["bounds"]["max_manifest_bytes"]:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_MANIFEST_BOUND_EXCEEDED"],
            }
        return {"ok": True, "manifest": manifest}

    def validate_export_manifest(self, manifest: Any) -> list[str]:
        policy, policy_errors = self.policy()
        if policy is None:
            return policy_errors
        if not isinstance(manifest, dict) or set(manifest) != EXPORT_FIELDS:
            return ["PORTABILITY_MANIFEST_FIELDS_INVALID"]
        if (
            manifest.get("schema_version") != 1
            or manifest.get("bundle_version") != 1
            or not isinstance(manifest.get("bundle_id"), str)
            or BUNDLE_ID.fullmatch(manifest["bundle_id"]) is None
            or artifact_id(manifest, "continuity-export-", "bundle_id")
            != manifest["bundle_id"]
            or not isinstance(manifest.get("project_id"), str)
            or not 1 <= len(manifest["project_id"]) <= 128
            or not _valid_time(manifest.get("created_at"))
            or not isinstance(manifest.get("source_git_head"), str)
            or FULL_COMMIT.fullmatch(manifest["source_git_head"]) is None
            or any(
                not _valid_hash(manifest.get(field))
                for field in (
                    "binding_sha256",
                    "adapter_fingerprint_sha256",
                    "core_manifest_sha256",
                    "inventory_sha256",
                )
            )
            or any(
                manifest.get(field) is not False
                for field in (
                    "raw_conversation_stored",
                    "prompt_stored",
                    "chain_of_thought_stored",
                    "secret_stored",
                    "source_deleted",
                    "commit_created",
                    "push_performed",
                )
            )
            or manifest.get("content_sha256") != receipt_hash(manifest)
        ):
            return ["PORTABILITY_MANIFEST_INVALID"]
        registry = manifest.get("record_type_registry")
        profile = manifest.get("recovery_profile")
        retention = manifest.get("retention_policy")
        catalog = manifest.get("catalog")
        if (
            not isinstance(registry, dict)
            or set(registry)
            != {"registry_id", "registry_version", "registry_sha256"}
            or registry.get("registry_id") != "universal-continuity-record-types"
            or type(registry.get("registry_version")) is not int
            or registry["registry_version"] < 1
            or not _valid_hash(registry.get("registry_sha256"))
            or not isinstance(profile, dict)
            or set(profile) != {"profile_id", "profile_version", "profile_sha256"}
            or profile.get("profile_id") != "universal-project-continuity"
            or type(profile.get("profile_version")) is not int
            or profile["profile_version"] < 1
            or not _valid_hash(profile.get("profile_sha256"))
            or not isinstance(retention, dict)
            or set(retention) != {"policy_id", "policy_version", "policy_sha256"}
            or retention.get("policy_id") != "universal-continuity-retention"
            or retention.get("policy_version") != 1
            or not _valid_hash(retention.get("policy_sha256"))
            or not isinstance(catalog, dict)
            or set(catalog) != CATALOG_DESCRIPTOR_FIELDS
            or catalog.get("schema_version") != ACTIVE_CATALOG_GENERATION
            or type(catalog.get("catalog_revision")) is not int
            or catalog["catalog_revision"] < 1
            or not _valid_hash(catalog.get("catalog_sha256"))
            or not _valid_hash(catalog.get("migration_extensions_sha256"))
        ):
            return ["PORTABILITY_MANIFEST_CONTRACTS_INVALID"]
        entries = manifest.get("entries")
        bounds = policy["bounds"]
        if (
            not isinstance(entries, list)
            or not 1 <= len(entries) <= bounds["max_entries"]
        ):
            return ["PORTABILITY_MANIFEST_INVENTORY_INVALID"]
        paths: list[str] = []
        collision_paths: dict[str, str] = {}
        storage_paths: set[str] = set()
        total_bytes = 0
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != EXPORT_ENTRY_FIELDS:
                return ["PORTABILITY_MANIFEST_ENTRY_INVALID"]
            path = entry.get("canonical_path")
            try:
                canonical = portable_relative(str(path), canonical=True)
            except ValueError:
                return ["PORTABILITY_MANIFEST_ENTRY_PATH_INVALID"]
            if canonical != path or path in paths:
                return ["PORTABILITY_MANIFEST_ENTRY_PATH_INVALID"]
            collision_key = portable_collision_key(canonical, canonical=True)
            previous = collision_paths.get(collision_key)
            if previous is not None and previous != canonical:
                return ["PORTABILITY_MANIFEST_ENTRY_PATH_COLLISION"]
            collision_paths[collision_key] = canonical
            present = entry.get("present")
            digest = entry.get("sha256")
            size = entry.get("bytes")
            entry_id = entry.get("entry_id")
            storage_path = entry.get("storage_path")
            references = entry.get("reference_ids")
            expected_owner, expected_mode = self.derived_owner_mode(path)
            if (
                type(present) is not bool
                or not 1 <= len(canonical) <= 512
                or type(size) is not int
                or not 0 <= size <= bounds["max_file_bytes"]
                or not isinstance(entry_id, str)
                or ENTRY_ID.fullmatch(entry_id) is None
                or entry_id != artifact_entry_id(path, present, digest)
                or entry.get("canonical_owner") != expected_owner
                or entry.get("restore_mode") != expected_mode
                or entry.get("privacy_class") not in PRIVACY_CLASSES
                or entry.get("privacy_class") == "sensitive-reference"
                or entry.get("retention_class") not in RETENTION_CLASSES
                or not isinstance(references, list)
                or len(references) > 128
                or references != sorted(set(references))
                or any(
                    not isinstance(item, str) or not 1 <= len(item) <= 128
                    for item in references
                )
            ):
                return ["PORTABILITY_MANIFEST_ENTRY_INVALID"]
            if present:
                expected_storage = f"files/{entry_id}.bin"
                if (
                    not _valid_hash(digest)
                    or storage_path != expected_storage
                    or storage_path in storage_paths
                ):
                    return ["PORTABILITY_MANIFEST_ENTRY_INVALID"]
                storage_paths.add(storage_path)
            elif digest is not None or storage_path is not None or size != 0:
                return ["PORTABILITY_MANIFEST_ENTRY_INVALID"]
            paths.append(path)
            total_bytes += size
        if paths != sorted(paths):
            return ["PORTABILITY_MANIFEST_INVENTORY_INVALID"]
        if (
            manifest.get("entry_count") != len(entries)
            or manifest.get("total_bytes") != total_bytes
            or total_bytes > bounds["max_total_bytes"]
            or manifest.get("inventory_sha256") != canonical_hash(entries)
            or len(json_bytes(manifest)) > bounds["max_manifest_bytes"]
        ):
            return ["PORTABILITY_MANIFEST_INVENTORY_INVALID"]
        return []

    def inspect_bundle(self, source: str | Path) -> dict[str, Any]:
        policy, policy_errors = self.policy()
        if policy is None:
            return {"ok": False, "reason_codes": policy_errors}
        bundle_input = lexical_absolute(Path(source), self.project_root)
        if self.path_is_link_like(bundle_input):
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_BUNDLE_ROOT_SYMLINK"],
            }
        try:
            bundle = bundle_input.resolve(strict=True)
        except OSError:
            return {"ok": False, "reason_codes": ["PORTABILITY_BUNDLE_PATH_INVALID"]}
        if not bundle.is_dir():
            return {"ok": False, "reason_codes": ["PORTABILITY_BUNDLE_PATH_INVALID"]}
        manifest_path = bundle / EXPORT_MANIFEST_NAME
        content, manifest_error = read_regular_bounded(
            manifest_path,
            policy["bounds"]["max_manifest_bytes"],
        )
        if content is None:
            return {
                "ok": False,
                "reason_codes": [
                    (
                        "PORTABILITY_MANIFEST_BOUND_EXCEEDED"
                        if manifest_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
                        else "PORTABILITY_MANIFEST_MISSING_OR_UNREADABLE"
                    )
                ],
            }
        try:
            manifest = strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"ok": False, "reason_codes": ["PORTABILITY_MANIFEST_INVALID"]}
        errors = self.validate_export_manifest(manifest)
        if errors:
            return {"ok": False, "reason_codes": errors}
        provenance_issues = self.validate_export_git_provenance(manifest)
        if provenance_issues:
            return {
                "ok": False,
                "reason_codes": list(
                    dict.fromkeys(item["code"] for item in provenance_issues)
                ),
                "issues": provenance_issues,
            }
        actual_files: set[str] = set()
        files, _visited, scan_error, _error_path = scan_tree_bounded(
            bundle,
            policy["bounds"]["max_entries"] * 2 + 16,
        )
        if scan_error is not None:
            reason = {
                "bound": "PORTABILITY_BUNDLE_ENTRY_BOUND_EXCEEDED",
                "symlink": "PORTABILITY_BUNDLE_SYMLINK",
                "irregular": "PORTABILITY_BUNDLE_FILE_NOT_REGULAR",
                "unreadable": "PORTABILITY_BUNDLE_UNREADABLE",
            }[scan_error]
            return {"ok": False, "reason_codes": [reason]}
        actual_files.update(path.relative_to(bundle).as_posix() for path in files)
        expected_files = {EXPORT_MANIFEST_NAME}
        issues: list[dict[str, Any]] = []
        for entry in manifest["entries"]:
            if not entry["present"]:
                continue
            storage_path = entry["storage_path"]
            expected_files.add(storage_path)
            try:
                path = safe_join(bundle, storage_path, canonical=True)
            except ValueError:
                issues.append(
                    {
                        "code": "PORTABILITY_STORAGE_PATH_INVALID",
                        "entry_id": entry["entry_id"],
                    }
                )
                continue
            payload, payload_error = read_regular_bounded(
                path,
                policy["bounds"]["max_file_bytes"],
            )
            if (
                payload is None
                or len(payload) != entry["bytes"]
                or sha256_bytes(payload) != entry["sha256"]
            ):
                issues.append(
                    {
                        "code": "PORTABILITY_PAYLOAD_TAMPERED",
                        "entry_id": entry["entry_id"],
                        "cause": payload_error,
                    }
                )
                continue
            privacy_error = self.privacy_error(payload, entry["canonical_path"])
            if privacy_error:
                issues.append(
                    {
                        "code": privacy_error,
                        "entry_id": entry["entry_id"],
                    }
                )
        if actual_files != expected_files:
            issues.append(
                {
                    "code": "PORTABILITY_BUNDLE_FILE_SET_MISMATCH",
                    "missing": sorted(expected_files - actual_files),
                    "extra": sorted(actual_files - expected_files),
                }
            )
        if issues:
            return {
                "ok": False,
                "reason_codes": list(dict.fromkeys(item["code"] for item in issues)),
                "issues": issues,
            }
        return {
            "ok": True,
            "integrity_state": "valid",
            "authority_state": "unverified-until-restore",
            "bundle_path": str(bundle),
            "manifest": manifest,
            "manifest_sha256": sha256_bytes(content),
        }

    def export_destination(self, destination: str | Path) -> Path | None:
        lexical = lexical_absolute(Path(destination), self.project_root)
        parent = lexical.parent
        if (
            lexical in {self.project_root, self.root, Path(lexical.anchor)}
            or lexical.exists()
            or self.path_is_link_like(lexical)
            or not parent.exists()
            or not parent.is_dir()
            or self.path_is_link_like(parent)
        ):
            return None
        try:
            resolved_parent = parent.resolve(strict=True)
        except OSError:
            return None
        resolved = resolved_parent / lexical.name
        if (
            resolved in {self.project_root, self.root, Path(resolved.anchor)}
            or resolved.exists()
            or self.path_is_link_like(resolved)
            or self.path_is_link_like(resolved.parent)
        ):
            return None
        return resolved

    def plan_export(
        self, destination: str | Path, expiry_seconds: int = 900
    ) -> dict[str, Any]:
        try:
            destination_text = os.fspath(destination)
        except TypeError:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_DESTINATION_INVALID"],
            }
        if (
            not isinstance(destination_text, str)
            or not 1 <= len(destination_text) <= 4096
        ):
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_DESTINATION_INVALID"],
            }
        resolved = self.export_destination(destination)
        if resolved is None:
            return {"ok": False, "reason_codes": ["PORTABILITY_DESTINATION_INVALID"]}
        built = self.build_export_manifest()
        if not built.get("ok"):
            return built
        return self.create_portability_plan(
            "export",
            built["manifest"],
            str(resolved),
            {"bundle_kind": "offline-continuity"},
            expiry_seconds,
        )

    def prepare_export_apply(self, plan: dict[str, Any]) -> dict[str, Any]:
        destination = self.export_destination(plan["destination"])
        if destination is None or str(destination) != plan["destination"]:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_DESTINATION_DRIFT"],
            }
        built = self.build_export_manifest()
        if not built.get("ok"):
            return built
        return {
            "ok": True,
            "manifest": built["manifest"],
            "destination": destination,
        }

    @staticmethod
    def export_cleanup_target(destination: Path) -> tuple[Path, str]:
        return destination.parent, destination.name

    def validate_export_portability_receipt_artifact(
        self,
        receipt: dict[str, Any],
    ) -> list[str]:
        manifest = receipt.get("artifact_manifest")
        if (
            receipt["artifact_state"] != "external-unverified"
            or receipt["artifact_path"]
            != f"external-directory/{receipt['artifact_id']}"
            or not isinstance(manifest, dict)
            or self.validate_export_manifest(manifest)
            or self.validate_export_git_provenance(manifest)
            or sha256_bytes(json_bytes(manifest)) != receipt["manifest_sha256"]
            or manifest.get("inventory_sha256") != receipt["inventory_sha256"]
            or manifest.get("bundle_id") != receipt["artifact_id"]
            or manifest.get("project_id") != receipt["project_id"]
            or manifest.get("source_git_head") != receipt["base_commit"]
            or manifest.get("binding_sha256") != receipt["binding_sha256"]
            or manifest.get("adapter_fingerprint_sha256")
            != receipt["adapter_fingerprint_sha256"]
            or manifest.get("retention_policy", {}).get("policy_sha256")
            != receipt["retention_policy_sha256"]
        ):
            return ["PORTABILITY_RECEIPT_ARTIFACT_UNVERIFIABLE"]
        return []
