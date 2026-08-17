"""Restore target ordering, compatibility, and bounded diff analysis.

This mixin is imported by the stable restore facade. It never imports that facade,
so dependency direction remains one-way while public method lookup stays compatible.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from agent_os_context_memory import canonical_hash, sha256_bytes
from agent_os_continuity import validate_catalog_shape, validate_reference_shape
from agent_os_continuity_dependency_order import (
    DependencyOrderError,
    stable_dependency_order,
)
from agent_os_continuity_portability_foundation import read_regular_bounded
from agent_os_continuity_transactions import (
    ContinuityTransactionService,
    strict_document,
)
from agent_os_paths import safe_join

_CATALOG_PROJECT_REL = ".agents/project/context/continuity.json"


class RestoreTargetAnalysisMixin:
    """Compatibility-preserving target analysis methods for restore services."""

    def restore_migration_extension_path(self, catalog: dict[str, Any]) -> list[str]:
        """Validate that staged migration evidence forms one registered path."""
        extensions = catalog.get("migration_extensions", [])
        if not extensions:
            return []
        registry, registry_errors = ContinuityTransactionService(
            self.root
        ).migration_registry()
        if registry_errors:
            return ["PORTABILITY_RESTORE_MIGRATION_REGISTRY_INVALID"]
        previous_target: int | None = None
        migration_ids: set[str] = set()
        for extension in extensions:
            migration_id = extension["migration_id"]
            source_generation = extension["source_generation"]
            candidates = [
                entry
                for (source, _target), entry in registry.items()
                if source == source_generation and entry["migration_id"] == migration_id
            ]
            if (
                len(candidates) != 1
                or migration_id in migration_ids
                or (
                    previous_target is not None and source_generation != previous_target
                )
            ):
                return ["PORTABILITY_RESTORE_MIGRATION_PATH_INVALID"]
            migration_ids.add(migration_id)
            previous_target = candidates[0]["target_generation"]
        if previous_target != catalog.get("schema_version"):
            return ["PORTABILITY_RESTORE_MIGRATION_PATH_INVALID"]
        return []

    def restore_target_execution_order(
        self,
        staged_path: Path,
        manifest: dict[str, Any],
        targets: list[dict[str, Any]],
    ) -> tuple[list[str] | None, list[str]]:
        policy, policy_errors = self.policy()
        if policy is None:
            return None, policy_errors
        catalog_entries = [
            entry
            for entry in manifest.get("entries", [])
            if isinstance(entry, dict)
            and entry.get("canonical_path") == _CATALOG_PROJECT_REL
            and entry.get("present") is True
            and entry.get("reference_ids") == ["continuity-catalog"]
        ]
        if len(catalog_entries) != 1:
            return None, ["PORTABILITY_RESTORE_CATALOG_INVALID"]
        catalog_entry = catalog_entries[0]
        storage_path = catalog_entry.get("storage_path")
        if not isinstance(storage_path, str) or catalog_entry.get(
            "sha256"
        ) != manifest.get("catalog", {}).get("catalog_sha256"):
            return None, ["PORTABILITY_RESTORE_CATALOG_INVALID"]
        try:
            payload, _payload_error = read_regular_bounded(
                safe_join(staged_path, storage_path, canonical=True),
                policy["bounds"]["max_file_bytes"],
            )
            catalog = strict_document(payload) if payload is not None else None
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            return None, ["PORTABILITY_RESTORE_CATALOG_INVALID"]
        if (
            payload is None
            or sha256_bytes(payload) != catalog_entry.get("sha256")
            or not isinstance(catalog, dict)
            or catalog.get("project_id") != manifest.get("project_id")
        ):
            return None, ["PORTABILITY_RESTORE_CATALOG_INVALID"]
        manifest_catalog = manifest.get("catalog", {})
        if catalog.get("schema_version") != manifest_catalog.get("schema_version"):
            return None, ["PORTABILITY_RESTORE_GENERATION_INVALID"]
        if (
            catalog.get("catalog_revision")
            != manifest.get("catalog", {}).get("catalog_revision")
            or catalog.get("record_type_registry")
            != manifest.get("record_type_registry")
            or catalog.get("recovery_profile") != manifest.get("recovery_profile")
            or validate_catalog_shape(catalog)
        ):
            return None, ["PORTABILITY_RESTORE_CATALOG_INVALID"]
        if manifest_catalog.get("migration_extensions_sha256") != canonical_hash(
            catalog.get("migration_extensions", [])
        ):
            return None, ["PORTABILITY_RESTORE_EXTENSION_INVALID"]
        path_errors = self.restore_migration_extension_path(catalog)
        if path_errors:
            return None, path_errors
        references = catalog.get("references")
        if not isinstance(references, list) or any(
            validate_reference_shape(reference, index)
            for index, reference in enumerate(references)
        ):
            return None, ["PORTABILITY_RESTORE_CATALOG_INVALID"]
        known_references = {
            reference["reference_id"]
            for reference in references
            if isinstance(reference, dict)
            and isinstance(reference.get("reference_id"), str)
        }
        entry_by_id = {
            entry.get("entry_id"): entry
            for entry in manifest.get("entries", [])
            if isinstance(entry, dict)
        }
        order_targets = []
        for target in targets:
            entry = entry_by_id.get(target.get("entry_id"))
            if not isinstance(entry, dict):
                return None, ["PORTABILITY_RESTORE_DEPENDENCY_ORDER_INVALID"]
            order_targets.append(
                {
                    "entry_id": target["entry_id"],
                    "path": target["path"],
                    "reference_ids": [
                        reference_id
                        for reference_id in entry.get("reference_ids", [])
                        if reference_id in known_references
                    ],
                }
            )
        try:
            return stable_dependency_order(references, order_targets), []
        except DependencyOrderError as error:
            return None, [error.reason_code]

    def restore_compatibility(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        contracts = self.contract_hashes()
        binding = self.binding()
        if contracts is None:
            return [{"code": "PORTABILITY_CONTRACTS_UNAVAILABLE"}]
        issues: list[dict[str, Any]] = []
        if manifest.get("project_id") != binding.get("project_id"):
            issues.append(
                {
                    "code": "PORTABILITY_PROJECT_CONTAMINATION",
                    "bundle_project_id": manifest.get("project_id"),
                    "target_project_id": binding.get("project_id"),
                }
            )
            return issues
        contract_pairs = {
            "binding_sha256": manifest.get("binding_sha256"),
            "adapter_fingerprint_sha256": manifest.get("adapter_fingerprint_sha256"),
            "core_manifest_sha256": manifest.get("core_manifest_sha256"),
            "record_type_registry_sha256": manifest.get("record_type_registry", {}).get(
                "registry_sha256"
            ),
            "recovery_profile_sha256": manifest.get("recovery_profile", {}).get(
                "profile_sha256"
            ),
            "retention_policy_sha256": manifest.get("retention_policy", {}).get(
                "policy_sha256"
            ),
        }
        for field, expected in contract_pairs.items():
            if contracts[field] != expected:
                issues.append(
                    {
                        "code": "PORTABILITY_COMPATIBILITY_MISMATCH",
                        "field": field,
                    }
                )
        for entry in manifest["entries"]:
            if entry["restore_mode"] != "verify-only" or not entry["present"]:
                continue
            target = self.project_path(entry["canonical_path"])
            content, _content_error = read_regular_bounded(
                target,
                entry["bytes"],
            )
            if (
                content is None
                or len(content) != entry["bytes"]
                or sha256_bytes(content) != entry["sha256"]
            ):
                issues.append(
                    {
                        "code": "PORTABILITY_VERIFY_ONLY_TARGET_MISMATCH",
                        "path": entry["canonical_path"],
                    }
                )
        return issues

    def render_restore_diff(
        self,
        targets: list[dict[str, Any]],
        bundle: Path,
        manifest: dict[str, Any],
    ) -> str:
        entries = {item["entry_id"]: item for item in manifest["entries"]}
        policy, policy_errors = self.policy()
        if policy is None:
            raise ValueError(f"retention policy invalid: {policy_errors}")
        maximum = policy["bounds"]["max_manifest_bytes"]
        parts: list[str] = []
        summaries: list[str] = []
        for target in targets:
            target_path = self.project_path(target["path"])
            before_content, before_error = read_regular_bounded(
                target_path,
                policy["bounds"]["max_file_bytes"],
            )
            if target_path.exists() and before_content is None:
                raise ValueError(f"unreadable restore target: {before_error}")
            before = before_content or b""
            entry = entries[target["entry_id"]]
            after, _after_error = read_regular_bounded(
                safe_join(bundle, entry["storage_path"], canonical=True),
                entry["bytes"],
            )
            if after is None:
                raise ValueError(f"missing staged payload: {entry['entry_id']}")
            summary = (
                f"Binary/large payload: {target['path']} "
                f"before={target['before_sha256']} "
                f"after={target['after_sha256']} bytes={target['bytes']}\n"
            )
            summaries.append(summary)
            try:
                before_text = before.decode("utf-8")
                after_text = after.decode("utf-8")
                textual = "\x00" not in before_text and "\x00" not in after_text
            except UnicodeDecodeError:
                textual = False
                before_text = ""
                after_text = ""
            if textual and len(before) + len(after) <= 65536:
                parts.append(
                    "".join(
                        difflib.unified_diff(
                            before_text.splitlines(keepends=True),
                            after_text.splitlines(keepends=True),
                            fromfile=f"a/{target['path']}",
                            tofile=f"b/{target['path']}",
                        )
                    )
                )
            else:
                parts.append(summary)
        result = "".join(parts)
        if len(result.encode("utf-8")) > maximum:
            result = "".join(summaries)
        if len(result.encode("utf-8")) > maximum:
            raise ValueError("restore diff exceeds bounded review surface")
        return result
