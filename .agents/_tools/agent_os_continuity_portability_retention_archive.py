#!/usr/bin/env python3
"""Retention and archive domain behavior for AOS-15 continuity portability.

This internal mixin owns retention characterization and archive-specific planning,
validation, provenance, apply preparation, cleanup targeting, and receipt binding.
It never deletes live sources and does not implement prune or age/count execution.
"""

from __future__ import annotations

import json
import re
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
    artifact_id,
    lexical_absolute,
    project_relative_from_agent,
    read_regular,
    read_regular_bounded,
    scan_tree_bounded,
)
from agent_os_continuity_transactions import strict_document
from agent_os_paths import portable_collision_key, portable_relative, safe_join

POLICY_AGENT_REL = "memory/continuity-retention-policy.json"
ARCHIVE_DIR_AGENT_REL = "project/context/continuity-archives"
ARCHIVE_MANIFEST_NAME = "continuity-archive-manifest.json"
ARCHIVE_ID = re.compile(r"^continuity-archive-[0-9a-f]{24}$")
RETENTION_CLASSES = {
    "critical-active",
    "critical-history",
    "evidence",
    "operational",
    "advisory",
}
POLICY_FIELDS = {
    "schema_version",
    "policy_id",
    "policy_version",
    "classes",
    "holds",
    "bounds",
    "archive_original_required",
    "explicit_confirmation_required",
    "raw_conversation_allowed",
}
POLICY_CLASS_FIELDS = {
    "retention_class",
    "allowed_candidate_modes",
    "live_prune_mode",
}
POLICY_HOLDS = {
    "active-required-or-state-aware",
    "dependency-target",
    "handoff-or-completion-evidence",
    "recovery-pinned",
}
POLICY_BOUND_FIELDS = {
    "max_entries",
    "max_file_bytes",
    "max_total_bytes",
    "max_manifest_bytes",
}
ARCHIVE_FIELDS = {
    "schema_version",
    "archive_id",
    "project_id",
    "created_at",
    "source_git_head",
    "binding_sha256",
    "adapter_fingerprint_sha256",
    "retention_policy_sha256",
    "catalog_sha256",
    "reference_ids",
    "entries",
    "summary",
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
ARCHIVE_ENTRY_FIELDS = {
    "entry_id",
    "reference_id",
    "canonical_path",
    "storage_path",
    "bytes",
    "sha256",
    "retention_class",
    "privacy_class",
}
ARCHIVE_SUMMARY_FIELDS = {
    "reference_count",
    "entry_count",
    "total_bytes",
    "retention_classes",
    "predecessors",
    "successors",
    "holds",
    "inventory_sha256",
    "source_deleted",
}

_CATALOG_AGENT_REL = "project/context/continuity.json"
_BINDING_AGENT_REL = "project/project-binding.json"
_FINGERPRINT_AGENT_REL = "project/adapter-fingerprint.json"
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


class ContinuityRetentionArchiveMixin:
    def inspect_retention(self) -> dict[str, Any]:
        policy, policy_errors = self.policy()
        catalog, catalog_errors = self.catalog()
        if policy is None or catalog is None:
            return {
                "ok": False,
                "reason_codes": list(dict.fromkeys([*policy_errors, *catalog_errors])),
                "candidates": [],
            }
        references = [
            item for item in catalog.get("references", []) if isinstance(item, dict)
        ]
        by_id = {item["reference_id"]: item for item in references}
        successors: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        for reference in references:
            if reference.get("lifecycle") == "active":
                for target in reference.get("supersedes", []):
                    successors.setdefault(target, []).append(reference["reference_id"])
                for dependency in reference.get("dependencies", []):
                    incoming.setdefault(
                        str(dependency.get("target_reference_id")), []
                    ).append(reference["reference_id"])
        class_modes = {
            item["retention_class"]: item["allowed_candidate_modes"]
            for item in policy["classes"]
        }
        candidates: list[dict[str, Any]] = []
        for reference_id in sorted(by_id):
            reference = by_id[reference_id]
            holds: list[str] = []
            retention_class = reference["retention_class"]
            if retention_class == "critical-active":
                holds.append("RETENTION_CRITICAL_ACTIVE_HOLD")
            if (
                reference.get("lifecycle") == "active"
                and reference.get("requirement") in {"required", "state-aware"}
            ):
                holds.append("RETENTION_ACTIVE_AUTHORITY_HOLD")
            if incoming.get(reference_id):
                holds.append("RETENTION_DEPENDENCY_HOLD")
            if (
                reference.get("record_type")
                in {"handoff-receipt", "verification-artifact"}
                and reference.get("lifecycle") == "active"
            ):
                holds.append("RETENTION_EVIDENCE_HOLD")
            source_path = str(reference.get("source", {}).get("path", ""))
            if source_path.startswith(
                (
                    ".agents/project/context/continuity-backups/",
                    ".agents/project/context/continuity-transactions/",
                )
            ):
                holds.append("RETENTION_RECOVERY_HOLD")
            if (
                retention_class == "critical-history"
                and not successors.get(reference_id)
            ):
                holds.append("RETENTION_SUCCESSOR_REQUIRED")
            try:
                source = self.project_path(source_path)
                source_content, _source_error = read_regular_bounded(
                    source,
                    policy["bounds"]["max_file_bytes"],
                )
                source_available = (
                    source_content is not None
                    and sha256_bytes(source_content)
                    == reference.get("source", {}).get("sha256")
                )
            except (OSError, ValueError):
                source_available = False
            if not source_available:
                holds.append("RETENTION_SOURCE_UNAVAILABLE")
            eligible = (
                "explicit" in class_modes.get(retention_class, [])
                and not holds
            )
            candidates.append(
                {
                    "reference_id": reference_id,
                    "retention_class": retention_class,
                    "lifecycle": reference.get("lifecycle"),
                    "requirement": reference.get("requirement"),
                    "archive_eligible": eligible,
                    "prune_eligible": False,
                    "hold_reasons": list(dict.fromkeys(holds)),
                    "successor_reference_ids": sorted(successors.get(reference_id, [])),
                    "dependent_reference_ids": sorted(incoming.get(reference_id, [])),
                    "source": {
                        "path": source_path,
                        "sha256": reference.get("source", {}).get("sha256"),
                    },
                }
            )
        return {
            "ok": True,
            "project_id": catalog.get("project_id"),
            "policy_sha256": sha256_bytes(
                read_regular(self.agent_path(POLICY_AGENT_REL)) or b""
            ),
            "source_deleted": False,
            "candidates": candidates,
        }

    def build_archive_manifest(self, reference_ids: list[str]) -> dict[str, Any]:
        preflight = self.preflight()
        if not preflight["ok"]:
            return {"ok": False, "reason_codes": preflight["reason_codes"]}
        if (
            not isinstance(reference_ids, list)
            or not reference_ids
            or reference_ids != sorted(set(reference_ids))
        ):
            return {"ok": False, "reason_codes": ["RETENTION_SELECTION_INVALID"]}
        retention = self.inspect_retention()
        by_candidate = {
            item["reference_id"]: item for item in retention.get("candidates", [])
        }
        blocked = [
            {
                "reference_id": reference_id,
                "hold_reasons": by_candidate.get(reference_id, {}).get(
                    "hold_reasons", ["RETENTION_REFERENCE_UNKNOWN"]
                ),
            }
            for reference_id in reference_ids
            if not by_candidate.get(reference_id, {}).get("archive_eligible")
        ]
        if blocked:
            return {
                "ok": False,
                "reason_codes": ["RETENTION_SELECTION_HELD"],
                "blocked": blocked,
            }
        catalog = preflight["catalog"]
        by_reference = {
            item["reference_id"]: item for item in catalog["references"]
        }
        entries: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        collision_paths: dict[str, str] = {}
        for reference_id in reference_ids:
            reference = by_reference[reference_id]
            path = reference["source"]["path"]
            source = self.project_path(path)
            content, content_error = read_regular_bounded(
                source,
                preflight["policy"]["bounds"]["max_file_bytes"],
            )
            if content is None or self.path_is_link_like(source):
                issues.append(
                    {
                        "code": (
                            "PORTABILITY_FILE_BOUND_EXCEEDED"
                            if content_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
                            else "RETENTION_SOURCE_UNAVAILABLE"
                        ),
                        "reference_id": reference_id,
                    }
                )
                continue
            if reference["privacy_class"] == "sensitive-reference":
                issues.append(
                    {
                        "code": "PORTABILITY_SENSITIVE_PLAINTEXT_FORBIDDEN",
                        "reference_id": reference_id,
                    }
                )
                continue
            privacy_error = self.privacy_error(content, path)
            if privacy_error:
                issues.append({"code": privacy_error, "reference_id": reference_id})
                continue
            digest = sha256_bytes(content)
            if digest != reference["source"]["sha256"]:
                issues.append(
                    {"code": "RETENTION_SOURCE_DRIFT", "reference_id": reference_id}
                )
                continue
            collision_key = portable_collision_key(path, canonical=True)
            colliding_path = collision_paths.get(collision_key)
            if colliding_path is not None and colliding_path != path:
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_PATH_COLLISION",
                        "reference_id": reference_id,
                        "path": path,
                        "collides_with": colliding_path,
                    }
                )
                continue
            collision_paths[collision_key] = path
            entry_id = (
                "continuity-entry-"
                + canonical_hash(
                    {
                        "reference_id": reference_id,
                        "canonical_path": path,
                        "sha256": digest,
                    }
                )[:24]
            )
            entries.append(
                {
                    "entry_id": entry_id,
                    "reference_id": reference_id,
                    "canonical_path": path,
                    "storage_path": f"files/{entry_id}.bin",
                    "bytes": len(content),
                    "sha256": digest,
                    "retention_class": reference["retention_class"],
                    "privacy_class": reference["privacy_class"],
                }
            )
        if issues:
            return {
                "ok": False,
                "reason_codes": list(dict.fromkeys(item["code"] for item in issues)),
                "issues": issues,
            }
        entries = sorted(entries, key=lambda item: item["canonical_path"])
        inventory_sha256 = canonical_hash(entries)
        successors = [
            {
                "reference_id": reference_id,
                "successor_reference_ids": by_candidate[reference_id][
                    "successor_reference_ids"
                ],
            }
            for reference_id in reference_ids
        ]
        predecessors = [
            {
                "reference_id": reference_id,
                "predecessor_reference_ids": sorted(
                    by_reference[reference_id].get("supersedes", [])
                ),
            }
            for reference_id in reference_ids
        ]
        holds = [
            {
                "reference_id": reference_id,
                "hold_reasons": by_candidate[reference_id]["hold_reasons"],
            }
            for reference_id in reference_ids
        ]
        summary = {
            "reference_count": len(reference_ids),
            "entry_count": len(entries),
            "total_bytes": sum(item["bytes"] for item in entries),
            "retention_classes": sorted(
                set(item["retention_class"] for item in entries)
            ),
            "predecessors": predecessors,
            "successors": successors,
            "holds": holds,
            "inventory_sha256": inventory_sha256,
            "source_deleted": False,
        }
        contracts = preflight["contracts"]
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "archive_id": "",
            "project_id": catalog["project_id"],
            "created_at": catalog["updated_at"],
            "source_git_head": preflight["head"],
            "binding_sha256": contracts["binding_sha256"],
            "adapter_fingerprint_sha256": contracts[
                "adapter_fingerprint_sha256"
            ],
            "retention_policy_sha256": contracts["retention_policy_sha256"],
            "catalog_sha256": sha256_bytes(
                read_regular(self.agent_path(_CATALOG_AGENT_REL)) or b""
            ),
            "reference_ids": reference_ids,
            "entries": entries,
            "summary": summary,
            "entry_count": len(entries),
            "total_bytes": summary["total_bytes"],
            "inventory_sha256": inventory_sha256,
            "raw_conversation_stored": False,
            "prompt_stored": False,
            "chain_of_thought_stored": False,
            "secret_stored": False,
            "source_deleted": False,
            "commit_created": False,
            "push_performed": False,
        }
        manifest["archive_id"] = artifact_id(
            manifest, "continuity-archive-", "archive_id"
        )
        manifest["content_sha256"] = receipt_hash(manifest)
        errors = self.validate_archive_manifest(manifest)
        if errors:
            return {"ok": False, "reason_codes": errors}
        return {"ok": True, "manifest": manifest}

    def validate_archive_manifest(self, manifest: Any) -> list[str]:
        policy, policy_errors = self.policy()
        if policy is None:
            return policy_errors
        if not isinstance(manifest, dict) or set(manifest) != ARCHIVE_FIELDS:
            return ["RETENTION_ARCHIVE_MANIFEST_FIELDS_INVALID"]
        if (
            manifest.get("schema_version") != 1
            or not isinstance(manifest.get("archive_id"), str)
            or ARCHIVE_ID.fullmatch(manifest["archive_id"]) is None
            or artifact_id(manifest, "continuity-archive-", "archive_id")
            != manifest["archive_id"]
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
                    "retention_policy_sha256",
                    "catalog_sha256",
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
            or len(json_bytes(manifest))
            > policy["bounds"]["max_manifest_bytes"]
        ):
            return ["RETENTION_ARCHIVE_MANIFEST_INVALID"]
        references = manifest.get("reference_ids")
        entries = manifest.get("entries")
        summary = manifest.get("summary")
        if (
            not isinstance(references, list)
            or not references
            or len(references) > policy["bounds"]["max_entries"]
            or references != sorted(set(references))
            or any(
                not isinstance(reference_id, str)
                or not 1 <= len(reference_id) <= 128
                for reference_id in references
            )
            or not isinstance(entries, list)
            or len(entries) > policy["bounds"]["max_entries"]
            or len(entries) != len(references)
            or not isinstance(summary, dict)
            or set(summary) != ARCHIVE_SUMMARY_FIELDS
        ):
            return ["RETENTION_ARCHIVE_INVENTORY_INVALID"]
        paths: list[str] = []
        collision_paths: dict[str, str] = {}
        total = 0
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != ARCHIVE_ENTRY_FIELDS:
                return ["RETENTION_ARCHIVE_ENTRY_INVALID"]
            try:
                canonical = portable_relative(
                    str(entry.get("canonical_path")), canonical=True
                )
            except ValueError:
                return ["RETENTION_ARCHIVE_ENTRY_INVALID"]
            collision_key = portable_collision_key(canonical, canonical=True)
            colliding_path = collision_paths.get(collision_key)
            if colliding_path is not None and colliding_path != canonical:
                return ["RETENTION_ARCHIVE_ENTRY_PATH_COLLISION"]
            expected_id = (
                "continuity-entry-"
                + canonical_hash(
                    {
                        "reference_id": entry.get("reference_id"),
                        "canonical_path": canonical,
                        "sha256": entry.get("sha256"),
                    }
                )[:24]
            )
            if (
                canonical != entry.get("canonical_path")
                or not 1 <= len(canonical) <= 512
                or canonical in paths
                or entry.get("reference_id") not in references
                or entry.get("entry_id") != expected_id
                or entry.get("storage_path") != f"files/{expected_id}.bin"
                or type(entry.get("bytes")) is not int
                or not 0 <= entry["bytes"] <= policy["bounds"]["max_file_bytes"]
                or not _valid_hash(entry.get("sha256"))
                or entry.get("retention_class")
                not in RETENTION_CLASSES - {"critical-active"}
                or entry.get("privacy_class")
                not in {"public-metadata", "project-internal"}
            ):
                return ["RETENTION_ARCHIVE_ENTRY_INVALID"]
            paths.append(canonical)
            collision_paths[collision_key] = canonical
            total += entry["bytes"]
        if paths != sorted(paths):
            return ["RETENTION_ARCHIVE_INVENTORY_INVALID"]
        expected_predecessors = summary.get("predecessors")
        expected_successors = summary.get("successors")
        expected_holds = summary.get("holds")
        if (
            sorted(item["reference_id"] for item in entries) != references
            or summary.get("reference_count") != len(references)
            or summary.get("entry_count") != len(entries)
            or summary.get("total_bytes") != total
            or summary.get("retention_classes")
            != sorted(set(item["retention_class"] for item in entries))
            or not isinstance(expected_predecessors, list)
            or [
                item.get("reference_id")
                for item in expected_predecessors
                if isinstance(item, dict)
            ]
            != references
            or any(
                not isinstance(item, dict)
                or set(item) != {"reference_id", "predecessor_reference_ids"}
                or not isinstance(item["predecessor_reference_ids"], list)
                or len(item["predecessor_reference_ids"])
                > policy["bounds"]["max_entries"]
                or item["predecessor_reference_ids"]
                != sorted(set(item["predecessor_reference_ids"]))
                or any(
                    not isinstance(reference_id, str)
                    or not 1 <= len(reference_id) <= 128
                    for reference_id in item["predecessor_reference_ids"]
                )
                for item in expected_predecessors
            )
            or not isinstance(expected_successors, list)
            or [
                item.get("reference_id")
                for item in expected_successors
                if isinstance(item, dict)
            ]
            != references
            or any(
                not isinstance(item, dict)
                or set(item) != {"reference_id", "successor_reference_ids"}
                or not isinstance(item["successor_reference_ids"], list)
                or len(item["successor_reference_ids"])
                > policy["bounds"]["max_entries"]
                or item["successor_reference_ids"]
                != sorted(set(item["successor_reference_ids"]))
                or any(
                    not isinstance(reference_id, str)
                    or not 1 <= len(reference_id) <= 128
                    for reference_id in item["successor_reference_ids"]
                )
                for item in expected_successors
            )
            or not isinstance(expected_holds, list)
            or [
                item.get("reference_id")
                for item in expected_holds
                if isinstance(item, dict)
            ]
            != references
            or any(
                not isinstance(item, dict)
                or set(item) != {"reference_id", "hold_reasons"}
                or not isinstance(item["hold_reasons"], list)
                or len(item["hold_reasons"]) > len(POLICY_HOLDS) + 2
                or item["hold_reasons"] != sorted(set(item["hold_reasons"]))
                or any(
                    not isinstance(reason, str) or not 1 <= len(reason) <= 128
                    for reason in item["hold_reasons"]
                )
                for item in expected_holds
            )
            or summary.get("inventory_sha256") != canonical_hash(entries)
            or summary.get("source_deleted") is not False
            or manifest.get("entry_count") != len(entries)
            or manifest.get("total_bytes") != total
            or manifest.get("inventory_sha256") != canonical_hash(entries)
            or total > policy["bounds"]["max_total_bytes"]
        ):
            return ["RETENTION_ARCHIVE_INVENTORY_INVALID"]
        return []

    def validate_archive_git_provenance(
        self,
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        commit = manifest["source_git_head"]
        tree = self.git_tree(commit)
        if tree is None:
            return [{"code": "PORTABILITY_SOURCE_COMMIT_NOT_REACHABLE"}]

        authority_paths = {
            "catalog_sha256": project_relative_from_agent(_CATALOG_AGENT_REL),
            "binding_sha256": project_relative_from_agent(_BINDING_AGENT_REL),
            "adapter_fingerprint_sha256": project_relative_from_agent(
                _FINGERPRINT_AGENT_REL
            ),
            "retention_policy_sha256": project_relative_from_agent(POLICY_AGENT_REL),
        }
        authority: dict[str, bytes] = {}
        issues: list[dict[str, Any]] = []
        for field, path in authority_paths.items():
            content, error = self.git_blob_at(commit, path, tree)
            if error or content is None:
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_GIT_AUTHORITY_UNAVAILABLE",
                        "path": path,
                    }
                )
                continue
            authority[field] = content
            if manifest.get(field) != sha256_bytes(content):
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_GIT_AUTHORITY_MISMATCH",
                        "field": field,
                    }
                )
        raw_catalog = authority.get("catalog_sha256")
        if raw_catalog is None:
            return issues
        try:
            catalog = strict_document(raw_catalog)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return [
                *issues,
                {"code": "RETENTION_ARCHIVE_GIT_CATALOG_INVALID"},
            ]
        if not isinstance(catalog, dict) or validate_catalog_shape(catalog):
            return [
                *issues,
                {"code": "RETENTION_ARCHIVE_GIT_CATALOG_INVALID"},
            ]
        if (
            manifest.get("project_id") != catalog.get("project_id")
            or manifest.get("created_at") != catalog.get("updated_at")
        ):
            issues.append({"code": "RETENTION_ARCHIVE_GIT_CATALOG_MISMATCH"})

        references = {
            item["reference_id"]: item
            for item in catalog["references"]
            if isinstance(item, dict)
            and isinstance(item.get("reference_id"), str)
        }
        successors: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        for reference in references.values():
            if reference.get("lifecycle") != "active":
                continue
            for target in reference.get("supersedes", []):
                successors.setdefault(target, []).append(reference["reference_id"])
            for dependency in reference.get("dependencies", []):
                if isinstance(dependency, dict):
                    incoming.setdefault(
                        str(dependency.get("target_reference_id")), []
                    ).append(reference["reference_id"])

        expected_predecessors: list[dict[str, Any]] = []
        expected_successors: list[dict[str, Any]] = []
        expected_holds: list[dict[str, Any]] = []
        for entry in manifest["entries"]:
            reference_id = entry["reference_id"]
            reference = references.get(reference_id)
            if reference is None:
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_GIT_REFERENCE_MISSING",
                        "reference_id": reference_id,
                    }
                )
                continue
            source = reference.get("source", {})
            holds: list[str] = []
            if reference.get("retention_class") == "critical-active":
                holds.append("RETENTION_CRITICAL_ACTIVE_HOLD")
            if (
                reference.get("lifecycle") == "active"
                and reference.get("requirement") in {"required", "state-aware"}
            ):
                holds.append("RETENTION_ACTIVE_AUTHORITY_HOLD")
            if incoming.get(reference_id):
                holds.append("RETENTION_DEPENDENCY_HOLD")
            if (
                reference.get("record_type")
                in {"handoff-receipt", "verification-artifact"}
                and reference.get("lifecycle") == "active"
            ):
                holds.append("RETENTION_EVIDENCE_HOLD")
            if str(source.get("path", "")).startswith(
                (
                    ".agents/project/context/continuity-backups/",
                    ".agents/project/context/continuity-transactions/",
                )
            ):
                holds.append("RETENTION_RECOVERY_HOLD")
            if (
                reference.get("retention_class") == "critical-history"
                and not successors.get(reference_id)
            ):
                holds.append("RETENTION_SUCCESSOR_REQUIRED")
            source_content, source_error = self.git_blob_at(
                commit,
                str(source.get("path", "")),
                tree,
            )
            if (
                source_error
                or source_content is None
                or sha256_bytes(source_content) != source.get("sha256")
            ):
                holds.append("RETENTION_SOURCE_UNAVAILABLE")
            if (
                entry["canonical_path"] != source.get("path")
                or entry["sha256"] != source.get("sha256")
                or entry["retention_class"] != reference.get("retention_class")
                or entry["privacy_class"] != reference.get("privacy_class")
            ):
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_GIT_REFERENCE_MISMATCH",
                        "reference_id": reference_id,
                    }
                )
            if holds:
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_GIT_REFERENCE_HELD",
                        "reference_id": reference_id,
                        "hold_reasons": list(dict.fromkeys(holds)),
                    }
                )
            expected_predecessors.append(
                {
                    "reference_id": reference_id,
                    "predecessor_reference_ids": sorted(
                        reference.get("supersedes", [])
                    ),
                }
            )
            expected_successors.append(
                {
                    "reference_id": reference_id,
                    "successor_reference_ids": sorted(
                        successors.get(reference_id, [])
                    ),
                }
            )
            expected_holds.append(
                {
                    "reference_id": reference_id,
                    "hold_reasons": list(dict.fromkeys(holds)),
                }
            )
        summary = manifest["summary"]
        if (
            summary.get("predecessors") != expected_predecessors
            or summary.get("successors") != expected_successors
            or summary.get("holds") != expected_holds
        ):
            issues.append({"code": "RETENTION_ARCHIVE_GIT_SUMMARY_MISMATCH"})
        return issues

    def inspect_archive(self, source: str | Path) -> dict[str, Any]:
        policy, policy_errors = self.policy()
        if policy is None:
            return {"ok": False, "reason_codes": policy_errors}
        archive_input = lexical_absolute(Path(source), self.project_root)
        if self.path_is_link_like(archive_input):
            return {
                "ok": False,
                "reason_codes": ["RETENTION_ARCHIVE_ROOT_SYMLINK"],
            }
        try:
            archive = archive_input.resolve(strict=True)
        except OSError:
            return {
                "ok": False,
                "reason_codes": ["RETENTION_ARCHIVE_PATH_INVALID"],
            }
        if not archive.is_dir():
            return {
                "ok": False,
                "reason_codes": ["RETENTION_ARCHIVE_PATH_INVALID"],
            }
        manifest_content, manifest_error = read_regular_bounded(
            archive / ARCHIVE_MANIFEST_NAME,
            policy["bounds"]["max_manifest_bytes"],
        )
        if manifest_content is None:
            return {
                "ok": False,
                "reason_codes": [
                    (
                        "RETENTION_ARCHIVE_MANIFEST_BOUND_EXCEEDED"
                        if manifest_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
                        else "RETENTION_ARCHIVE_MANIFEST_MISSING"
                    )
                ],
            }
        try:
            manifest = strict_document(manifest_content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {
                "ok": False,
                "reason_codes": ["RETENTION_ARCHIVE_MANIFEST_INVALID"],
            }
        errors = self.validate_archive_manifest(manifest)
        if errors:
            return {"ok": False, "reason_codes": errors}
        provenance_issues = self.validate_archive_git_provenance(manifest)
        if provenance_issues:
            return {
                "ok": False,
                "reason_codes": list(
                    dict.fromkeys(
                        item["code"] for item in provenance_issues
                    )
                ),
                "issues": provenance_issues,
            }
        actual_files: set[str] = set()
        files, _visited, scan_error, _error_path = scan_tree_bounded(
            archive,
            policy["bounds"]["max_entries"] * 2 + 16,
        )
        if scan_error is not None:
            reason = {
                "bound": "RETENTION_ARCHIVE_ENTRY_BOUND_EXCEEDED",
                "symlink": "RETENTION_ARCHIVE_SYMLINK",
                "irregular": "RETENTION_ARCHIVE_UNREADABLE",
                "unreadable": "RETENTION_ARCHIVE_UNREADABLE",
            }[scan_error]
            return {"ok": False, "reason_codes": [reason]}
        actual_files.update(path.relative_to(archive).as_posix() for path in files)
        expected_files = {
            ARCHIVE_MANIFEST_NAME,
            *(entry["storage_path"] for entry in manifest["entries"]),
        }
        issues: list[dict[str, Any]] = []
        tree = self.git_tree(manifest["source_git_head"])
        if tree is None:
            issues.append({"code": "PORTABILITY_SOURCE_COMMIT_NOT_REACHABLE"})
        for entry in manifest["entries"]:
            payload, payload_error = read_regular_bounded(
                safe_join(archive, entry["storage_path"], canonical=True),
                policy["bounds"]["max_file_bytes"],
            )
            if (
                payload is None
                or len(payload) != entry["bytes"]
                or sha256_bytes(payload) != entry["sha256"]
            ):
                issues.append(
                    {
                        "code": "RETENTION_ARCHIVE_PAYLOAD_TAMPERED",
                        "entry_id": entry["entry_id"],
                        "cause": payload_error,
                    }
                )
                continue
            privacy_error = self.privacy_error(payload, entry["canonical_path"])
            if privacy_error:
                issues.append(
                    {"code": privacy_error, "entry_id": entry["entry_id"]}
                )
            if tree is not None:
                git_payload, git_error = self.git_blob_at(
                    manifest["source_git_head"],
                    entry["canonical_path"],
                    tree,
                )
                if (
                    git_error
                    or git_payload is None
                    or sha256_bytes(git_payload) != entry["sha256"]
                ):
                    issues.append(
                        {
                            "code": "RETENTION_ARCHIVE_GIT_PROVENANCE_INVALID",
                            "entry_id": entry["entry_id"],
                        }
                    )
        if actual_files != expected_files:
            issues.append(
                {
                    "code": "RETENTION_ARCHIVE_FILE_SET_MISMATCH",
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
            "archive_path": str(archive),
            "manifest": manifest,
            "manifest_sha256": sha256_bytes(manifest_content),
        }

    def plan_archive(
        self, reference_ids: list[str], expiry_seconds: int = 900
    ) -> dict[str, Any]:
        if (
            not isinstance(reference_ids, list)
            or not reference_ids
            or len(reference_ids) > 2048
            or any(
                not isinstance(item, str) or not 1 <= len(item) <= 128
                for item in reference_ids
            )
        ):
            return {"ok": False, "reason_codes": ["RETENTION_SELECTION_INVALID"]}
        selection = sorted(set(reference_ids))
        built = self.build_archive_manifest(selection)
        if not built.get("ok"):
            return built
        manifest = built["manifest"]
        destination = f"{ARCHIVE_DIR_AGENT_REL}/{manifest['archive_id']}"
        return self.create_portability_plan(
            "archive",
            manifest,
            destination,
            {
                "reference_ids": selection,
                "summary_sha256": canonical_hash(manifest["summary"]),
            },
            expiry_seconds,
        )

    def prepare_archive_apply(self, plan: dict[str, Any]) -> dict[str, Any]:
        built = self.build_archive_manifest(plan["metadata"]["reference_ids"])
        if not built.get("ok"):
            return built
        archive_root = self.verified_owned_directory(
            ARCHIVE_DIR_AGENT_REL,
            create=True,
        )
        if archive_root is None:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_ARCHIVE_ROOT_UNSAFE"],
            }
        return {
            "ok": True,
            "manifest": built["manifest"],
            "destination": archive_root / plan["artifact_id"],
        }

    @staticmethod
    def archive_cleanup_relative(destination: Path) -> str:
        return f"{ARCHIVE_DIR_AGENT_REL}/{destination.name}"

    def validate_archive_portability_receipt_artifact(
        self,
        receipt: dict[str, Any],
    ) -> list[str]:
        expected_path = f".agents/{ARCHIVE_DIR_AGENT_REL}/{receipt['artifact_id']}"
        if (
            receipt["artifact_state"] != "durable-verified"
            or receipt["artifact_path"] != expected_path
            or receipt.get("artifact_manifest") is not None
        ):
            return ["PORTABILITY_RECEIPT_INVALID"]
        inspected = self.inspect_archive(self.project_path(receipt["artifact_path"]))
        manifest = inspected.get("manifest", {})
        if (
            not inspected.get("ok")
            or inspected.get("manifest_sha256") != receipt["manifest_sha256"]
            or manifest.get("inventory_sha256") != receipt["inventory_sha256"]
            or manifest.get("archive_id") != receipt["artifact_id"]
            or manifest.get("project_id") != receipt["project_id"]
            or manifest.get("source_git_head") != receipt["base_commit"]
            or manifest.get("binding_sha256") != receipt["binding_sha256"]
            or manifest.get("adapter_fingerprint_sha256")
            != receipt["adapter_fingerprint_sha256"]
            or manifest.get("retention_policy_sha256")
            != receipt["retention_policy_sha256"]
        ):
            return ["PORTABILITY_RECEIPT_ARTIFACT_UNVERIFIABLE"]
        return []
