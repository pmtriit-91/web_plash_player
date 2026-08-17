#!/usr/bin/env python3
"""Retention, deterministic export, and transactional restore for AOS-15.

The service is release-owned. It never treats a summary or bundle as new project
authority, never overwrites Core from a bundle, and never deletes a live source.
All write operations require a reviewed plan ID and explicit confirmation.
"""

from __future__ import annotations

import json
import os
import re
import stat
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    ContextMemoryService,
    canonical_hash,
    has_forbidden_payload,
    iso_time,
    json_bytes,
    parse_time,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity import (
    doctor as continuity_doctor,
)
from agent_os_continuity import (
    validate_catalog_shape,
)
from agent_os_continuity_portability_export import (
    BUNDLE_ID,
    EXPORT_MANIFEST_NAME,
    ContinuityExportMixin,
)
from agent_os_continuity_portability_export import (
    ENTRY_ID as ENTRY_ID,
)
from agent_os_continuity_portability_export import (
    EXPORT_ENTRY_FIELDS as EXPORT_ENTRY_FIELDS,
)
from agent_os_continuity_portability_export import (
    EXPORT_FIELDS as EXPORT_FIELDS,
)
from agent_os_continuity_portability_export import (
    PRIVACY_CLASSES as PRIVACY_CLASSES,
)
from agent_os_continuity_portability_export import (
    RECOVERY_AUTHORITY_PREFIXES as RECOVERY_AUTHORITY_PREFIXES,
)
from agent_os_continuity_portability_foundation import (
    ABSOLUTE_MAX_FILE_BYTES as ABSOLUTE_MAX_FILE_BYTES,
)
from agent_os_continuity_portability_foundation import (
    DEFAULT_ROOT as DEFAULT_ROOT,
)
from agent_os_continuity_portability_foundation import (
    FULL_COMMIT,
    ContinuityPortabilityFoundation,
    project_relative_from_agent,
    read_regular,
    read_regular_bounded,
)
from agent_os_continuity_portability_foundation import (
    NO_EXPECTED_CONTENT as NO_EXPECTED_CONTENT,
)
from agent_os_continuity_portability_foundation import (
    RESTORE_BACKUP_DIR_AGENT_REL as RESTORE_BACKUP_DIR_AGENT_REL,
)
from agent_os_continuity_portability_foundation import (
    artifact_entry_id as artifact_entry_id,
)
from agent_os_continuity_portability_foundation import (
    artifact_id as artifact_id,
)
from agent_os_continuity_portability_foundation import (
    has_symlink_component as has_symlink_component,
)
from agent_os_continuity_portability_foundation import (
    lexical_absolute as lexical_absolute,
)
from agent_os_continuity_portability_foundation import (
    link_like_path as link_like_path,
)
from agent_os_continuity_portability_foundation import (
    now_utc as now_utc,
)
from agent_os_continuity_portability_foundation import (
    scan_tree_bounded as scan_tree_bounded,
)
from agent_os_continuity_portability_foundation import (
    stat_is_link_like as stat_is_link_like,
)
from agent_os_continuity_portability_restore import (
    BACKUP_ID as BACKUP_ID,
)
from agent_os_continuity_portability_restore import (
    RESTORE_BACKUP_FIELDS as RESTORE_BACKUP_FIELDS,
)
from agent_os_continuity_portability_restore import (
    RESTORE_BACKUP_FILE_FIELDS as RESTORE_BACKUP_FILE_FIELDS,
)
from agent_os_continuity_portability_restore import (
    RESTORE_PLAN_FIELDS as RESTORE_PLAN_FIELDS,
)
from agent_os_continuity_portability_restore import (
    RESTORE_RECEIPT_FIELDS as RESTORE_RECEIPT_FIELDS,
)
from agent_os_continuity_portability_restore import (
    RESTORE_RECEIPT_ID as RESTORE_RECEIPT_ID,
)
from agent_os_continuity_portability_restore import (
    RESTORE_TARGET_FIELDS as RESTORE_TARGET_FIELDS,
)
from agent_os_continuity_portability_restore import (
    ContinuityRestoreMixin,
)
from agent_os_continuity_portability_retention_archive import (
    ARCHIVE_DIR_AGENT_REL,
    ARCHIVE_ID,
    ARCHIVE_MANIFEST_NAME,
    POLICY_AGENT_REL,
    POLICY_BOUND_FIELDS,
    POLICY_CLASS_FIELDS,
    POLICY_FIELDS,
    POLICY_HOLDS,
    RETENTION_CLASSES,
    ContinuityRetentionArchiveMixin,
)
from agent_os_continuity_portability_retention_archive import (
    ARCHIVE_ENTRY_FIELDS as ARCHIVE_ENTRY_FIELDS,
)
from agent_os_continuity_portability_retention_archive import (
    ARCHIVE_FIELDS as ARCHIVE_FIELDS,
)
from agent_os_continuity_portability_retention_archive import (
    ARCHIVE_SUMMARY_FIELDS as ARCHIVE_SUMMARY_FIELDS,
)
from agent_os_continuity_transactions import strict_document
from agent_os_paths import portable_relative as portable_relative
from agent_os_paths import safe_join as safe_join
from agent_os_transaction_lock import (
    TransactionLockError,
    TransactionLockHandle,
    acquire_transaction_lock,
    release_transaction_lock,
)

CATALOG_AGENT_REL = "project/context/continuity.json"
PROJECTION_AGENT_REL = "project/context/continuity-projection.json"
BINDING_AGENT_REL = "project/project-binding.json"
FINGERPRINT_AGENT_REL = "project/adapter-fingerprint.json"
CORE_MANIFEST_AGENT_REL = "_manifest/base-release-manifest.json"
REGISTRY_AGENT_REL = "memory/continuity-record-types.json"
PROFILE_AGENT_REL = "memory/continuity-recovery-profiles.json"
RECEIPT_DIR_AGENT_REL = "project/context/continuity-portability-receipts"


PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

PORTABILITY_PLAN_FIELDS = {
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
    "retention_policy_sha256",
    "artifact_id",
    "artifact_manifest_sha256",
    "source_inventory_sha256",
    "destination",
    "metadata",
    "commit_created",
    "push_performed",
    "content_sha256",
}
PORTABILITY_RECEIPT_FIELDS = {
    "schema_version",
    "receipt_id",
    "plan_id",
    "operation",
    "status",
    "project_id",
    "base_commit",
    "applied_at",
    "artifact_id",
    "artifact_path",
    "artifact_state",
    "artifact_manifest",
    "manifest_sha256",
    "inventory_sha256",
    "binding_sha256",
    "adapter_fingerprint_sha256",
    "retention_policy_sha256",
    "source_deleted",
    "owner_confirmation_performed",
    "raw_conversation_stored",
    "prompt_stored",
    "chain_of_thought_stored",
    "secret_stored",
    "commit_created",
    "push_performed",
    "content_sha256",
}

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
)
SECRET_ASSIGNMENT = re.compile(
    r"""(?i)(?:^|[\x00\r\n])\s*["']?(?:password|passwd|pwd|api[_-]?key|access[_-]?token|"""
    r"""auth[_-]?token|client[_-]?secret|private[_-]?key|secret|token)["']?"""
    r"""\s*[:=]\s*["']?([^\s"'#]{4,})"""
)
SECRET_FIELD_NAMES = {
    "password",
    "passwd",
    "pwd",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "client_secret",
    "private_key",
    "secret",
    "token",
}
FORBIDDEN_CONTENT_FIELDS = {
    "prompt",
    "prompts",
    "raw_prompt",
    "raw_prompts",
    "conversation",
    "conversation_history",
    "transcript",
    "chain_of_thought",
    "reasoning",
    "reasoning_trace",
    "scratchpad",
}
SAFE_SECRET_VALUES = {
    "false",
    "none",
    "null",
    "redacted",
    "placeholder",
    "example",
}
FORBIDDEN_TEXT_FIELD = re.compile(
    r"""(?im)(?:^|[\x00\r\n])\s*["']?(?:prompts?|raw_prompts?|conversation(?:_history)?|"""
    r"""transcript|chain_of_thought|reasoning(?:_trace)?|scratchpad)["']?\s*[:=]"""
)


def valid_hash(value: Any, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (
        isinstance(value, str) and SHA256.fullmatch(value) is not None
    )


def valid_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = parse_time(value)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def meaningful_secret(value: Any) -> bool:
    if value is None or value is False:
        return False
    if not isinstance(value, (str, int, float)):
        return True
    normalized = str(value).strip().strip("\"'").lower()
    return (
        len(normalized) >= 4
        and normalized not in SAFE_SECRET_VALUES
        and not normalized.startswith(("<redacted", "${", "{{", "example-"))
        and set(normalized) != {"*"}
    )


def structured_privacy_error(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_CONTENT_FIELDS:
                return "PORTABILITY_FORBIDDEN_STRUCTURED_PAYLOAD"
            if normalized in SECRET_FIELD_NAMES and meaningful_secret(item):
                return "PORTABILITY_SECRET_DETECTED"
            nested = structured_privacy_error(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = structured_privacy_error(item)
            if nested:
                return nested
    elif isinstance(value, str) and has_forbidden_payload(value):
        return "PORTABILITY_FORBIDDEN_STRUCTURED_PAYLOAD"
    return None


class ContinuityPortabilityService(
    ContinuityRestoreMixin,
    ContinuityExportMixin,
    ContinuityRetentionArchiveMixin,
    ContinuityPortabilityFoundation,
):
    def document(self, relative: str) -> Any:
        content = read_regular(self.agent_path(relative))
        if content is None:
            raise ValueError(f"missing document: {relative}")
        return strict_document(content)

    def policy(self) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            policy = self.document(POLICY_AGENT_REL)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, ["RETENTION_POLICY_INVALID"]
        if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
            return None, ["RETENTION_POLICY_INVALID"]
        classes = policy.get("classes")
        holds = policy.get("holds")
        bounds = policy.get("bounds")
        if (
            policy.get("schema_version") != 1
            or policy.get("policy_id") != "universal-continuity-retention"
            or policy.get("policy_version") != 1
            or not isinstance(classes, list)
            or len(classes) != 5
            or not isinstance(holds, list)
            or set(holds) != POLICY_HOLDS
            or len(holds) != len(POLICY_HOLDS)
            or not isinstance(bounds, dict)
            or set(bounds) != POLICY_BOUND_FIELDS
            or any(type(bounds.get(field)) is not int for field in POLICY_BOUND_FIELDS)
            or not 1 <= bounds["max_entries"] <= 10000
            or not 1024 <= bounds["max_file_bytes"] <= 67108864
            or not 1048576 <= bounds["max_total_bytes"] <= 1073741824
            or not 4096 <= bounds["max_manifest_bytes"] <= 8388608
            or policy.get("archive_original_required") is not True
            or policy.get("explicit_confirmation_required") is not True
            or policy.get("raw_conversation_allowed") is not False
        ):
            return None, ["RETENTION_POLICY_INVALID"]
        by_class: dict[str, dict[str, Any]] = {}
        expected_modes = {
            "critical-active": [],
            "critical-history": ["explicit"],
            "evidence": ["explicit"],
            "operational": ["explicit", "age", "count"],
            "advisory": ["explicit"],
        }
        for item in classes:
            if (
                not isinstance(item, dict)
                or set(item) != POLICY_CLASS_FIELDS
                or item.get("retention_class") not in RETENTION_CLASSES
                or item["retention_class"] in by_class
                or item.get("allowed_candidate_modes")
                != expected_modes[item["retention_class"]]
                or item.get("live_prune_mode")
                != (
                    "never"
                    if item["retention_class"] == "critical-active"
                    else "after-verified-archive"
                )
            ):
                return None, ["RETENTION_POLICY_INVALID"]
            by_class[item["retention_class"]] = item
        if set(by_class) != RETENTION_CLASSES:
            return None, ["RETENTION_POLICY_INVALID"]
        return policy, []

    def contract_hashes(self) -> dict[str, str] | None:
        paths = {
            "binding_sha256": BINDING_AGENT_REL,
            "adapter_fingerprint_sha256": FINGERPRINT_AGENT_REL,
            "core_manifest_sha256": CORE_MANIFEST_AGENT_REL,
            "record_type_registry_sha256": REGISTRY_AGENT_REL,
            "recovery_profile_sha256": PROFILE_AGENT_REL,
            "retention_policy_sha256": POLICY_AGENT_REL,
        }
        result: dict[str, str] = {}
        for field, relative in paths.items():
            content = read_regular(self.agent_path(relative))
            if content is None:
                return None
            result[field] = sha256_bytes(content)
        return result

    def validate_git_contract_provenance(
        self,
        commit: str,
        project_id: str,
        expected_hashes: dict[str, Any],
    ) -> bool:
        """Bind a durable receipt to current project identity and exact Git bytes."""
        if (
            FULL_COMMIT.fullmatch(commit) is None
            or self.binding().get("project_id") != project_id
        ):
            return False
        tree = self.git_tree(commit)
        if tree is None:
            return False
        paths = {
            "binding_sha256": BINDING_AGENT_REL,
            "adapter_fingerprint_sha256": FINGERPRINT_AGENT_REL,
            "core_manifest_sha256": CORE_MANIFEST_AGENT_REL,
            "record_type_registry_sha256": REGISTRY_AGENT_REL,
            "recovery_profile_sha256": PROFILE_AGENT_REL,
            "retention_policy_sha256": POLICY_AGENT_REL,
        }
        authority: dict[str, bytes] = {}
        for field, relative in paths.items():
            content, error = self.git_blob_at(
                commit,
                project_relative_from_agent(relative),
                tree,
            )
            if (
                error is not None
                or content is None
                or expected_hashes.get(field) != sha256_bytes(content)
            ):
                return False
            authority[field] = content
        try:
            binding = strict_document(authority["binding_sha256"])
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return False
        return (
            isinstance(binding, dict)
            and binding.get("project_id") == project_id
        )

    def binding(self) -> dict[str, Any]:
        try:
            value = self.document(BINDING_AGENT_REL)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def catalog(self) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            catalog = self.document(CATALOG_AGENT_REL)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, ["CONTINUITY_CATALOG_INVALID"]
        errors = validate_catalog_shape(catalog)
        if errors:
            return None, list(dict.fromkeys(item["code"] for item in errors))
        return catalog, []

    def preflight(self) -> dict[str, Any]:
        policy, policy_errors = self.policy()
        contracts = self.contract_hashes()
        catalog, catalog_errors = self.catalog()
        context_health = ContextMemoryService(self.root, now=self.now).doctor()
        continuity_health = continuity_doctor(self.root)
        head = self.head()
        required_unavailable = [
            item
            for item in continuity_health.get("references", [])
            if item.get("lifecycle") == "active"
            and item.get("requirement") == "required"
            and item.get("readiness") != "available"
        ]
        reason_codes = [
            *policy_errors,
            *catalog_errors,
            *(["PORTABILITY_CONTRACTS_UNAVAILABLE"] if contracts is None else []),
            *(["GIT_HEAD_UNAVAILABLE"] if head is None else []),
            *(
                ["PORTABILITY_CONTEXT_NOT_FRESH"]
                if context_health.get("state") != "FRESH"
                else []
            ),
            *(
                ["PORTABILITY_CONTINUITY_TOPOLOGY_NOT_COMPLETE"]
                if continuity_health.get("topology_state") != "complete"
                else []
            ),
            *(
                ["PORTABILITY_REQUIRED_AUTHORITY_UNAVAILABLE"]
                if required_unavailable
                else []
            ),
        ]
        return {
            "ok": not reason_codes,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "head": head,
            "policy": policy,
            "contracts": contracts,
            "catalog": catalog,
            "context_health": context_health,
            "continuity_health": continuity_health,
            "required_unavailable": required_unavailable,
        }

    @staticmethod
    def derived_owner_mode(path: str) -> tuple[str, str]:
        application_agent_prefixes = (
            ".agents/project/",
            ".agents/skills/project-memory/",
            ".agents/skills/project-local/",
        )
        if path in {
            ".agents/project/project-binding.json",
            ".agents/project/adapter-fingerprint.json",
        }:
            return "application", "verify-only"
        if path.startswith(application_agent_prefixes):
            return "application", "replace"
        if path.startswith("docs/") or path == "README.md":
            return "application", "replace"
        if path.startswith(".agents/"):
            return "core", "verify-only"
        return "application", "verify-only"

    @staticmethod
    def privacy_error(content: bytes, path: str) -> str | None:
        text = content.decode("utf-8", errors="replace")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            return "PORTABILITY_SECRET_DETECTED"
        assignment = SECRET_ASSIGNMENT.search(text)
        if assignment and meaningful_secret(assignment.group(1)):
            return "PORTABILITY_SECRET_DETECTED"
        suffix = Path(path).suffix.lower()
        if suffix == ".json":
            try:
                document = strict_document(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return "PORTABILITY_STRUCTURED_PAYLOAD_INVALID"
            structured_error = structured_privacy_error(document)
            if structured_error:
                return structured_error
        if has_forbidden_payload(text) or FORBIDDEN_TEXT_FIELD.search(text):
            return "PORTABILITY_FORBIDDEN_TEXT_PAYLOAD"
        return None


    def create_portability_plan(
        self,
        operation: str,
        manifest: dict[str, Any],
        destination: str,
        metadata: dict[str, Any],
        expiry_seconds: int = 900,
    ) -> dict[str, Any]:
        if operation not in {"archive", "export"}:
            return {"ok": False, "reason_codes": ["PORTABILITY_OPERATION_INVALID"]}
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["PORTABILITY_PLAN_EXPIRY_INVALID"]}
        contracts = self.contract_hashes()
        head = self.head()
        binding = self.binding()
        if contracts is None or head is None or not binding.get("project_id"):
            return {"ok": False, "reason_codes": ["PORTABILITY_PREFLIGHT_INVALID"]}
        created = self.now()
        identifier = (
            manifest["archive_id"] if operation == "archive" else manifest["bundle_id"]
        )
        plan: dict[str, Any] = {
            "schema_version": 1,
            "plan_id": "",
            "status": "pending-approval",
            "operation": operation,
            "created_at": iso_time(created),
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "git_head": head,
            "project_id": binding["project_id"],
            **contracts,
            "artifact_id": identifier,
            "artifact_manifest_sha256": sha256_bytes(json_bytes(manifest)),
            "source_inventory_sha256": manifest["inventory_sha256"],
            "destination": destination,
            "metadata": metadata,
            "commit_created": False,
            "push_performed": False,
        }
        plan["plan_id"] = canonical_hash(
            {
                key: value
                for key, value in plan.items()
                if key not in {"plan_id", "content_sha256"}
            }
        )[:24]
        plan["content_sha256"] = receipt_hash(plan)
        plan_root = self.verified_owned_directory(
            "_runtime/continuity-portability/plans",
            create=True,
        )
        if plan_root is None:
            return {"ok": False, "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"]}
        try:
            self._atomic_scoped_bytes(
                self.root,
                f"_runtime/continuity-portability/plans/{plan['plan_id']}.json",
                json_bytes(plan),
                create_parents=True,
            )
        except (OSError, ValueError):
            return {"ok": False, "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"]}
        return {"ok": True, "plan": plan, "artifact_manifest": manifest}


    def validate_portability_plan(
        self, plan: Any, plan_id: str
    ) -> list[str]:
        if not isinstance(plan, dict) or set(plan) != PORTABILITY_PLAN_FIELDS:
            return ["PORTABILITY_PLAN_FIELDS_INVALID"]
        try:
            created = parse_time(str(plan.get("created_at")))
            expires = parse_time(str(plan.get("expires_at")))
        except (TypeError, ValueError):
            return ["PORTABILITY_PLAN_INVALID"]
        expected_id = canonical_hash(
            {
                key: value
                for key, value in plan.items()
                if key not in {"plan_id", "content_sha256"}
            }
        )[:24]
        if (
            plan.get("schema_version") != 1
            or plan.get("plan_id") != plan_id
            or PLAN_ID.fullmatch(plan_id) is None
            or expected_id != plan_id
            or plan.get("status") != "pending-approval"
            or plan.get("operation") not in {"archive", "export"}
            or not valid_time(plan.get("created_at"))
            or not valid_time(plan.get("expires_at"))
            or expires <= created
            or not 60 <= (expires - created).total_seconds() <= 3600
            or not isinstance(plan.get("git_head"), str)
            or FULL_COMMIT.fullmatch(plan["git_head"]) is None
            or not isinstance(plan.get("project_id"), str)
            or not 1 <= len(plan["project_id"]) <= 128
            or any(
                not valid_hash(plan.get(field))
                for field in (
                    "binding_sha256",
                    "adapter_fingerprint_sha256",
                    "core_manifest_sha256",
                    "record_type_registry_sha256",
                    "recovery_profile_sha256",
                    "retention_policy_sha256",
                    "artifact_manifest_sha256",
                    "source_inventory_sha256",
                )
            )
            or plan.get("commit_created") is not False
            or plan.get("push_performed") is not False
            or plan.get("content_sha256") != receipt_hash(plan)
        ):
            return ["PORTABILITY_PLAN_INVALID"]
        operation = plan["operation"]
        metadata = plan.get("metadata")
        destination = plan.get("destination")
        if operation == "export":
            if (
                not isinstance(plan.get("artifact_id"), str)
                or BUNDLE_ID.fullmatch(plan["artifact_id"]) is None
                or metadata != {"bundle_kind": "offline-continuity"}
                or not isinstance(destination, str)
                or not 1 <= len(destination) <= 4096
                or not Path(destination).is_absolute()
            ):
                return ["PORTABILITY_PLAN_METADATA_INVALID"]
        else:
            if (
                not isinstance(plan.get("artifact_id"), str)
                or ARCHIVE_ID.fullmatch(plan["artifact_id"]) is None
                or not isinstance(metadata, dict)
                or set(metadata) != {"reference_ids", "summary_sha256"}
                or not isinstance(metadata["reference_ids"], list)
                or not metadata["reference_ids"]
                or len(metadata["reference_ids"]) > 2048
                or metadata["reference_ids"]
                != sorted(set(metadata["reference_ids"]))
                or any(
                    not isinstance(reference_id, str)
                    or not 1 <= len(reference_id) <= 128
                    for reference_id in metadata["reference_ids"]
                )
                or not valid_hash(metadata.get("summary_sha256"))
                or not isinstance(destination, str)
                or not 1 <= len(destination) <= 4096
                or destination
                != f"{ARCHIVE_DIR_AGENT_REL}/{plan['artifact_id']}"
            ):
                return ["PORTABILITY_PLAN_METADATA_INVALID"]
        return []

    def acquire_domain_locks(
        self,
    ) -> tuple[list[TransactionLockHandle] | None, str | None]:
        acquired: list[TransactionLockHandle] = []
        prepared: list[tuple[Path, str, os.stat_result]] = []
        for relative, owner in (
            (
                "_runtime/continuity-portability/apply.lock",
                "continuity-portability-apply",
            ),
            ("_runtime/context-memory/apply.lock", "context-memory-apply"),
            ("_runtime/continuity/apply.lock", "continuity-apply"),
        ):
            relative_path = Path(relative)
            parent_relative = relative_path.parent.as_posix()
            parent = self.verified_owned_directory(parent_relative, create=True)
            expected_parent = self.root.joinpath(*relative_path.parent.parts)
            before = self._safe_directory_stat(parent) if parent is not None else None
            if parent != expected_parent or before is None:
                return None, "PORTABILITY_RUNTIME_UNSAFE"
            prepared.append((parent / relative_path.name, owner, before))
        for path, owner, before in prepared:
            try:
                handle = acquire_transaction_lock(path, owner)
            except TransactionLockError as error:
                self.release_domain_locks(acquired)
                if error.reason_code == "TRANSACTION_LOCK_BUSY":
                    return None, "PORTABILITY_TRANSACTION_BUSY"
                if error.reason_code == "TRANSACTION_LOCK_LEGACY_UNVERIFIED":
                    return None, error.reason_code
                return None, "PORTABILITY_RUNTIME_UNSAFE"
            after = self._safe_directory_stat(path.parent)
            if after is None or not self._same_entry(before, after):
                release_transaction_lock(handle)
                self.release_domain_locks(acquired)
                return None, "PORTABILITY_RUNTIME_UNSAFE"
            acquired.append(handle)
        return acquired, None

    def release_domain_locks(
        self,
        acquired: list[TransactionLockHandle],
    ) -> None:
        for handle in reversed(acquired):
            release_transaction_lock(handle)

    def publish_artifact(
        self,
        manifest: dict[str, Any],
        destination: Path,
        *,
        operation: str,
    ) -> dict[str, Any]:
        if operation == "export":
            verified_destination = self.export_destination(destination)
            if verified_destination is None or verified_destination != destination:
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_DESTINATION_DRIFT"],
                }
        else:
            archive_root = self.verified_owned_directory(
                ARCHIVE_DIR_AGENT_REL,
                create=True,
            )
            if archive_root is None or destination.parent != archive_root:
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_ARCHIVE_ROOT_UNSAFE"],
                }
            if destination.exists() or self.path_is_link_like(destination):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_DESTINATION_EXISTS"],
                }
        scoped_base = destination.parent if operation == "export" else self.root
        scoped_parent = "" if operation == "export" else ARCHIVE_DIR_AGENT_REL
        staging = self._create_scoped_temp_directory(
            scoped_base,
            scoped_parent,
            prefix=f".{destination.name}.",
            suffix=".staging",
        )
        if staging is None:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_PUBLISH_FAILED"],
                "error": "unsafe artifact staging directory",
            }
        staging_relative = (
            staging.name
            if not scoped_parent
            else f"{scoped_parent}/{staging.name}"
        )
        try:
            entries = manifest["entries"]
            for entry in entries:
                if operation == "export" and not entry["present"]:
                    continue
                source = self.project_path(entry["canonical_path"])
                payload, _payload_error = read_regular_bounded(
                    source,
                    entry["bytes"],
                )
                if (
                    payload is None
                    or len(payload) != entry["bytes"]
                    or sha256_bytes(payload) != entry["sha256"]
                ):
                    raise ValueError(
                        f"source drift for {entry['canonical_path']}"
                    )
                self._atomic_scoped_bytes(
                    scoped_base,
                    f"{staging_relative}/{entry['storage_path']}",
                    payload,
                    create_parents=True,
                )
            manifest_name = (
                EXPORT_MANIFEST_NAME
                if operation == "export"
                else ARCHIVE_MANIFEST_NAME
            )
            self._atomic_scoped_bytes(
                scoped_base,
                f"{staging_relative}/{manifest_name}",
                json_bytes(manifest),
                create_parents=True,
            )
            if operation == "export":
                verification = self.inspect_bundle(staging)
                if not verification.get("ok"):
                    raise ValueError(
                        f"staged bundle verification failed: {verification.get('reason_codes')}"
                    )
            else:
                verification = self.inspect_archive(staging)
                if not verification.get("ok"):
                    raise ValueError(
                        "staged archive verification failed: "
                        f"{verification.get('reason_codes')}"
                    )
            if operation == "export":
                verified_destination = self.export_destination(destination)
                if (
                    verified_destination is None
                    or verified_destination != destination
                    or staging.parent.resolve(strict=True)
                    != destination.parent.resolve(strict=True)
                ):
                    raise ValueError("export destination changed during publish")
            elif (
                self.verified_owned_directory(
                    ARCHIVE_DIR_AGENT_REL,
                    create=False,
                )
                != destination.parent
                or staging.parent != destination.parent
            ):
                raise ValueError("archive destination changed during publish")
            if not self._rename_scoped_directory(
                scoped_base,
                scoped_parent,
                staging.name,
                destination.name,
            ):
                raise ValueError("artifact destination changed during commit")
            return {"ok": True, "artifact_path": str(destination)}
        except Exception as exc:
            try:
                self._remove_scoped_tree(scoped_base, staging_relative)
            except (OSError, ValueError):
                pass
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_PUBLISH_FAILED"],
                "error": str(exc)[:480],
            }

    def portability_receipt(
        self,
        plan: dict[str, Any],
        artifact_path: Path,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        applied_at = iso_time(self.now())
        seed = {
            "plan_id": plan["plan_id"],
            "operation": plan["operation"],
            "artifact_id": plan["artifact_id"],
            "applied_at": applied_at,
        }
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "receipt_id": f"continuity-portability-{canonical_hash(seed)[:24]}",
            "plan_id": plan["plan_id"],
            "operation": plan["operation"],
            "status": "applied",
            "project_id": plan["project_id"],
            "base_commit": plan["git_head"],
            "applied_at": applied_at,
            "artifact_id": plan["artifact_id"],
            "artifact_path": (
                artifact_path.relative_to(self.project_root).as_posix()
                if plan["operation"] == "archive"
                else f"external-directory/{plan['artifact_id']}"
            ),
            "artifact_state": (
                "durable-verified"
                if plan["operation"] == "archive"
                else "external-unverified"
            ),
            "artifact_manifest": (
                deepcopy(manifest) if plan["operation"] == "export" else None
            ),
            "manifest_sha256": plan["artifact_manifest_sha256"],
            "inventory_sha256": plan["source_inventory_sha256"],
            "binding_sha256": plan["binding_sha256"],
            "adapter_fingerprint_sha256": plan[
                "adapter_fingerprint_sha256"
            ],
            "retention_policy_sha256": plan["retention_policy_sha256"],
            "source_deleted": False,
            "owner_confirmation_performed": False,
            "raw_conversation_stored": False,
            "prompt_stored": False,
            "chain_of_thought_stored": False,
            "secret_stored": False,
            "commit_created": False,
            "push_performed": False,
        }
        receipt["content_sha256"] = receipt_hash(receipt)
        return receipt

    def apply_portability(
        self,
        plan_id: str,
        confirm: bool,
        *,
        expected_operation: str | None = None,
        test_fail_stage: str | None = None,
        test_fail_artifact_cleanup: bool = False,
        test_fail_receipt_cleanup: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            return {
                "ok": False,
                "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"],
            }
        if PLAN_ID.fullmatch(plan_id or "") is None:
            return {"ok": False, "reason_codes": ["PORTABILITY_PLAN_ID_INVALID"]}
        acquired, lock_error = self.acquire_domain_locks()
        if acquired is None:
            return {
                "ok": False,
                "reason_codes": [lock_error or "PORTABILITY_TRANSACTION_BUSY"],
            }
        destination: Path | None = None
        published = False
        receipt_path: Path | None = None
        receipt_relative: str | None = None
        prepared_receipt_content: bytes | None = None
        final_receipt_content: bytes | None = None
        plan: dict[str, Any] | None = None
        plan_relative = f"_runtime/continuity-portability/plans/{plan_id}.json"
        try:
            policy, policy_errors = self.policy()
            if policy is None:
                return {"ok": False, "reason_codes": policy_errors}
            plan_root = self.verified_owned_directory(
                "_runtime/continuity-portability/plans",
                create=False,
            )
            if plan_root is None:
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"],
                }
            plan_path = plan_root / f"{plan_id}.json"
            content, _plan_error = self._read_scoped_regular(
                self.root,
                plan_relative,
                policy["bounds"]["max_manifest_bytes"] * 2,
            )
            if content is None:
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_NOT_FOUND_OR_TAMPERED"],
                }
            try:
                loaded_plan = strict_document(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_NOT_FOUND_OR_TAMPERED"],
                }
            if (
                not isinstance(loaded_plan, dict)
                or loaded_plan.get("status") != "pending-approval"
            ):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_NOT_PENDING"],
                }
            plan = loaded_plan
            errors = self.validate_portability_plan(plan, plan_id)
            if errors:
                return {"ok": False, "reason_codes": errors}
            if (
                expected_operation is not None
                and plan["operation"] != expected_operation
            ):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_OPERATION_MISMATCH"],
                }
            if self.now() > parse_time(plan["expires_at"]):
                return {"ok": False, "reason_codes": ["PORTABILITY_PLAN_EXPIRED"]}
            contracts = self.contract_hashes()
            if (
                self.head() != plan["git_head"]
                or self.binding().get("project_id") != plan["project_id"]
                or contracts is None
                or any(
                    contracts[field] != plan[field]
                    for field in contracts
                )
            ):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_PLAN_ENVIRONMENT_DRIFT"],
                }
            if plan["operation"] == "export":
                prepared = self.prepare_export_apply(plan)
                if not prepared.get("ok"):
                    return prepared
                manifest = prepared["manifest"]
                destination = prepared["destination"]
            else:
                prepared = self.prepare_archive_apply(plan)
                if not prepared.get("ok"):
                    return prepared
                manifest = prepared["manifest"]
                destination = prepared["destination"]
            identifier = (
                manifest["bundle_id"]
                if plan["operation"] == "export"
                else manifest["archive_id"]
            )
            if (
                identifier != plan["artifact_id"]
                or sha256_bytes(json_bytes(manifest))
                != plan["artifact_manifest_sha256"]
                or manifest["inventory_sha256"]
                != plan["source_inventory_sha256"]
                or (
                    plan["operation"] == "archive"
                    and canonical_hash(manifest["summary"])
                    != plan["metadata"]["summary_sha256"]
                )
            ):
                return {
                    "ok": False,
                    "reason_codes": ["PORTABILITY_SOURCE_INVENTORY_DRIFT"],
                }
            published_result = self.publish_artifact(
                manifest,
                destination,
                operation=plan["operation"],
            )
            if not published_result.get("ok"):
                return published_result
            published = True
            receipt = self.portability_receipt(plan, destination, manifest)
            receipt_root = self.verified_owned_directory(
                RECEIPT_DIR_AGENT_REL,
                create=True,
            )
            if receipt_root is None:
                raise RuntimeError("unsafe portability receipt root")
            receipt_path = receipt_root / f"{receipt['receipt_id']}.json"
            receipt_relative = (
                f"{RECEIPT_DIR_AGENT_REL}/{receipt['receipt_id']}.json"
            )
            prepared_receipt = deepcopy(receipt)
            prepared_receipt["status"] = "prepared"
            prepared_receipt["content_sha256"] = receipt_hash(prepared_receipt)
            prepared_receipt_content = json_bytes(prepared_receipt)
            final_receipt_content = json_bytes(receipt)
            self._atomic_scoped_bytes(
                self.root,
                receipt_relative,
                prepared_receipt_content,
                create_parents=True,
            )
            if (
                test_fail_stage == "after-receipt"
                and os.environ.get("AGENT_OS_TEST_MODE") == "1"
            ):
                raise RuntimeError("injected portability failure after receipt")
            plan["status"] = "applied"
            plan["content_sha256"] = receipt_hash(plan)
            self._atomic_scoped_bytes(
                self.root,
                plan_relative,
                json_bytes(plan),
            )
            self._commit_scoped_bytes(
                self.root,
                receipt_relative,
                final_receipt_content,
            )
            return {
                "ok": True,
                "receipt": receipt,
                "artifact_manifest": manifest,
            }
        except Exception as exc:
            receipt_removed = True
            if (
                receipt_path is not None
                and receipt_relative is not None
                and prepared_receipt_content is not None
            ):
                try:
                    current_receipt, _receipt_error = self._read_scoped_regular(
                        self.root,
                        receipt_relative,
                        max(
                            len(prepared_receipt_content),
                            len(final_receipt_content or b""),
                        ),
                    )
                    if _receipt_error == "PORTABILITY_FILE_NOT_FOUND":
                        receipt_removed = True
                    elif current_receipt is None:
                        receipt_removed = False
                    elif current_receipt != prepared_receipt_content:
                        receipt_removed = False
                    elif (
                        test_fail_receipt_cleanup
                        and os.environ.get("AGENT_OS_TEST_MODE") == "1"
                    ):
                        receipt_removed = False
                    else:
                        receipt_removed = self._unlink_scoped_file(
                            self.root,
                            receipt_relative,
                            expected_before_sha256=sha256_bytes(
                                prepared_receipt_content
                            ),
                        )
                except (OSError, ValueError):
                    receipt_removed = False
            artifact_removed = not published
            if published and destination is not None:
                try:
                    if (
                        test_fail_artifact_cleanup
                        and os.environ.get("AGENT_OS_TEST_MODE") == "1"
                    ):
                        raise OSError("injected artifact cleanup failure")
                    if plan is not None and plan["operation"] == "export":
                        cleanup_base, cleanup_relative = self.export_cleanup_target(
                            destination
                        )
                    else:
                        cleanup_base = self.root
                        cleanup_relative = self.archive_cleanup_relative(destination)
                    artifact_removed = self._remove_scoped_tree(
                        cleanup_base,
                        cleanup_relative,
                    )
                except (OSError, ValueError):
                    artifact_removed = False
            plan_failed_recorded = plan is None
            if plan is not None:
                plan["status"] = "failed"
                plan["content_sha256"] = receipt_hash(plan)
                failed_content = json_bytes(plan)
                try:
                    self._atomic_scoped_bytes(
                        self.root,
                        plan_relative,
                        failed_content,
                    )
                    persisted, _persist_error = self._read_scoped_regular(
                        self.root,
                        plan_relative,
                        len(failed_content),
                    )
                    plan_failed_recorded = persisted == failed_content
                except (OSError, ValueError):
                    plan_failed_recorded = False
            rollback_verified = (
                receipt_removed and artifact_removed and plan_failed_recorded
            )
            reason_code = (
                "PORTABILITY_APPLY_FAILED_ROLLED_BACK"
                if rollback_verified
                else "PORTABILITY_APPLY_ROLLBACK_INCOMPLETE"
            )
            return {
                "ok": False,
                "reason_codes": [reason_code],
                "rollback_verified": rollback_verified,
                "false_receipt_removed": receipt_removed,
                "artifact_removed": artifact_removed,
                "failed_plan_recorded": plan_failed_recorded,
                "error": str(exc)[:480],
            }
        finally:
            self.release_domain_locks(acquired)


    def validate_portability_receipt(self, receipt: Any) -> list[str]:
        policy, policy_errors = self.policy()
        if policy is None:
            return policy_errors
        if (
            not isinstance(receipt, dict)
            or set(receipt) != PORTABILITY_RECEIPT_FIELDS
        ):
            return ["PORTABILITY_RECEIPT_INVALID"]
        seed = {
            "plan_id": receipt.get("plan_id"),
            "operation": receipt.get("operation"),
            "artifact_id": receipt.get("artifact_id"),
            "applied_at": receipt.get("applied_at"),
        }
        expected_id = f"continuity-portability-{canonical_hash(seed)[:24]}"
        operation = receipt.get("operation")
        artifact_pattern = BUNDLE_ID if operation == "export" else ARCHIVE_ID
        if (
            receipt.get("schema_version") != 1
            or receipt.get("receipt_id") != expected_id
            or receipt.get("plan_id") is None
            or PLAN_ID.fullmatch(str(receipt["plan_id"])) is None
            or operation not in {"archive", "export"}
            or artifact_pattern.fullmatch(str(receipt.get("artifact_id", "")))
            is None
            or receipt.get("status") != "applied"
            or not isinstance(receipt.get("project_id"), str)
            or not 1 <= len(receipt["project_id"]) <= 128
            or receipt["project_id"] != self.binding().get("project_id")
            or FULL_COMMIT.fullmatch(str(receipt.get("base_commit", ""))) is None
            or not valid_time(receipt.get("applied_at"))
            or not isinstance(receipt.get("artifact_path"), str)
            or not 1 <= len(receipt["artifact_path"]) <= 4096
            or receipt.get("artifact_state")
            not in {"durable-verified", "external-unverified"}
            or any(
                not valid_hash(receipt.get(field))
                for field in (
                    "manifest_sha256",
                    "inventory_sha256",
                    "binding_sha256",
                    "adapter_fingerprint_sha256",
                    "retention_policy_sha256",
                )
            )
            or any(
                receipt.get(field) is not False
                for field in (
                    "source_deleted",
                    "owner_confirmation_performed",
                    "raw_conversation_stored",
                    "prompt_stored",
                    "chain_of_thought_stored",
                    "secret_stored",
                    "commit_created",
                    "push_performed",
                )
            )
            or receipt.get("content_sha256") != receipt_hash(receipt)
            or len(json_bytes(receipt))
            > policy["bounds"]["max_manifest_bytes"] * 2
        ):
            return ["PORTABILITY_RECEIPT_INVALID"]
        if operation == "archive":
            archive_errors = self.validate_archive_portability_receipt_artifact(
                receipt
            )
            if archive_errors:
                return archive_errors
        else:
            export_errors = self.validate_export_portability_receipt_artifact(
                receipt
            )
            if export_errors:
                return export_errors
        return []


    def list_receipts(self) -> dict[str, Any]:
        lexical_directory = self.agent_path(RECEIPT_DIR_AGENT_REL)
        receipts: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        policy, policy_errors = self.policy()
        if policy is None:
            return {
                "ok": False,
                "receipts": [],
                "errors": [{"code": code} for code in policy_errors],
            }
        directory = self.verified_owned_directory(
            RECEIPT_DIR_AGENT_REL,
            create=False,
        )
        if directory is None:
            parent_relative = Path(RECEIPT_DIR_AGENT_REL).parent.as_posix()
            safe_parent = self.verified_owned_directory(
                parent_relative,
                create=False,
            )
            if (
                safe_parent == lexical_directory.parent
                and not lexical_directory.exists()
                and not self.path_is_link_like(lexical_directory)
            ):
                return {"ok": True, "receipts": [], "errors": []}
            return {
                "ok": False,
                "receipts": [],
                "errors": [{"code": "PORTABILITY_RECEIPT_DIRECTORY_INVALID"}],
            }
        names: list[str] = []
        total_bytes = 0
        receipt_bound = policy["bounds"]["max_manifest_bytes"] * 2
        try:
            visited = 0
            with os.scandir(directory) as iterator:
                for item in iterator:
                    visited += 1
                    if visited > policy["bounds"]["max_entries"]:
                        return {
                            "ok": False,
                            "receipts": [],
                            "errors": [
                                {
                                    "code": "PORTABILITY_RECEIPT_BOUND_EXCEEDED"
                                }
                            ],
                        }
                    if not item.name.endswith(".json"):
                        continue
                    try:
                        details = item.stat(follow_symlinks=False)
                    except OSError:
                        details = None
                    if (
                        details is None
                        or self._stat_is_link_like(details)
                        or not stat.S_ISREG(details.st_mode)
                    ):
                        errors.append(
                            {
                                "code": "PORTABILITY_RECEIPT_INVALID",
                                "path": item.name,
                            }
                        )
                        continue
                    size = details.st_size
                    names.append(item.name)
                    total_bytes += size
                    if (
                        len(names) > policy["bounds"]["max_entries"]
                        or size > receipt_bound
                        or total_bytes > policy["bounds"]["max_total_bytes"]
                    ):
                        return {
                            "ok": False,
                            "receipts": [],
                            "errors": [
                                {
                                    "code": "PORTABILITY_RECEIPT_BOUND_EXCEEDED"
                                }
                            ],
                        }
        except OSError:
            return {
                "ok": False,
                "receipts": [],
                "errors": [{"code": "PORTABILITY_RECEIPT_DIRECTORY_INVALID"}],
            }
        for name in sorted(names):
            content, _receipt_error = self._read_scoped_regular(
                self.root,
                f"{RECEIPT_DIR_AGENT_REL}/{name}",
                receipt_bound,
            )
            if content is None:
                errors.append(
                    {"code": "PORTABILITY_RECEIPT_INVALID", "path": name}
                )
                continue
            try:
                receipt = strict_document(content)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                errors.append(
                    {"code": "PORTABILITY_RECEIPT_INVALID", "path": name}
                )
                continue
            validation = (
                self.validate_restore_receipt(receipt)
                if isinstance(receipt, dict)
                and receipt.get("operation") == "restore"
                else self.validate_portability_receipt(receipt)
            )
            if validation or Path(name).stem != receipt.get("receipt_id"):
                errors.append(
                    {
                        "code": (
                            validation[0]
                            if validation
                            else "PORTABILITY_RECEIPT_FILENAME_MISMATCH"
                        ),
                        "path": name,
                    }
                )
                continue
            receipts.append(receipt)
        return {"ok": not errors, "receipts": receipts, "errors": errors}
