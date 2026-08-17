#!/usr/bin/env python3
"""Project-bound Context Memory engine with transactional application-owned writes.

Core owns this engine, its policy, schemas, and templates. Every actual record,
task, handoff, and Project Memory projection remains inside application-owned
scopes. Memory is evidence-indexed context, never a transcript or completion
authority.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_os_paths import safe_join
from agent_os_transaction_lock import (
    TransactionLockError,
    TransactionLockHandle,
    acquire_transaction_lock,
    release_transaction_lock,
)
from context_memory import evidence as context_evidence
from context_memory import handoff_validation as context_handoffs
from context_memory import health as context_health
from context_memory import task_ledger
from context_memory.task_ledger import ACTIVE_TASK_STATES

# Keep the v1 task-ledger symbols import-compatible for existing clients.
LEGACY_OPAQUE_TASK_SCOPE_PREFIXES = task_ledger.LEGACY_OPAQUE_TASK_SCOPE_PREFIXES
TASK_STATES = task_ledger.TASK_STATES
valid_task_scope = task_ledger.valid_task_scope

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = "project/context/context-manifest.json"
HOT_REL = "project/context/hot.json"
WARM_REL = "project/context/warm.json"
COLD_REL = "project/context/cold.json"
TASKS_REL = "project/context/active-tasks.json"
HANDOFF_DIR_REL = "project/context/handoffs"
PROJECTION_REL = "skills/project-memory/SKILL.md"
POLICY_REL = "memory/context-policy.json"
BINDING_REL = "project/project-binding.json"
CORE_MANIFEST_REL = "_manifest/base-release-manifest.json"

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,95}$")
HANDOFF_ID = re.compile(r"^handoff-[0-9a-f]{24}$")
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")
AUTHORITY = ["binding", "git-evidence", "user-confirmed", "project-decision", "research-only", "historical"]
TIERS = {"hot", "warm", "cold"}
EVIDENCE_STALE_CODES = {"CONTEXT_EVIDENCE_STALE", "CONTEXT_EVIDENCE_UNCOMMITTED"}
FORBIDDEN_KEYS = {
    "raw_prompt",
    "raw_prompts",
    "conversation",
    "conversation_history",
    "transcript",
    "chain_of_thought",
    "reasoning_trace",
    "scratchpad",
}
TRANSCRIPT_MARKERS = ("<|assistant|>", "<|user|>", "chain of thought:", "reasoning trace:")
HANDOFF_FIELDS = {
    "schema_version",
    "id",
    "project_id",
    "task_id",
    "from_owner",
    "to_owner",
    "base_commit",
    "created_at",
    "verified_outcomes",
    "unresolved_risks",
    "next_action",
    "evidence",
    "content_sha256",
}
PLAN_FIELDS = {
    "schema_version",
    "plan_id",
    "status",
    "operation",
    "created_at",
    "expires_at",
    "git_head",
    "core_manifest_sha256",
    "project_id",
    "changes",
    "exact_diff",
    "metadata",
    "commit_created",
    "push_performed",
    "content_sha256",
}
PLAN_CHANGE_FIELDS = {
    "path",
    "before_sha256",
    "after_sha256",
    "before_base64",
    "after_base64",
}
PLAN_OPERATIONS = {
    "initialize",
    "refresh",
    "repair-projection",
    "upsert-record",
    "claim-task",
    "continue-task",
    "rekey-task",
    "handoff",
    "compact",
    "migrate-task-ledger",
    "rollback-task-ledger",
}
CONTEXT_STATE_PATHS = {
    HOT_REL,
    WARM_REL,
    COLD_REL,
    TASKS_REL,
    MANIFEST_REL,
    PROJECTION_REL,
}
TIER_PATHS = {
    "hot": HOT_REL,
    "warm": WARM_REL,
    "cold": COLD_REL,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def valid_date_time(value: Any) -> bool:
    if not isinstance(value, str) or DATE_TIME.fullmatch(value) is None:
        return False
    try:
        normalized = value.replace("t", "T")
        if normalized.endswith("z"):
            normalized = normalized[:-1] + "Z"
        parsed = parse_time(normalized)
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def valid_string_list(value: Any, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, list)
        and minimum <= len(value) <= maximum
        and all(isinstance(item, str) and 1 <= len(item) <= 512 for item in value)
    )


def valid_bounded_string_list(
    value: Any,
    minimum_items: int,
    maximum_items: int,
    minimum_length: int,
    maximum_length: int,
) -> bool:
    return (
        isinstance(value, list)
        and minimum_items <= len(value) <= maximum_items
        and all(
            isinstance(item, str) and minimum_length <= len(item) <= maximum_length
            for item in value
        )
    )


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return deepcopy(default)


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def encoded(content: bytes | None) -> str | None:
    return base64.b64encode(content).decode("ascii") if content is not None else None


def decoded(value: str | None) -> bytes | None:
    return base64.b64decode(value.encode("ascii"), validate=True) if value is not None else None


def receipt_hash(document: dict[str, Any]) -> str:
    return canonical_hash({key: value for key, value in document.items() if key != "content_sha256"})


def has_forbidden_payload(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in FORBIDDEN_KEYS or has_forbidden_payload(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_forbidden_payload(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in TRANSCRIPT_MARKERS)
    return False


class ContextMemoryService:
    def __init__(self, agent_root: Path = DEFAULT_ROOT, now: Callable[[], datetime] = now_utc):
        self.root = agent_root.resolve()
        self.project_root = self.root.parent
        self.runtime = self.root / "_runtime" / "context-memory"
        self.plans = self.runtime / "plans"
        self.receipts = self.runtime / "receipts"
        self.lock_path = self.runtime / "apply.lock"
        self.now = now
        self._legacy_evidence_cache: dict[tuple[str, str, str], str | None] = {}

    def path(self, relative: str) -> Path:
        return safe_join(self.root, str(relative))

    def evidence_path(self, relative: str) -> Path:
        return safe_join(self.project_root, str(relative))

    @staticmethod
    def application_owned(relative: str) -> bool:
        return (
            relative in {"project", "skills/project-memory", "skills/project-local"}
            or relative.startswith(
                ("project/", "skills/project-memory/", "skills/project-local/")
            )
        )

    def writable(self, relative: str) -> bool:
        return relative.startswith("project/context/") or relative == PROJECTION_REL

    def read_bytes(self, relative: str) -> bytes | None:
        path = self.path(relative)
        return path.read_bytes() if path.is_file() and not path.is_symlink() else None

    def document(self, relative: str, default: Any) -> Any:
        return load_json(self.path(relative), default)

    def git(self, *arguments: str) -> str | None:
        return context_evidence.git(self, *arguments)

    def head(self) -> str | None:
        return context_evidence.head(self)

    def commit_is_ancestor(self, commit: str) -> bool:
        return context_evidence.commit_is_ancestor(self, commit)

    def commit_exists(self, commit: str) -> bool:
        return context_evidence.commit_exists(self, commit)

    def git_blob_bytes(self, commit: str, relative: str) -> bytes | None:
        return context_evidence.git_blob_bytes(self, commit, relative)

    def git_path_is_clean(self, relative: str) -> bool:
        return context_evidence.git_path_is_clean(self, relative)

    def committed_evidence_ref(self, relative: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        return context_evidence.committed_evidence_ref(self, relative)

    def validate_git_evidence_ref(
        self,
        ref: dict[str, Any],
        *,
        require_current: bool,
    ) -> list[dict[str, Any]]:
        return context_evidence.validate_git_evidence_ref(
            self,
            ref,
            require_current=require_current,
        )

    def find_reachable_evidence_commit(
        self,
        relative: str,
        expected_sha256: str,
        preferred_commit: str | None = None,
    ) -> str | None:
        return context_evidence.find_reachable_evidence_commit(
            self,
            relative,
            expected_sha256,
            preferred_commit,
        )

    def binding(self) -> dict[str, Any]:
        return self.document(BINDING_REL, {})

    def policy(self) -> dict[str, Any]:
        return self.document(POLICY_REL, {})

    @staticmethod
    def normalize_remote(value: str) -> str:
        return context_evidence.normalize_remote(value)

    def current_remote_aliases(self) -> set[str]:
        return context_evidence.current_remote_aliases(self)

    def default_stores(self, project_id: str) -> dict[str, dict[str, Any]]:
        return {
            HOT_REL: {"schema_version": 1, "project_id": project_id, "tier": "hot", "records": []},
            WARM_REL: {"schema_version": 1, "project_id": project_id, "tier": "warm", "records": []},
            COLD_REL: {"schema_version": 1, "project_id": project_id, "tier": "cold", "records": []},
            TASKS_REL: {"schema_version": 1, "project_id": project_id, "tasks": []},
        }

    def source_entry(self, identifier: str, tier: str, relative: str, content: bytes) -> dict[str, Any]:
        authority = {"hot": "git-evidence", "warm": "project-decision", "cold": "research-only"}[tier]
        keys = {
            "hot": ["identity", "current-state", "guardrails"],
            "warm": ["decisions", "architecture", "conventions", "known-issues"],
            "cold": ["research", "history"],
        }[tier]
        return {
            "id": identifier,
            "tier": tier,
            "path": relative,
            "owner": "application",
            "format": "context-store-json",
            "load_policy": {"hot": "boot", "warm": "just-in-time", "cold": "explicit-only"}[tier],
            "authority": authority,
            "content_sha256": sha256_bytes(content),
            "canonical_keys": keys,
        }

    def render_manifest(self, project_id: str, stores: dict[str, bytes], task_content: bytes, existing: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = existing or {}
        aliases = sorted(
            {
                str(item) for item in self.binding().get("repository", {}).get("remote_aliases", [])
                if isinstance(item, str) and item
            }
        ) or ["local-repository"]
        budgets = existing.get("budgets") if isinstance(existing.get("budgets"), dict) else {
            "hot_max_bytes": 32768,
            "warm_max_bytes": 131072,
            "cold_max_records": 5000,
            "projection_max_bytes": 16384,
        }
        return {
            "schema_version": 1,
            "project_id": project_id,
            "repository": {"remote_aliases": aliases},
            "authority_order": AUTHORITY,
            "sources": [
                self.source_entry("hot-context", "hot", HOT_REL, stores[HOT_REL]),
                self.source_entry("warm-context", "warm", WARM_REL, stores[WARM_REL]),
                self.source_entry("cold-context", "cold", COLD_REL, stores[COLD_REL]),
            ],
            "active_task_ledger": TASKS_REL,
            "active_task_ledger_sha256": sha256_bytes(task_content),
            "handoff_directory": HANDOFF_DIR_REL,
            "projection": PROJECTION_REL,
            "budgets": budgets,
            "refreshed_at": iso_time(self.now()),
            "refreshed_commit": self.head(),
        }

    def validate_record(
        self,
        record: Any,
        tier: str,
        project_id: str,
        *,
        verify_evidence: bool = True,
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        required = {
            "schema_version", "id", "project_id", "tier", "kind", "title", "summary",
            "status", "authority", "source_refs", "created_at", "updated_at", "supersedes", "tags",
        }
        if not isinstance(record, dict) or set(record) != required:
            return [{"code": "CONTEXT_RECORD_FIELDS_INVALID", "id": record.get("id") if isinstance(record, dict) else None}]
        if has_forbidden_payload(record):
            errors.append({"code": "RAW_CONVERSATION_OR_REASONING_FORBIDDEN", "id": record.get("id")})
        if record.get("schema_version") != 1 or not SAFE_ID.fullmatch(str(record.get("id", ""))):
            errors.append({"code": "CONTEXT_RECORD_ID_INVALID", "id": record.get("id")})
        if record.get("project_id") != project_id:
            errors.append({"code": "CONTEXT_PROJECT_CONTAMINATION", "id": record.get("id"), "actual": record.get("project_id")})
        if record.get("tier") != tier:
            errors.append({"code": "CONTEXT_RECORD_TIER_MISMATCH", "id": record.get("id")})
        allowed_kinds = set(self.policy().get("tiers", {}).get(tier, {}).get("allowed_kinds", []))
        if record.get("kind") not in allowed_kinds:
            errors.append({"code": "CONTEXT_KIND_NOT_ALLOWED_IN_TIER", "id": record.get("id"), "kind": record.get("kind"), "tier": tier})
        if record.get("authority") not in AUTHORITY:
            errors.append({"code": "CONTEXT_AUTHORITY_INVALID", "id": record.get("id")})
        if record.get("authority") == "research-only" and tier != "cold":
            errors.append({"code": "RESEARCH_AUTHORITY_COLD_ONLY", "id": record.get("id")})
        if record.get("status") not in {"active", "superseded", "archived"}:
            errors.append({"code": "CONTEXT_RECORD_STATUS_INVALID", "id": record.get("id")})
        if not isinstance(record.get("title"), str) or not 3 <= len(record["title"]) <= 200:
            errors.append({"code": "CONTEXT_TITLE_INVALID", "id": record.get("id")})
        if not isinstance(record.get("summary"), str) or not 3 <= len(record["summary"]) <= 4000:
            errors.append({"code": "CONTEXT_SUMMARY_INVALID", "id": record.get("id")})
        for field in ("created_at", "updated_at"):
            try:
                parse_time(str(record.get(field, "")))
            except (TypeError, ValueError):
                errors.append({"code": "CONTEXT_TIMESTAMP_INVALID", "id": record.get("id"), "field": field})
        refs = record.get("source_refs") if isinstance(record.get("source_refs"), list) else []
        if not refs:
            errors.append({"code": "CONTEXT_EVIDENCE_REQUIRED", "id": record.get("id")})
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) - {"path", "sha256", "git_commit"} or not {"path", "sha256"} <= set(ref):
                errors.append({"code": "CONTEXT_EVIDENCE_INVALID", "id": record.get("id")})
                continue
            try:
                self.evidence_path(str(ref.get("path", "")))
            except ValueError:
                errors.append({"code": "CONTEXT_EVIDENCE_PATH_UNSAFE", "id": record.get("id"), "path": ref.get("path")})
                continue
            commit = ref.get("git_commit")
            if not SHA256.fullmatch(str(ref.get("sha256", ""))):
                errors.append({"code": "CONTEXT_EVIDENCE_HASH_INVALID", "id": record.get("id"), "path": ref.get("path")})
                continue
            if commit is not None and not FULL_COMMIT.fullmatch(str(commit)):
                errors.append({"code": "CONTEXT_EVIDENCE_COMMIT_INVALID", "id": record.get("id"), "path": ref.get("path")})
                continue
            if verify_evidence:
                errors.extend(
                    {**item, "id": record.get("id")}
                    for item in self.validate_git_evidence_ref(ref, require_current=True)
                )
        if not isinstance(record.get("supersedes"), list) or not isinstance(record.get("tags"), list):
            errors.append({"code": "CONTEXT_RECORD_LIST_FIELDS_INVALID", "id": record.get("id")})
        return errors

    def validate_store(
        self,
        store: Any,
        tier: str,
        project_id: str,
        *,
        verify_evidence: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        if not isinstance(store, dict) or set(store) != {"schema_version", "project_id", "tier", "records"}:
            return [{"code": "CONTEXT_STORE_FIELDS_INVALID", "tier": tier}], records
        if store.get("schema_version") != 1 or store.get("project_id") != project_id or store.get("tier") != tier:
            errors.append({"code": "CONTEXT_STORE_CONTAMINATION_OR_TIER_MISMATCH", "tier": tier})
        raw_records = store.get("records") if isinstance(store.get("records"), list) else []
        identifiers: set[str] = set()
        for record in raw_records:
            errors.extend(self.validate_record(record, tier, project_id, verify_evidence=verify_evidence))
            if isinstance(record, dict):
                identifier = str(record.get("id", ""))
                if identifier in identifiers:
                    errors.append({"code": "CONTEXT_RECORD_DUPLICATED", "id": identifier})
                identifiers.add(identifier)
                records.append(record)
        return errors, records

    @staticmethod
    def normalized_scope(value: str) -> str:
        return task_ledger.normalized_scope(value)

    @classmethod
    def scopes_overlap(cls, left: list[str], right: list[str]) -> bool:
        return task_ledger.scopes_overlap(left, right)

    def validate_tasks(self, ledger: Any, project_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        return task_ledger.validate_tasks(self, ledger, project_id)

    def validate_handoffs(self) -> dict[str, Any]:
        return context_handoffs.validate_handoffs(self)

    def validate_manifest(
        self,
        manifest: Any,
        verify_hashes: bool = True,
        verify_evidence: bool = True,
        verify_handoffs: bool = True,
    ) -> dict[str, Any]:
        binding = self.binding()
        project_id = binding.get("project_id")
        errors: list[dict[str, Any]] = []
        stale: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        required = {
            "schema_version", "project_id", "repository", "authority_order", "sources",
            "active_task_ledger", "active_task_ledger_sha256", "handoff_directory", "projection", "budgets", "refreshed_at", "refreshed_commit",
        }
        if not isinstance(manifest, dict) or set(manifest) != required:
            return {
                "errors": [{"code": "CONTEXT_MANIFEST_FIELDS_INVALID"}],
                "stale": [],
                "conflicts": [],
                "warnings": [],
                "stores": {},
                "tasks": {},
                "handoff_durability": {},
            }
        if manifest.get("schema_version") != 1 or not project_id or manifest.get("project_id") != project_id:
            errors.append({"code": "CONTEXT_MANIFEST_PROJECT_CONTAMINATION", "expected": project_id, "actual": manifest.get("project_id")})
        repository = manifest.get("repository")
        aliases: set[str] = set()
        repository_valid = (
            isinstance(repository, dict)
            and set(repository) == {"remote_aliases"}
            and isinstance(repository.get("remote_aliases"), list)
            and bool(repository["remote_aliases"])
            and all(
                isinstance(item, str) and 1 <= len(item) <= 256
                for item in repository["remote_aliases"]
            )
        )
        if not repository_valid:
            errors.append({"code": "CONTEXT_MANIFEST_REPOSITORY_INVALID"})
        else:
            aliases = {
                self.normalize_remote(item)
                for item in repository["remote_aliases"]
            }
        current_aliases = self.current_remote_aliases()
        if repository_valid and current_aliases and not aliases.intersection(current_aliases):
            errors.append({"code": "CONTEXT_REPOSITORY_CONTAMINATION", "manifest_aliases": sorted(aliases), "binding_aliases": sorted(current_aliases)})
        if manifest.get("authority_order") != AUTHORITY:
            errors.append({"code": "CONTEXT_AUTHORITY_ORDER_INVALID"})
        source_ids: set[str] = set()
        keys_by_rank: dict[tuple[int, str], tuple[str, str]] = {}
        stores: dict[str, Any] = {}
        records_by_tier: dict[str, list[dict[str, Any]]] = {tier: [] for tier in TIERS}
        raw_sources = manifest.get("sources")
        if not isinstance(raw_sources, list):
            errors.append({"code": "CONTEXT_MANIFEST_SOURCES_INVALID"})
        sources = raw_sources if isinstance(raw_sources, list) else []
        for source in sources:
            source_required = {"id", "tier", "path", "owner", "format", "load_policy", "authority", "content_sha256", "canonical_keys"}
            if not isinstance(source, dict) or set(source) - (source_required | {"connector"}) or not source_required <= set(source):
                errors.append({"code": "CONTEXT_SOURCE_FIELDS_INVALID"})
                continue
            canonical_keys = source.get("canonical_keys")
            connector = source.get("connector")
            if (
                not isinstance(source.get("id"), str)
                or not isinstance(source.get("tier"), str)
                or not isinstance(source.get("path"), str)
                or not isinstance(source.get("owner"), str)
                or not isinstance(source.get("format"), str)
                or not isinstance(source.get("load_policy"), str)
                or not isinstance(source.get("authority"), str)
                or not SHA256.fullmatch(str(source.get("content_sha256", "")))
                or not isinstance(canonical_keys, list)
                or not canonical_keys
                or not all(isinstance(key, str) and 1 <= len(key) <= 128 for key in canonical_keys)
                or (connector is not None and (not isinstance(connector, str) or len(connector) > 64))
            ):
                errors.append({"code": "CONTEXT_SOURCE_FIELDS_INVALID", "id": source.get("id")})
                continue
            identifier = str(source.get("id", ""))
            tier = str(source.get("tier", ""))
            relative = str(source.get("path", ""))
            if not SAFE_ID.fullmatch(identifier) or identifier in source_ids:
                errors.append({"code": "CONTEXT_SOURCE_ID_INVALID_OR_DUPLICATED", "id": identifier})
            source_ids.add(identifier)
            if tier not in TIERS or source.get("owner") != "application" or not self.application_owned(relative):
                errors.append({"code": "CONTEXT_SOURCE_OWNERSHIP_OR_TIER_INVALID", "id": identifier, "path": relative})
                continue
            expected_load = {"hot": "boot", "warm": "just-in-time", "cold": "explicit-only"}[tier]
            if source.get("load_policy") != expected_load:
                errors.append({"code": "CONTEXT_LOAD_POLICY_INVALID", "id": identifier})
            if source.get("connector") == "notebooklm" and (tier != "cold" or source.get("authority") != "research-only"):
                errors.append({"code": "NOTEBOOKLM_COLD_RESEARCH_ONLY", "id": identifier})
            try:
                content = self.read_bytes(relative)
            except ValueError:
                errors.append({"code": "CONTEXT_SOURCE_PATH_UNSAFE", "id": identifier, "path": relative})
                continue
            if content is None:
                errors.append({"code": "CONTEXT_SOURCE_MISSING", "id": identifier, "path": relative})
                continue
            actual_hash = sha256_bytes(content)
            if verify_hashes and actual_hash != source.get("content_sha256"):
                stale.append({"code": "CONTEXT_SOURCE_STALE", "id": identifier, "path": relative, "expected": source.get("content_sha256"), "actual": actual_hash})
            store = load_json(self.path(relative), None)
            store_errors, records = self.validate_store(
                store,
                tier,
                str(project_id),
                verify_evidence=verify_evidence,
            )
            errors.extend({**item, "source": identifier} for item in store_errors if item.get("code") not in EVIDENCE_STALE_CODES)
            stale.extend({**item, "source": identifier} for item in store_errors if item.get("code") in EVIDENCE_STALE_CODES)
            stores[relative] = store
            records_by_tier[tier].extend(records)
            try:
                rank = AUTHORITY.index(str(source.get("authority")))
            except ValueError:
                errors.append({"code": "CONTEXT_SOURCE_AUTHORITY_INVALID", "id": identifier})
                rank = len(AUTHORITY)
            for key in canonical_keys:
                identity = (rank, str(key))
                previous = keys_by_rank.get(identity)
                if previous and previous[1] != actual_hash:
                    conflicts.append({"code": "CONTEXT_AUTHORITY_CONFLICT", "canonical_key": key, "sources": [previous[0], identifier]})
                keys_by_rank[identity] = (identifier, actual_hash)
        observed_tiers = {
            source.get("tier")
            for source in sources
            if isinstance(source, dict) and isinstance(source.get("tier"), str)
        }
        if observed_tiers != TIERS:
            errors.append({"code": "CONTEXT_TIERS_INCOMPLETE"})
        if (
            manifest.get("active_task_ledger") != TASKS_REL
            or manifest.get("handoff_directory") != HANDOFF_DIR_REL
            or manifest.get("projection") != PROJECTION_REL
        ):
            errors.append({"code": "CONTEXT_STANDARD_PATHS_INVALID"})
        ledger = self.document(TASKS_REL, {})
        ledger_content = self.read_bytes(TASKS_REL)
        if ledger_content is None:
            errors.append({"code": "TASK_LEDGER_MISSING"})
        elif verify_hashes and sha256_bytes(ledger_content) != manifest.get("active_task_ledger_sha256"):
            stale.append({"code": "TASK_LEDGER_STALE", "path": TASKS_REL})
        task_errors, task_stale, task_conflicts = self.validate_tasks(ledger, str(project_id))
        errors.extend(task_errors)
        stale.extend(task_stale)
        conflicts.extend(task_conflicts)
        refreshed_commit = manifest.get("refreshed_commit")
        if refreshed_commit is not None and not self.commit_is_ancestor(str(refreshed_commit)):
            stale.append({"code": "CONTEXT_MANIFEST_COMMIT_STALE", "refreshed_commit": refreshed_commit, "current_head": self.head()})
        handoff_validation = (
            context_handoffs.validate_for_doctor(self)
            if verify_handoffs
            else {"errors": [], "warnings": [], "summary": {}}
        )
        errors.extend(handoff_validation["errors"])
        raw_budgets = manifest.get("budgets")
        budget_fields = {
            "hot_max_bytes",
            "warm_max_bytes",
            "cold_max_records",
            "projection_max_bytes",
        }
        budgets_valid = (
            isinstance(raw_budgets, dict)
            and set(raw_budgets) == budget_fields
            and all(type(raw_budgets.get(field)) is int for field in budget_fields)
            and 1024 <= raw_budgets["hot_max_bytes"] <= 262144
            and 1024 <= raw_budgets["warm_max_bytes"] <= 1048576
            and 1 <= raw_budgets["cold_max_records"] <= 100000
            and 512 <= raw_budgets["projection_max_bytes"] <= 65536
        )
        if not budgets_valid:
            errors.append({"code": "CONTEXT_MANIFEST_BUDGETS_INVALID"})
        budgets = raw_budgets if budgets_valid else {}
        for tier, records in records_by_tier.items():
            budget = budgets.get(f"{tier}_max_bytes")
            if tier in {"hot", "warm"} and isinstance(budget, int):
                size = len(json_bytes({"records": records}))
                if size > budget:
                    errors.append({"code": "CONTEXT_TIER_BUDGET_EXCEEDED", "tier": tier, "bytes": size, "maximum": budget})
            if tier == "cold" and isinstance(budgets.get("cold_max_records"), int) and len(records) > budgets["cold_max_records"]:
                errors.append({"code": "CONTEXT_TIER_BUDGET_EXCEEDED", "tier": tier, "records": len(records)})
        projection_content = self.read_bytes(PROJECTION_REL)
        if projection_content is None:
            errors.append({"code": "CONTEXT_PROJECTION_MISSING_OR_UNSAFE", "path": PROJECTION_REL})
        elif (
            budgets_valid
            and isinstance(ledger, dict)
            and all(
                isinstance(stores.get(relative), dict)
                for relative in (HOT_REL, WARM_REL, COLD_REL)
            )
        ):
            try:
                expected_projection = self.render_projection(
                    str(project_id),
                    {
                        "hot": stores[HOT_REL],
                        "warm": stores[WARM_REL],
                        "cold": stores[COLD_REL],
                    },
                    ledger,
                    budgets["projection_max_bytes"],
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                errors.append({"code": "CONTEXT_PROJECTION_RENDER_INVALID", "path": PROJECTION_REL})
            else:
                if projection_content != expected_projection:
                    errors.append({"code": "CONTEXT_PROJECTION_NON_CANONICAL", "path": PROJECTION_REL})
        return {
            "errors": errors,
            "stale": stale,
            "conflicts": conflicts,
            "warnings": handoff_validation["warnings"],
            "stores": stores,
            "tasks": ledger,
            "records_by_tier": records_by_tier,
            "handoff_durability": handoff_validation["summary"],
        }

    def doctor(self) -> dict[str, Any]:
        return context_health.doctor(self)

    def validate_current_authority(self, manifest: Any) -> dict[str, Any]:
        return self.validate_manifest(
            manifest,
            verify_evidence=False,
            verify_handoffs=False,
        )

    def load(self, tier: str = "hot") -> dict[str, Any]:
        return context_health.load(self, tier)

    def evidence_refs(self, paths: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        if not isinstance(paths, list) or not paths:
            return refs, [{"code": "CONTEXT_EVIDENCE_REQUIRED"}]
        for value in paths[:32]:
            relative = str(value)
            ref, ref_errors = self.committed_evidence_ref(relative)
            errors.extend(ref_errors)
            if ref is not None:
                refs.append(ref)
        return refs, errors

    def build_record(self, proposal: Any, project_id: str, existing: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if not isinstance(proposal, dict) or has_forbidden_payload(proposal):
            return None, [{"code": "RAW_CONVERSATION_OR_REASONING_FORBIDDEN"}]
        allowed = {"id", "tier", "kind", "title", "summary", "authority", "evidence", "supersedes", "tags"}
        if set(proposal) - allowed:
            return None, [{"code": "CONTEXT_PROPOSAL_FIELDS_INVALID", "unexpected": sorted(set(proposal) - allowed)}]
        identifier = str(proposal.get("id", ""))
        tier = str(proposal.get("tier", ""))
        if not SAFE_ID.fullmatch(identifier) or tier not in TIERS:
            return None, [{"code": "CONTEXT_PROPOSAL_ID_OR_TIER_INVALID"}]
        refs, errors = self.evidence_refs(proposal.get("evidence"))
        timestamp = iso_time(self.now())
        record = {
            "schema_version": 1,
            "id": identifier,
            "project_id": project_id,
            "tier": tier,
            "kind": proposal.get("kind"),
            "title": proposal.get("title"),
            "summary": proposal.get("summary"),
            "status": "active",
            "authority": proposal.get("authority"),
            "source_refs": refs,
            "created_at": existing.get("created_at") if isinstance(existing, dict) else timestamp,
            "updated_at": timestamp,
            "supersedes": proposal.get("supersedes", []),
            "tags": proposal.get("tags", []),
        }
        errors.extend(self.validate_record(record, tier, project_id))
        return record, errors

    def render_projection(self, project_id: str, stores: dict[str, dict[str, Any]], tasks: dict[str, Any], maximum: int) -> bytes:
        lines = [
            "---",
            "name: project-memory",
            f"description: Generated Context Memory projection for {project_id}. Load only after Agent OS and Context Memory doctors permit it.",
            "---",
            "",
            "# Project Memory Projection",
            "",
            f"Project ID: `{project_id}`",
            "",
            "This is a compact projection, not the memory database. Current Git and",
            "canonical project evidence override stale or conflicting memory.",
        ]
        for tier in ("hot", "warm"):
            active = [item for item in stores.get(tier, {}).get("records", []) if item.get("status") == "active"]
            if not active:
                continue
            lines.extend(["", f"## {tier.title()} context", ""])
            for record in active:
                lines.append(f"- **{record.get('title')}**: {record.get('summary')}")
        active_tasks = [item for item in tasks.get("tasks", []) if item.get("status") in ACTIVE_TASK_STATES]
        if active_tasks:
            lines.extend(["", "## Active tasks", ""])
            for task in active_tasks:
                lines.append(f"- `{task.get('id')}` — {task.get('title')} (owner: `{task.get('owner')}`, base: `{str(task.get('base_commit'))[:12]}`)")
        content = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
        if len(content) > maximum:
            raise ValueError(f"projection exceeds budget: {len(content)} > {maximum}")
        return content

    def desired_with_manifest(self, stores: dict[str, dict[str, Any]], tasks: dict[str, Any], existing_manifest: dict[str, Any] | None = None, extra: dict[str, bytes | None] | None = None) -> dict[str, bytes | None]:
        project_id = str(self.binding().get("project_id", ""))
        store_bytes = {
            HOT_REL: json_bytes(stores["hot"]),
            WARM_REL: json_bytes(stores["warm"]),
            COLD_REL: json_bytes(stores["cold"]),
        }
        task_content = json_bytes(tasks)
        manifest = self.render_manifest(project_id, store_bytes, task_content, existing_manifest)
        projection = self.render_projection(project_id, stores, tasks, manifest["budgets"]["projection_max_bytes"])
        desired: dict[str, bytes | None] = {
            **store_bytes,
            TASKS_REL: task_content,
            PROJECTION_REL: projection,
            MANIFEST_REL: json_bytes(manifest),
        }
        desired.update(extra or {})
        return desired

    def current_stores(self) -> dict[str, dict[str, Any]]:
        return {
            "hot": self.document(HOT_REL, {}),
            "warm": self.document(WARM_REL, {}),
            "cold": self.document(COLD_REL, {}),
        }

    @staticmethod
    def valid_hash(value: Any, *, nullable: bool = False) -> bool:
        return (nullable and value is None) or (
            isinstance(value, str) and SHA256.fullmatch(value) is not None
        )

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

    def validate_plan_metadata(
        self,
        operation: str,
        metadata: Any,
        change_paths: set[str],
    ) -> list[str]:
        if not isinstance(metadata, dict) or has_forbidden_payload(metadata):
            return ["CONTEXT_PLAN_METADATA_INVALID"]
        fields = set(metadata)
        if operation == "initialize":
            if (
                fields != {"project_id"}
                or metadata.get("project_id") != self.binding().get("project_id")
                or change_paths != CONTEXT_STATE_PATHS
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            return []
        if operation == "refresh":
            previous = metadata.get("previous_refreshed_commit")
            if (
                fields != {"previous_refreshed_commit"}
                or (
                    previous is not None
                    and (
                        not isinstance(previous, str)
                        or FULL_COMMIT.fullmatch(previous) is None
                    )
                )
                or MANIFEST_REL not in change_paths
                or not change_paths <= {
                    HOT_REL,
                    WARM_REL,
                    COLD_REL,
                    MANIFEST_REL,
                    PROJECTION_REL,
                }
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            return []
        if operation == "repair-projection":
            if (
                fields != {"repair"}
                or metadata.get("repair") != "canonical-projection"
                or change_paths != {PROJECTION_REL}
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            return []
        if operation == "upsert-record":
            tier = metadata.get("tier")
            record_id = metadata.get("record_id")
            allowed_paths = {
                TIER_PATHS.get(str(tier), ""),
                MANIFEST_REL,
                PROJECTION_REL,
            }
            if (
                fields != {"record_id", "tier"}
                or not isinstance(record_id, str)
                or SAFE_ID.fullmatch(record_id) is None
                or tier not in TIERS
                or TIER_PATHS[tier] not in change_paths
                or MANIFEST_REL not in change_paths
                or not change_paths <= allowed_paths
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            return []
        if operation in {"claim-task", "continue-task"}:
            required = {"task_id", "owner"}
            if operation == "continue-task":
                required |= {"previous_base_commit", "continued_base_commit"}
            task_id = metadata.get("task_id")
            owner = metadata.get("owner")
            if (
                fields != required
                or not isinstance(task_id, str)
                or SAFE_ID.fullmatch(task_id) is None
                or not isinstance(owner, str)
                or not 1 <= len(owner) <= 128
                or change_paths != {TASKS_REL, MANIFEST_REL, PROJECTION_REL}
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            if operation == "continue-task" and any(
                not isinstance(metadata.get(field), str)
                or FULL_COMMIT.fullmatch(metadata[field]) is None
                for field in ("previous_base_commit", "continued_base_commit")
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            return []
        if operation == "rekey-task":
            task_id = metadata.get("task_id")
            replacement_id = metadata.get("replacement_id")
            owner = metadata.get("owner")
            replacement_owner = metadata.get("replacement_owner")
            return [] if (
                fields == {
                    "task_id",
                    "replacement_id",
                    "owner",
                    "replacement_owner",
                    "previous_base_commit",
                    "continued_base_commit",
                }
                and isinstance(task_id, str)
                and SAFE_ID.fullmatch(task_id) is not None
                and isinstance(replacement_id, str)
                and SAFE_ID.fullmatch(replacement_id) is not None
                and replacement_id != task_id
                and isinstance(owner, str)
                and 1 <= len(owner) <= 128
                and isinstance(replacement_owner, str)
                and 1 <= len(replacement_owner) <= 128
                and all(
                    isinstance(metadata.get(field), str)
                    and FULL_COMMIT.fullmatch(metadata[field]) is not None
                    for field in ("previous_base_commit", "continued_base_commit")
                )
                and change_paths == {TASKS_REL, MANIFEST_REL, PROJECTION_REL}
            ) else ["CONTEXT_PLAN_METADATA_INVALID"]
        if operation == "handoff":
            task_id = metadata.get("task_id")
            handoff_id = metadata.get("handoff_id")
            handoff_path = f"{HANDOFF_DIR_REL}/{handoff_id}.json"
            base_paths = {TASKS_REL, MANIFEST_REL, PROJECTION_REL, handoff_path}
            if fields == {"task_id", "handoff_id"}:
                return [] if (
                    isinstance(task_id, str)
                    and SAFE_ID.fullmatch(task_id) is not None
                    and isinstance(handoff_id, str)
                    and HANDOFF_ID.fullmatch(handoff_id) is not None
                    and {TASKS_REL, MANIFEST_REL, handoff_path} <= change_paths
                    and change_paths <= base_paths
                ) else ["CONTEXT_PLAN_METADATA_INVALID"]
            if fields == {"task_id", "handoff_id", "ledger_mode", "segment_id", "segment_path", "index_path"}:
                segment_id = metadata.get("segment_id")
                segment_path = metadata.get("segment_path")
                index_path = metadata.get("index_path")
                allowed = base_paths | {index_path, segment_path}
                return [] if (
                    isinstance(task_id, str)
                    and SAFE_ID.fullmatch(task_id) is not None
                    and isinstance(handoff_id, str)
                    and HANDOFF_ID.fullmatch(handoff_id) is not None
                    and metadata.get("ledger_mode") == "v2-terminal-segment"
                    and isinstance(segment_id, str)
                    and SAFE_ID.fullmatch(segment_id) is not None
                    and index_path == "project/context/task-ledger/index.json"
                    and segment_path == f"project/context/task-ledger/segments/{segment_id}.json"
                    and {TASKS_REL, MANIFEST_REL, index_path, segment_path, handoff_path} <= change_paths
                    and change_paths <= allowed
                ) else ["CONTEXT_PLAN_METADATA_INVALID"]
            return ["CONTEXT_PLAN_METADATA_INVALID"]
        if operation == "compact":
            archived = metadata.get("archived_record_ids")
            summary_id = metadata.get("summary_id")
            if (
                fields
                != {"archived_record_ids", "summary_id", "records_deleted"}
                or not isinstance(archived, list)
                or not archived
                or not all(
                    isinstance(item, str) and SAFE_ID.fullmatch(item) is not None
                    for item in archived
                )
                or archived != sorted(archived)
                or len(archived) != len(set(archived))
                or not isinstance(summary_id, str)
                or SAFE_ID.fullmatch(summary_id) is None
                or summary_id in archived
                or type(metadata.get("records_deleted")) is not int
                or metadata["records_deleted"] != 0
                or not {COLD_REL, MANIFEST_REL} <= change_paths
                or not change_paths <= {COLD_REL, MANIFEST_REL, PROJECTION_REL}
            ):
                return ["CONTEXT_PLAN_METADATA_INVALID"]
            return []
        if operation in {"migrate-task-ledger", "rollback-task-ledger"}:
            return task_ledger.validate_transition_metadata(operation, metadata, change_paths)
        return ["CONTEXT_PLAN_METADATA_INVALID"]

    def validate_compaction_transition(
        self,
        plan: dict[str, Any],
        changes: dict[str, tuple[bytes | None, bytes | None]],
    ) -> list[str]:
        invalid = ["CONTEXT_COMPACTION_TRANSITION_INVALID"]
        if set(changes) != {COLD_REL, MANIFEST_REL}:
            return invalid

        cold_before_bytes, cold_after_bytes = changes[COLD_REL]
        manifest_before_bytes, manifest_after_bytes = changes[MANIFEST_REL]
        current_hot_bytes = self.read_bytes(HOT_REL)
        current_warm_bytes = self.read_bytes(WARM_REL)
        current_task_bytes = self.read_bytes(TASKS_REL)
        current_projection_bytes = self.read_bytes(PROJECTION_REL)
        if any(
            content is None
            for content in (
                cold_before_bytes,
                cold_after_bytes,
                manifest_before_bytes,
                manifest_after_bytes,
                current_hot_bytes,
                current_warm_bytes,
                current_task_bytes,
                current_projection_bytes,
            )
        ):
            return invalid

        try:
            cold_before = json.loads(cold_before_bytes.decode("utf-8"))
            cold_after = json.loads(cold_after_bytes.decode("utf-8"))
            manifest_before = json.loads(manifest_before_bytes.decode("utf-8"))
            manifest_after = json.loads(manifest_after_bytes.decode("utf-8"))
            hot = json.loads(current_hot_bytes.decode("utf-8"))
            warm = json.loads(current_warm_bytes.decode("utf-8"))
            tasks = json.loads(current_task_bytes.decode("utf-8"))
            plan_created = parse_time(str(plan["created_at"]))
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return invalid

        project_id = str(plan.get("project_id", ""))
        before_errors, before_records = self.validate_store(
            cold_before,
            "cold",
            project_id,
            verify_evidence=False,
        )
        after_errors, after_records = self.validate_store(
            cold_after,
            "cold",
            project_id,
            verify_evidence=False,
        )
        if (
            before_errors
            or after_errors
            or not isinstance(cold_before.get("records"), list)
            or not isinstance(cold_after.get("records"), list)
            or not isinstance(hot, dict)
            or not isinstance(warm, dict)
            or not isinstance(tasks, dict)
        ):
            return invalid

        metadata = plan.get("metadata")
        if not isinstance(metadata, dict):
            return invalid
        archived_ids = metadata.get("archived_record_ids")
        summary_id = metadata.get("summary_id")
        if not isinstance(archived_ids, list) or not isinstance(summary_id, str):
            return invalid

        before_by_id = {str(record.get("id")): record for record in before_records}
        after_by_id = {str(record.get("id")): record for record in after_records}
        expected_after_ids = set(before_by_id) | {summary_id}
        if (
            summary_id in before_by_id
            or set(after_by_id) != expected_after_ids
            or [str(record.get("id")) for record in after_records]
            != sorted(expected_after_ids)
        ):
            return invalid

        update_times: set[str] = set()
        selected_before_times: list[datetime] = []
        expected_records: list[dict[str, Any]] = []
        archived_set = set(archived_ids)
        for identifier, before_record in before_by_id.items():
            after_record = after_by_id.get(identifier)
            if not isinstance(after_record, dict):
                return invalid
            if identifier not in archived_set:
                if after_record != before_record:
                    return invalid
                expected_records.append(deepcopy(before_record))
                continue
            if (
                before_record.get("status") != "active"
                or before_record.get("kind") not in {"research", "historical"}
                or after_record.get("status") != "archived"
                or not valid_date_time(after_record.get("updated_at"))
            ):
                return invalid
            try:
                before_updated = parse_time(str(before_record.get("updated_at")))
                after_updated = parse_time(str(after_record.get("updated_at")))
            except (TypeError, ValueError):
                return invalid
            if after_updated < before_updated or after_updated > plan_created:
                return invalid
            expected_record = deepcopy(before_record)
            expected_record["status"] = "archived"
            expected_record["updated_at"] = after_record["updated_at"]
            if after_record != expected_record:
                return invalid
            update_times.add(str(after_record["updated_at"]))
            selected_before_times.append(before_updated)
            expected_records.append(expected_record)
        if (
            len(archived_set) != len(archived_ids)
            or archived_set - set(before_by_id)
            or len(update_times) != 1
        ):
            return invalid

        summary = after_by_id.get(summary_id)
        if (
            not isinstance(summary, dict)
            or summary.get("status") != "active"
            or summary.get("tier") != "cold"
            or summary.get("kind") not in {"research", "historical"}
            or summary.get("supersedes") != archived_ids
            or not valid_date_time(summary.get("created_at"))
            or summary.get("created_at") != summary.get("updated_at")
            or self.validate_record(summary, "cold", project_id)
        ):
            return invalid
        try:
            summary_created = parse_time(str(summary["created_at"]))
            archived_at = parse_time(next(iter(update_times)))
        except (KeyError, TypeError, ValueError):
            return invalid
        if (
            not selected_before_times
            or max(selected_before_times) > summary_created
            or summary_created > archived_at
            or archived_at > plan_created
        ):
            return invalid
        expected_records.append(deepcopy(summary))
        expected_cold = deepcopy(cold_before)
        expected_cold["records"] = sorted(
            expected_records,
            key=lambda record: str(record.get("id", "")),
        )
        if cold_after != expected_cold or cold_after_bytes != json_bytes(expected_cold):
            return invalid

        baseline = self.validate_manifest(
            manifest_before,
            verify_hashes=True,
            verify_evidence=False,
        )
        if baseline["errors"] or baseline["stale"] or baseline["conflicts"]:
            return invalid
        if (
            not isinstance(manifest_before, dict)
            or not isinstance(manifest_after, dict)
            or not valid_date_time(manifest_before.get("refreshed_at"))
            or not valid_date_time(manifest_after.get("refreshed_at"))
        ):
            return invalid
        try:
            before_refreshed = parse_time(str(manifest_before["refreshed_at"]))
            after_refreshed = parse_time(str(manifest_after["refreshed_at"]))
        except (KeyError, TypeError, ValueError):
            return invalid
        if not before_refreshed <= archived_at <= after_refreshed <= plan_created:
            return invalid

        store_bytes_before = {
            HOT_REL: current_hot_bytes,
            WARM_REL: current_warm_bytes,
            COLD_REL: cold_before_bytes,
        }
        expected_manifest_before = self.render_manifest(
            project_id,
            store_bytes_before,
            current_task_bytes,
            manifest_before,
        )
        expected_manifest_before["refreshed_at"] = manifest_before["refreshed_at"]
        expected_manifest_before["refreshed_commit"] = manifest_before.get("refreshed_commit")
        if (
            manifest_before != expected_manifest_before
            or manifest_before_bytes != json_bytes(expected_manifest_before)
        ):
            return invalid

        store_bytes_after = {
            HOT_REL: current_hot_bytes,
            WARM_REL: current_warm_bytes,
            COLD_REL: cold_after_bytes,
        }
        expected_manifest_after = self.render_manifest(
            project_id,
            store_bytes_after,
            current_task_bytes,
            manifest_before,
        )
        expected_manifest_after["refreshed_at"] = manifest_after["refreshed_at"]
        expected_manifest_after["refreshed_commit"] = plan.get("git_head")
        if (
            manifest_after != expected_manifest_after
            or manifest_after_bytes != json_bytes(expected_manifest_after)
        ):
            return invalid

        maximum = manifest_after.get("budgets", {}).get("projection_max_bytes")
        if type(maximum) is not int:
            return invalid
        try:
            expected_projection = self.render_projection(
                project_id,
                {"hot": hot, "warm": warm, "cold": cold_after},
                tasks,
                maximum,
            )
        except (TypeError, ValueError):
            return invalid
        if current_projection_bytes != expected_projection:
            return invalid
        return []

    def validate_projection_repair_transition(
        self,
        changes: dict[str, tuple[bytes | None, bytes | None]],
    ) -> list[str]:
        invalid = ["CONTEXT_PROJECTION_REPAIR_INVALID"]
        if set(changes) != {PROJECTION_REL}:
            return invalid
        _, projection_after = changes[PROJECTION_REL]
        if projection_after is None:
            return invalid

        manifest = self.document(MANIFEST_REL, {})
        validation = self.validate_manifest(
            manifest,
            verify_hashes=True,
            verify_evidence=False,
        )
        repairable_codes = {
            "CONTEXT_PROJECTION_MISSING_OR_UNSAFE",
            "CONTEXT_PROJECTION_NON_CANONICAL",
        }
        errors = validation.get("errors", [])
        if (
            not errors
            or any(error.get("code") not in repairable_codes for error in errors)
            or validation.get("conflicts")
            or validation.get("stale")
        ):
            return invalid
        stores = validation.get("stores")
        tasks = validation.get("tasks")
        budgets = manifest.get("budgets") if isinstance(manifest, dict) else None
        if (
            not isinstance(stores, dict)
            or not isinstance(tasks, dict)
            or not isinstance(budgets, dict)
            or type(budgets.get("projection_max_bytes")) is not int
            or not all(
                isinstance(stores.get(relative), dict)
                for relative in (HOT_REL, WARM_REL, COLD_REL)
            )
        ):
            return invalid
        try:
            expected_projection = self.render_projection(
                str(self.binding().get("project_id", "")),
                {
                    "hot": stores[HOT_REL],
                    "warm": stores[WARM_REL],
                    "cold": stores[COLD_REL],
                },
                tasks,
                budgets["projection_max_bytes"],
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return invalid
        return [] if projection_after == expected_projection else invalid

    def validate_plan(self, plan: Any, plan_id: str) -> list[str]:
        if not isinstance(plan, dict) or set(plan) != PLAN_FIELDS:
            return ["CONTEXT_PLAN_FIELDS_INVALID"]
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
            return ["CONTEXT_PLAN_INVALID"]
        if (
            plan.get("schema_version") != 1
            or plan.get("plan_id") != plan_id
            or PLAN_ID.fullmatch(plan_id) is None
            or expected_plan_id != plan_id
            or plan.get("status") != "pending-approval"
            or plan.get("operation") not in PLAN_OPERATIONS
            or not valid_date_time(plan.get("created_at"))
            or not valid_date_time(plan.get("expires_at"))
            or expires_at <= created_at
            or not 60 <= (expires_at - created_at).total_seconds() <= 3600
            or not isinstance(plan.get("git_head"), str)
            or FULL_COMMIT.fullmatch(plan["git_head"]) is None
            or not self.valid_hash(plan.get("core_manifest_sha256"))
            or plan.get("project_id") != self.binding().get("project_id")
            or plan.get("commit_created") is not False
            or plan.get("push_performed") is not False
            or plan.get("content_sha256") != receipt_hash(plan)
        ):
            return ["CONTEXT_PLAN_INVALID"]
        changes = plan.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 7:
            return ["CONTEXT_PLAN_CHANGES_INVALID"]
        change_paths: list[str] = []
        decoded_changes: dict[str, tuple[bytes | None, bytes | None]] = {}
        for change in changes:
            if not isinstance(change, dict) or set(change) != PLAN_CHANGE_FIELDS:
                return ["CONTEXT_PLAN_CHANGES_INVALID"]
            relative = change.get("path")
            if (
                not isinstance(relative, str)
                or relative in change_paths
                or not self.writable(relative)
            ):
                return ["CONTEXT_PLAN_CHANGES_INVALID"]
            try:
                path = self.path(relative)
                before = decoded(change.get("before_base64"))
                after = decoded(change.get("after_base64"))
            except (TypeError, ValueError):
                return ["CONTEXT_PLAN_CHANGES_INVALID"]
            if (
                path.is_symlink()
                or not self.valid_hash(change.get("before_sha256"), nullable=True)
                or not self.valid_hash(change.get("after_sha256"), nullable=True)
                or (before is None) != (change.get("before_sha256") is None)
                or (after is None) != (change.get("after_sha256") is None)
                or (sha256_bytes(before) if before is not None else None)
                != change.get("before_sha256")
                or (sha256_bytes(after) if after is not None else None)
                != change.get("after_sha256")
                or (after is None and plan.get("operation") != "rollback-task-ledger")
                or before == after
            ):
                return ["CONTEXT_PLAN_CHANGES_INVALID"]
            change_paths.append(relative)
            decoded_changes[relative] = (before, after)
        if change_paths != sorted(change_paths):
            return ["CONTEXT_PLAN_CHANGES_INVALID"]
        try:
            expected_diff = self.render_exact_diff(changes)
        except (TypeError, ValueError):
            return ["CONTEXT_PLAN_CHANGES_INVALID"]
        if plan.get("exact_diff") != expected_diff:
            return ["CONTEXT_PLAN_INVALID"]
        metadata_errors = self.validate_plan_metadata(
            str(plan["operation"]),
            plan.get("metadata"),
            set(change_paths),
        )
        if metadata_errors:
            return metadata_errors
        if plan["operation"] == "compact":
            return self.validate_compaction_transition(plan, decoded_changes)
        if plan["operation"] == "repair-projection":
            return self.validate_projection_repair_transition(decoded_changes)
        return []

    def refreshed_stores(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        stores = deepcopy(self.current_stores())
        errors: list[dict[str, Any]] = []
        for store in stores.values():
            for record in store.get("records", []):
                changed = False
                for ref in record.get("source_refs", []):
                    refreshed, ref_errors = self.committed_evidence_ref(str(ref.get("path", "")))
                    errors.extend({**item, "id": record.get("id")} for item in ref_errors)
                    if refreshed is None:
                        continue
                    if ref != refreshed:
                        ref.clear()
                        ref.update(refreshed)
                        changed = True
                if changed:
                    record["updated_at"] = iso_time(self.now())
        return stores, errors

    def create_plan(self, operation: str, desired: dict[str, bytes | None], metadata: dict[str, Any] | None = None, expiry_seconds: int = 900) -> dict[str, Any]:
        head = self.head()
        if not head:
            return {"ok": False, "reason_codes": ["GIT_HEAD_UNAVAILABLE"]}
        if operation not in PLAN_OPERATIONS:
            return {"ok": False, "reason_codes": ["PLAN_OPERATION_INVALID"]}
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["PLAN_EXPIRY_INVALID"]}
        for relative in desired:
            if not self.writable(relative):
                return {"ok": False, "reason_codes": ["MEMORY_WRITE_OUTSIDE_APPLICATION_SCOPE"], "path": relative}
        changes: list[dict[str, Any]] = []
        for relative in sorted(desired):
            before = self.read_bytes(relative)
            after = desired[relative]
            if before == after:
                continue
            changes.append({
                "path": relative,
                "before_sha256": sha256_bytes(before) if before is not None else None,
                "after_sha256": sha256_bytes(after) if after is not None else None,
                "before_base64": encoded(before),
                "after_base64": encoded(after),
            })
        if not changes:
            return {"ok": False, "reason_codes": ["NO_CHANGES"]}
        created = self.now()
        plan = {
            "schema_version": 1,
            "plan_id": "",
            "status": "pending-approval",
            "operation": operation,
            "created_at": iso_time(created),
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "git_head": head,
            "core_manifest_sha256": sha256_bytes(self.read_bytes(CORE_MANIFEST_REL) or b""),
            "project_id": self.binding().get("project_id"),
            "changes": changes,
            "exact_diff": self.render_exact_diff(changes),
            "metadata": metadata or {},
            "commit_created": False,
            "push_performed": False,
        }
        plan["plan_id"] = canonical_hash({key: value for key, value in plan.items() if key not in {"plan_id", "content_sha256"}})[:24]
        plan["content_sha256"] = receipt_hash(plan)
        self.plans.mkdir(parents=True, exist_ok=True)
        atomic_bytes(self.plans / f"{plan['plan_id']}.json", json_bytes(plan))
        return {"ok": True, "plan": plan}

    def plan_initialize(self) -> dict[str, Any]:
        if self.path(MANIFEST_REL).exists():
            return {"ok": False, "reason_codes": ["CONTEXT_ALREADY_CONFIGURED"]}
        project_id = self.binding().get("project_id")
        if not isinstance(project_id, str) or not project_id:
            return {"ok": False, "reason_codes": ["PROJECT_BINDING_REQUIRED"]}
        defaults = self.default_stores(project_id)
        stores = {tier: defaults[path] for tier, path in (("hot", HOT_REL), ("warm", WARM_REL), ("cold", COLD_REL))}
        desired = self.desired_with_manifest(stores, defaults[TASKS_REL])
        return self.create_plan("initialize", desired, {"project_id": project_id})

    def plan_refresh(self) -> dict[str, Any]:
        manifest = self.document(MANIFEST_REL, {})
        validation = self.validate_manifest(manifest, verify_hashes=False, verify_evidence=False)
        repairable_projection_codes = {
            "CONTEXT_PROJECTION_MISSING_OR_UNSAFE",
            "CONTEXT_PROJECTION_NON_CANONICAL",
        }
        projection_errors = [
            error
            for error in validation["errors"]
            if error.get("code") in repairable_projection_codes
        ]
        blocking_errors = [
            error
            for error in validation["errors"]
            if error.get("code") not in repairable_projection_codes
        ]
        strict_validation = self.validate_manifest(
            manifest,
            verify_hashes=True,
            verify_evidence=False,
        )
        strict_blocking_errors = [
            error
            for error in strict_validation["errors"]
            if error.get("code") not in repairable_projection_codes
        ]
        if (
            projection_errors
            and not blocking_errors
            and not validation["conflicts"]
            and not strict_blocking_errors
            and not strict_validation["conflicts"]
            and not strict_validation["stale"]
        ):
            if self.path(PROJECTION_REL).is_symlink():
                return {
                    "ok": False,
                    "reason_codes": ["CONTEXT_REFRESH_BLOCKED"],
                    "errors": validation["errors"],
                    "conflicts": validation["conflicts"],
                }
            budgets = manifest.get("budgets") if isinstance(manifest, dict) else None
            if not isinstance(budgets, dict) or type(budgets.get("projection_max_bytes")) is not int:
                return {
                    "ok": False,
                    "reason_codes": ["CONTEXT_REFRESH_BLOCKED"],
                    "errors": validation["errors"],
                    "conflicts": validation["conflicts"],
                }
            try:
                projection = self.render_projection(
                    str(self.binding().get("project_id", "")),
                    self.current_stores(),
                    self.document(TASKS_REL, {}),
                    budgets["projection_max_bytes"],
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                return {
                    "ok": False,
                    "reason_codes": ["CONTEXT_REFRESH_BLOCKED"],
                    "errors": validation["errors"],
                    "conflicts": validation["conflicts"],
                }
            return self.create_plan(
                "repair-projection",
                {PROJECTION_REL: projection},
                {"repair": "canonical-projection"},
            )
        if blocking_errors or validation["conflicts"]:
            return {"ok": False, "reason_codes": ["CONTEXT_REFRESH_BLOCKED"], "errors": validation["errors"], "conflicts": validation["conflicts"]}
        stores, refresh_errors = self.refreshed_stores()
        if refresh_errors:
            return {"ok": False, "reason_codes": ["CONTEXT_REFRESH_EVIDENCE_INVALID"], "errors": refresh_errors}
        desired = self.desired_with_manifest(stores, self.document(TASKS_REL, {}), manifest)
        return self.create_plan("refresh", desired, {"previous_refreshed_commit": manifest.get("refreshed_commit")})

    def plan_upsert(self, proposal: Any) -> dict[str, Any]:
        health = self.doctor()
        if health.get("state") in {"UNCONFIGURED", "DEGRADED"}:
            return {"ok": False, "reason_codes": ["CONTEXT_NOT_MUTABLE"], "health": health}
        project_id = str(self.binding().get("project_id", ""))
        stores = self.current_stores()
        tier = str(proposal.get("tier", "")) if isinstance(proposal, dict) else ""
        existing = next((item for item in stores.get(tier, {}).get("records", []) if item.get("id") == proposal.get("id")), None) if isinstance(proposal, dict) else None
        record, errors = self.build_record(proposal, project_id, existing)
        if errors or record is None:
            return {"ok": False, "reason_codes": ["CONTEXT_PROPOSAL_INVALID"], "errors": errors}
        by_id = {item.get("id"): item for item in stores[tier].get("records", []) if isinstance(item, dict)}
        by_id[record["id"]] = record
        stores[tier]["records"] = [by_id[key] for key in sorted(by_id)]
        desired = self.desired_with_manifest(stores, self.document(TASKS_REL, {}), self.document(MANIFEST_REL, {}))
        return self.create_plan("upsert-record", desired, {"record_id": record["id"], "tier": tier})

    def plan_claim_task(self, proposal: Any) -> dict[str, Any]:
        return task_ledger.plan_claim_task(self, proposal)

    def plan_continue_task(self, proposal: Any) -> dict[str, Any]:
        return task_ledger.plan_continue_task(self, proposal)

    def plan_rekey_task(self, proposal: Any) -> dict[str, Any]:
        return task_ledger.plan_rekey_task(self, proposal)

    def plan_handoff(self, proposal: Any) -> dict[str, Any]:
        return task_ledger.plan_handoff(self, proposal)

    def plan_migrate_task_ledger(self) -> dict[str, Any]:
        return task_ledger.plan_migrate(self)

    def plan_rollback_task_ledger(self, source_plan_id: str) -> dict[str, Any]:
        return task_ledger.plan_rollback(self, source_plan_id)

    def plan_compact(self, proposal: Any) -> dict[str, Any]:
        allowed = {"record_ids", "summary"}
        if not isinstance(proposal, dict) or set(proposal) != allowed or not isinstance(proposal.get("record_ids"), list):
            return {"ok": False, "reason_codes": ["COMPACTION_PROPOSAL_INVALID"]}
        record_ids = proposal["record_ids"]
        if (
            not record_ids
            or not all(
                isinstance(item, str) and SAFE_ID.fullmatch(item) is not None
                for item in record_ids
            )
            or len(record_ids) != len(set(record_ids))
        ):
            return {"ok": False, "reason_codes": ["COMPACTION_PROPOSAL_INVALID"]}
        record_ids = sorted(record_ids)
        stores = self.current_stores()
        cold = stores.get("cold", {}).get("records", [])
        originals = [item for item in cold if item.get("id") in record_ids and item.get("status") == "active"]
        if len(originals) != len(record_ids) or any(item.get("kind") not in {"research", "historical"} for item in originals):
            return {"ok": False, "reason_codes": ["COMPACTION_ONLY_ACTIVE_COLD_HISTORY_OR_RESEARCH"]}
        summary_proposal = deepcopy(proposal.get("summary"))
        if not isinstance(summary_proposal, dict):
            return {"ok": False, "reason_codes": ["COMPACTION_SUMMARY_INVALID"]}
        summary_proposal["tier"] = "cold"
        summary_proposal["supersedes"] = sorted(set(record_ids))
        summary, errors = self.build_record(summary_proposal, str(self.binding().get("project_id", "")))
        cold_ids = {
            item.get("id")
            for item in cold
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if (
            errors
            or summary is None
            or summary.get("kind") not in {"research", "historical"}
            or summary.get("id") in cold_ids
        ):
            return {"ok": False, "reason_codes": ["COMPACTION_SUMMARY_INVALID"], "errors": errors}
        timestamp = iso_time(self.now())
        updated = []
        for record in cold:
            item = deepcopy(record)
            if item.get("id") in record_ids:
                item["status"] = "archived"
                item["updated_at"] = timestamp
            updated.append(item)
        updated.append(summary)
        stores["cold"]["records"] = sorted(updated, key=lambda item: item.get("id", ""))
        desired = self.desired_with_manifest(stores, self.document(TASKS_REL, {}), self.document(MANIFEST_REL, {}))
        return self.create_plan("compact", desired, {"archived_record_ids": sorted(record_ids), "summary_id": summary["id"], "records_deleted": 0})

    def acquire_lock(self) -> TransactionLockHandle:
        self.runtime.mkdir(parents=True, exist_ok=True)
        return acquire_transaction_lock(self.lock_path, "context-memory-apply")

    def release_lock(self, handle: TransactionLockHandle) -> None:
        release_transaction_lock(handle)

    def verify_changes(self, changes: list[dict[str, Any]], after: bool) -> bool:
        field = "after_sha256" if after else "before_sha256"
        for change in changes:
            content = self.read_bytes(str(change.get("path")))
            actual = sha256_bytes(content) if content is not None else None
            if actual != change.get(field):
                return False
        return True

    def restore(self, changes: list[dict[str, Any]]) -> bool:
        ok = True
        for change in reversed(changes):
            path = self.path(str(change["path"]))
            content = decoded(change.get("before_base64"))
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, content)
            except OSError:
                ok = False
        return ok

    def apply(
        self,
        plan_id: str,
        confirm: bool,
        test_fail_after: int = 0,
        test_fail_after_receipt: bool = False,
        test_fail_receipt_cleanup: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        if not PLAN_ID.fullmatch(plan_id or ""):
            return {"ok": False, "reason_codes": ["PLAN_ID_INVALID"]}
        try:
            lock = self.acquire_lock()
        except TransactionLockError as error:
            reason_codes = [error.reason_code]
            if error.reason_code == "TRANSACTION_LOCK_BUSY":
                reason_codes.insert(0, "TRANSACTION_BUSY")
            return {"ok": False, "reason_codes": reason_codes}
        try:
            plan_path = self.plans / f"{plan_id}.json"
            plan = load_json(plan_path, None)
            if not isinstance(plan, dict) or plan.get("plan_id") != plan_id or plan.get("content_sha256") != receipt_hash(plan):
                return {"ok": False, "reason_codes": ["PLAN_NOT_FOUND_OR_TAMPERED"]}
            if plan.get("status") != "pending-approval":
                return {"ok": False, "reason_codes": ["PLAN_NOT_PENDING"]}
            validation_errors = self.validate_plan(plan, plan_id)
            if validation_errors:
                return {
                    "ok": False,
                    "reason_codes": ["PLAN_NOT_FOUND_OR_TAMPERED"],
                    "validation_errors": validation_errors,
                }
            if self.now() > parse_time(plan["expires_at"]):
                return {"ok": False, "reason_codes": ["PLAN_EXPIRED"]}
            if self.head() != plan.get("git_head"):
                return {"ok": False, "reason_codes": ["STALE_GIT_HEAD"]}
            if sha256_bytes(self.read_bytes(CORE_MANIFEST_REL) or b"") != plan.get("core_manifest_sha256"):
                return {"ok": False, "reason_codes": ["CORE_RELEASE_CHANGED"]}
            if plan.get("project_id") != self.binding().get("project_id"):
                return {"ok": False, "reason_codes": ["PROJECT_BINDING_CHANGED"]}
            changes = plan.get("changes") if isinstance(plan.get("changes"), list) else []
            if not changes or not self.verify_changes(changes, after=False):
                return {"ok": False, "reason_codes": ["STALE_TARGET_HASH"]}
            ordered = sorted(changes, key=lambda item: item.get("path") == MANIFEST_REL)
            receipt_path: Path | None = None
            receipt_written = False
            try:
                for index, change in enumerate(ordered, start=1):
                    path = self.path(str(change["path"]))
                    content = decoded(change.get("after_base64"))
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_bytes(path, content)
                    if test_fail_after == index and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                        raise RuntimeError(f"injected memory failure after write {index}")
                if not self.verify_changes(changes, after=True):
                    raise RuntimeError("post-apply byte verification failed")
                health = self.doctor()
                if health.get("state") not in {"FRESH", "STALE"}:
                    raise RuntimeError("post-apply memory doctor failed")
                receipt = {
                    "schema_version": 1,
                    "transaction_id": canonical_hash({"plan": plan_id, "at": iso_time(self.now()), "nonce": os.urandom(16).hex()})[:24],
                    "plan_id": plan_id,
                    "operation": plan.get("operation"),
                    "status": "applied",
                    "applied_at": iso_time(self.now()),
                    "changes": [{"path": item["path"], "before_sha256": item["before_sha256"], "after_sha256": item["after_sha256"]} for item in changes],
                    "project_id": plan.get("project_id"),
                    "commit_created": False,
                    "push_performed": False,
                }
                if plan.get("operation") in {"migrate-task-ledger", "rollback-task-ledger"}:
                    receipt["transition"] = plan.get("metadata")
                receipt["content_sha256"] = receipt_hash(receipt)
                self.receipts.mkdir(parents=True, exist_ok=True)
                receipt_path = self.receipts / f"{receipt['transaction_id']}.json"
                atomic_bytes(receipt_path, json_bytes(receipt))
                receipt_written = True
                if test_fail_after_receipt and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                    raise RuntimeError("injected memory failure after receipt write")
                plan["status"] = "applied"
                plan["content_sha256"] = receipt_hash(plan)
                atomic_bytes(plan_path, json_bytes(plan))
                return {"ok": True, "receipt": receipt, "health": health}
            except Exception as exc:  # noqa: BLE001 - rollback is the transaction boundary
                receipt_removed = True
                if receipt_written and receipt_path is not None:
                    try:
                        if (
                            test_fail_receipt_cleanup
                            and os.environ.get("AGENT_OS_TEST_MODE") == "1"
                        ):
                            raise OSError("injected receipt cleanup failure")
                        receipt_path.unlink(missing_ok=True)
                        receipt_removed = not receipt_path.exists()
                    except OSError:
                        receipt_removed = False
                restored = self.restore(changes)
                rollback_verified = (
                    receipt_removed
                    and restored
                    and self.verify_changes(changes, after=False)
                )
                plan["status"] = "failed"
                plan["content_sha256"] = receipt_hash(plan)
                atomic_bytes(plan_path, json_bytes(plan))
                return {
                    "ok": False,
                    "reason_codes": [
                        (
                            "MEMORY_APPLY_FAILED_ROLLED_BACK"
                            if rollback_verified
                            else "MEMORY_APPLY_ROLLBACK_INCOMPLETE"
                        )
                    ],
                    "error": str(exc),
                    "rollback_verified": rollback_verified,
                }
        finally:
            self.release_lock(lock)

    def list_tasks(self) -> dict[str, Any]:
        return task_ledger.list_tasks(self)

    def list_handoffs(self) -> dict[str, Any]:
        validation = self.validate_handoffs()
        return {
            "ok": not validation["errors"],
            "handoffs": validation["valid_receipts"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
            "durability": validation["summary"],
        }


def read_input(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS Context Memory engine")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    load = commands.add_parser("load")
    load.add_argument("--tier", choices=sorted(TIERS), default="hot")
    commands.add_parser("plan-initialize")
    commands.add_parser("plan-refresh")
    propose = commands.add_parser("plan-propose")
    propose.add_argument("--input", required=True)
    claim = commands.add_parser("plan-claim")
    claim.add_argument("--input", required=True)
    continuation = commands.add_parser("plan-continue")
    continuation.add_argument("--input", required=True)
    rekey = commands.add_parser("plan-rekey-task")
    rekey.add_argument("--input", required=True)
    handoff = commands.add_parser("plan-handoff")
    handoff.add_argument("--input", required=True)
    compact = commands.add_parser("plan-compact")
    compact.add_argument("--input", required=True)
    commands.add_parser("plan-migrate-task-ledger")
    rollback = commands.add_parser("plan-rollback-task-ledger")
    rollback.add_argument("--plan", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm", action="store_true")
    commands.add_parser("tasks")
    commands.add_parser("handoffs")
    args = parser.parse_args()
    service = ContextMemoryService()
    try:
        if args.command == "doctor":
            result = service.doctor()
        elif args.command == "load":
            result = service.load(args.tier)
        elif args.command == "plan-initialize":
            result = service.plan_initialize()
        elif args.command == "plan-refresh":
            result = service.plan_refresh()
        elif args.command == "plan-propose":
            result = service.plan_upsert(read_input(args.input))
        elif args.command == "plan-claim":
            result = service.plan_claim_task(read_input(args.input))
        elif args.command == "plan-continue":
            result = service.plan_continue_task(read_input(args.input))
        elif args.command == "plan-rekey-task":
            result = service.plan_rekey_task(read_input(args.input))
        elif args.command == "plan-handoff":
            result = service.plan_handoff(read_input(args.input))
        elif args.command == "plan-compact":
            result = service.plan_compact(read_input(args.input))
        elif args.command == "plan-migrate-task-ledger":
            result = service.plan_migrate_task_ledger()
        elif args.command == "plan-rollback-task-ledger":
            result = service.plan_rollback_task_ledger(args.plan)
        elif args.command == "apply":
            result = service.apply(args.plan, args.confirm)
        elif args.command == "tasks":
            result = service.list_tasks()
        else:
            result = service.list_handoffs()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"ok": False, "reason_codes": ["CONTEXT_MEMORY_INPUT_OR_IO_INVALID"], "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
