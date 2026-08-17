#!/usr/bin/env python3
"""Dependency-free, read-only AOS-15 continuity catalog lifecycle doctor."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_os_context_memory import ContextMemoryService
from agent_os_genesis import doctor as genesis_doctor
from agent_os_lifecycle import verify_release_tree
from agent_os_paths import portable_relative

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
CATALOG_REL = "project/context/continuity.json"
CORE_REGISTRY_REL = "memory/continuity-record-types.json"
PROFILE_REGISTRY_REL = "memory/continuity-recovery-profiles.json"
BINDING_REL = "project/project-binding.json"
PROJECTION_REL = "project/context/continuity-projection.json"

CATALOG_FIELDS = {
    "schema_version",
    "project_id",
    "catalog_id",
    "catalog_revision",
    "record_type_registry",
    "recovery_profile",
    "references",
    "created_at",
    "updated_at",
}
CATALOG_OPTIONAL_FIELDS = {"project_record_type_registry", "migration_extensions"}
MIGRATION_EXTENSION_FIELDS = {
    "source_generation",
    "migration_id",
    "unknown_fields_sha256",
    "fields",
}
REGISTRY_REFERENCE_FIELDS = {"registry_id", "registry_version", "registry_sha256"}
PROJECT_REGISTRY_REFERENCE_FIELDS = {"path", *REGISTRY_REFERENCE_FIELDS}
PROFILE_REFERENCE_FIELDS = {"profile_id", "profile_version", "profile_sha256"}
REFERENCE_FIELDS = {
    "reference_id",
    "record_type",
    "profile_role",
    "record_id",
    "record_revision",
    "requirement",
    "lifecycle",
    "load_policy",
    "authority_provider",
    "source",
    "dependencies",
    "supersedes",
    "retention_class",
    "privacy_class",
    "created_at",
    "updated_at",
}
SOURCE_FIELDS = {"path", "sha256", "git_commit", "schema_id", "schema_version"}
DEPENDENCY_FIELDS = {"relation", "target_reference_id"}
REGISTRY_FIELDS = {"schema_version", "registry_id", "registry_version", "types"}
TYPE_FIELDS = {
    "record_type",
    "canonical_owner",
    "authority_provider",
    "supported_schemas",
    "identity_rule",
    "revision_rule",
    "revision_types",
    "allowed_requirements",
    "allowed_load_policies",
    "allowed_dependency_relations",
    "allowed_retention_classes",
    "missing_state_allowed",
    "validator_provider",
    "migration_provider",
    "payload_in_catalog",
    "raw_conversation_allowed",
    "extension_namespace",
}
SUPPORTED_SCHEMA_FIELDS = {"schema_id", "versions"}
PROFILE_REGISTRY_FIELDS = {"schema_version", "profiles"}
PROFILE_FIELDS = {
    "profile_id",
    "profile_version",
    "catalog_max_bytes",
    "projection_max_bytes",
    "roles",
}
ROLE_FIELDS = {
    "profile_role",
    "record_type",
    "minimum",
    "maximum",
    "requirement",
    "load_policy",
    "activation",
}

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
GIT_COMMIT = re.compile(r"^[a-f0-9]{40}$")
DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
EXTENSION_KEY = re.compile(r"^[a-z][a-z0-9._-]{1,127}$")
SECRET = re.compile(
    r"(?:BEGIN [A-Z ]*PRIVATE KEY|(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=])",
    re.IGNORECASE,
)

REQUIREMENTS = {"required", "state-aware", "advisory"}
LIFECYCLES = {"active", "superseded", "archived"}
LOAD_POLICIES = {"boot", "just-in-time", "explicit-only"}
DEPENDENCY_RELATIONS = {"requires", "generated-from", "evidence-for", "verified-by", "hands-off"}
RETENTION_CLASSES = {"critical-active", "critical-history", "operational", "evidence", "advisory"}
PRIVACY_CLASSES = {"public-metadata", "project-internal", "sensitive-reference"}
REVISION_TYPES = {"integer", "string", "null"}
ACTIVATIONS = {"always", "typed-active-phase", "typed-current-transition", "terminal-handoff"}
FORBIDDEN_KEYS = {
    "payload",
    "value",
    "content",
    "raw_conversation",
    "conversation",
    "prompt",
    "transcript",
    "chain_of_thought",
    "reasoning",
    "scratchpad",
}

MAX_JSON_BYTES = 1024 * 1024
MAX_REFERENCES = 1024
MAX_LIST_ITEMS = 128
MAX_MIGRATION_EXTENSIONS = 8
MAX_MIGRATION_FIELDS = 32
MAX_MIGRATION_STRING = 4096
MAX_MIGRATION_NUMBER = 1_000_000_000_000


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def optional_sha256_file(path: Path) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON document exceeds the read boundary")
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_json_constant,
    )


def valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or DATE_TIME.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is int:
        return "integer"
    if isinstance(value, str):
        return "string"
    return "invalid"


def bounded_string_list(value: Any, allowed: set[str] | None = None) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= MAX_LIST_ITEMS
        and all(isinstance(item, str) and 1 <= len(item) <= 128 for item in value)
        and len(value) == len(set(value))
        and (allowed is None or set(value) <= allowed)
    )


def forbidden_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_KEYS or forbidden_payload(item):
                return True
        return False
    if isinstance(value, list):
        return any(forbidden_payload(item) for item in value)
    return isinstance(value, str) and SECRET.search(value) is not None


def valid_migration_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= MAX_MIGRATION_STRING
    if type(value) in {int, float}:
        return -MAX_MIGRATION_NUMBER <= value <= MAX_MIGRATION_NUMBER
    return False


def valid_migration_value(value: Any) -> bool:
    if valid_migration_scalar(value):
        return True
    if isinstance(value, list):
        return len(value) <= MAX_MIGRATION_FIELDS and all(
            valid_migration_scalar(item) for item in value
        )
    if isinstance(value, dict):
        return (
            len(value) <= MAX_MIGRATION_FIELDS
            and all(
                isinstance(key, str) and EXTENSION_KEY.fullmatch(key) is not None
                for key in value
            )
            and all(valid_migration_scalar(item) for item in value.values())
        )
    return False


def validate_migration_extensions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_MIGRATION_EXTENSIONS:
        return [issue("CONTINUITY_MIGRATION_EXTENSIONS_INVALID")]
    errors: list[dict[str, Any]] = []
    canonical_entries: set[bytes] = set()
    for index, extension in enumerate(value):
        if not isinstance(extension, dict) or set(extension) != MIGRATION_EXTENSION_FIELDS:
            errors.append(issue("CONTINUITY_MIGRATION_EXTENSION_INVALID", index=index))
            continue
        source_generation = extension.get("source_generation")
        migration_id = extension.get("migration_id")
        evidence_hash = extension.get("unknown_fields_sha256")
        fields = extension.get("fields")
        if (
            type(source_generation) is not int
            or not 0 <= source_generation <= 1
            or not isinstance(migration_id, str)
            or SAFE_ID.fullmatch(migration_id) is None
            or not isinstance(evidence_hash, str)
            or SHA256.fullmatch(evidence_hash) is None
            or not isinstance(fields, dict)
            or len(fields) > MAX_MIGRATION_FIELDS
            or any(
                not isinstance(key, str) or EXTENSION_KEY.fullmatch(key) is None
                for key in fields
            )
            or any(not valid_migration_value(item) for item in fields.values())
        ):
            errors.append(issue("CONTINUITY_MIGRATION_EXTENSION_INVALID", index=index))
            continue
        if sha256_bytes(canonical_json_bytes(fields)) != evidence_hash:
            errors.append(
                issue("CONTINUITY_MIGRATION_EXTENSION_HASH_MISMATCH", index=index)
            )
        canonical_entry = canonical_json_bytes(extension)
        if canonical_entry in canonical_entries:
            errors.append(issue("CONTINUITY_MIGRATION_EXTENSION_DUPLICATE", index=index))
        canonical_entries.add(canonical_entry)
    return errors


def issue(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


def run_git(project_root: Path, *arguments: str, text: bool = False) -> subprocess.CompletedProcess[Any] | None:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            capture_output=True,
            text=text,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_blob(project_root: Path, commit: str, relative: str) -> bytes | None:
    result = run_git(project_root, "cat-file", "blob", f"{commit}:{relative}")
    return result.stdout if result is not None and result.returncode == 0 else None


def git_commit_exists(project_root: Path, commit: str) -> bool:
    result = run_git(project_root, "cat-file", "-e", f"{commit}^{{commit}}")
    return result is not None and result.returncode == 0


def git_commit_is_ancestor(project_root: Path, commit: str) -> bool:
    result = run_git(project_root, "merge-base", "--is-ancestor", commit, "HEAD")
    return result is not None and result.returncode == 0


def git_head(project_root: Path) -> str | None:
    result = run_git(project_root, "rev-parse", "HEAD", text=True)
    value = result.stdout.strip() if result is not None and result.returncode == 0 else ""
    return value if GIT_COMMIT.fullmatch(value) else None


def git_path_clean(project_root: Path, relative: str) -> bool:
    for arguments in (
        ("diff", "--quiet", "--no-ext-diff", "--", relative),
        ("diff", "--cached", "--quiet", "--no-ext-diff", "--", relative),
    ):
        result = run_git(project_root, *arguments)
        if result is None or result.returncode != 0:
            return False
    return True


def source_path(project_root: Path, value: Any) -> tuple[Path | None, list[dict[str, Any]]]:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return None, [issue("CONTINUITY_SOURCE_PATH_INVALID")]
    try:
        canonical = portable_relative(value, canonical=True)
    except ValueError:
        return None, [issue("CONTINUITY_SOURCE_PATH_UNSAFE", path=value)]
    if canonical != value:
        return None, [issue("CONTINUITY_SOURCE_PATH_NON_CANONICAL", path=value)]
    candidate = project_root / canonical
    current = project_root
    for part in Path(canonical).parts:
        current = current / part
        if current.is_symlink():
            return None, [issue("CONTINUITY_SOURCE_SYMLINK_REJECTED", path=value)]
    try:
        resolved = candidate.resolve()
    except OSError:
        return None, [issue("CONTINUITY_SOURCE_PATH_INVALID", path=value)]
    root = project_root.resolve()
    if resolved != root and root not in resolved.parents:
        return None, [issue("CONTINUITY_SOURCE_PATH_ESCAPE", path=value)]
    return candidate, []


def validate_registry(
    document: Any,
    *,
    project_id: str | None = None,
    extension: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(document, dict) or set(document) != REGISTRY_FIELDS:
        return {}, [issue("CONTINUITY_REGISTRY_FIELDS_INVALID")]
    registry_id = document.get("registry_id")
    version = document.get("registry_version")
    types = document.get("types")
    if document.get("schema_version") != 1:
        errors.append(issue("CONTINUITY_REGISTRY_SCHEMA_UNSUPPORTED"))
    if not isinstance(registry_id, str) or SAFE_ID.fullmatch(registry_id) is None:
        errors.append(issue("CONTINUITY_REGISTRY_ID_INVALID"))
    if type(version) is not int or version < 1:
        errors.append(issue("CONTINUITY_REGISTRY_VERSION_INVALID"))
    if not isinstance(types, list) or not 1 <= len(types) <= 256:
        return {}, [*errors, issue("CONTINUITY_REGISTRY_TYPES_INVALID")]
    by_id: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(types):
        if not isinstance(entry, dict) or set(entry) != TYPE_FIELDS:
            errors.append(issue("CONTINUITY_RECORD_TYPE_FIELDS_INVALID", index=index))
            continue
        record_type = entry.get("record_type")
        if not isinstance(record_type, str) or SAFE_ID.fullmatch(record_type) is None:
            errors.append(issue("CONTINUITY_RECORD_TYPE_ID_INVALID", index=index))
            continue
        if record_type in by_id:
            errors.append(issue("CONTINUITY_RECORD_TYPE_DUPLICATE", record_type=record_type))
            continue
        if extension:
            namespace = f"project.{project_id}."
            if not record_type.startswith(namespace):
                errors.append(issue("CONTINUITY_EXTENSION_NAMESPACE_INVALID", record_type=record_type))
            for field in ("authority_provider", "validator_provider"):
                provider = entry.get(field)
                if not isinstance(provider, str) or not provider.startswith(namespace):
                    errors.append(issue("CONTINUITY_EXTENSION_PROVIDER_INVALID", record_type=record_type, field=field))
            if entry.get("canonical_owner") != "application":
                errors.append(issue("CONTINUITY_EXTENSION_OWNER_INVALID", record_type=record_type))
        elif entry.get("canonical_owner") not in {"core", "application"}:
            errors.append(issue("CONTINUITY_RECORD_TYPE_OWNER_INVALID", record_type=record_type))
        for field in ("authority_provider", "validator_provider", "identity_rule", "revision_rule"):
            if not isinstance(entry.get(field), str) or not 1 <= len(entry[field]) <= 128:
                errors.append(issue("CONTINUITY_RECORD_TYPE_CONTRACT_INVALID", record_type=record_type, field=field))
        schemas = entry.get("supported_schemas")
        if not isinstance(schemas, list) or len(schemas) > 32:
            errors.append(issue("CONTINUITY_RECORD_TYPE_SCHEMAS_INVALID", record_type=record_type))
        else:
            seen_schemas: set[str] = set()
            for schema in schemas:
                if not isinstance(schema, dict) or set(schema) != SUPPORTED_SCHEMA_FIELDS:
                    errors.append(issue("CONTINUITY_RECORD_TYPE_SCHEMAS_INVALID", record_type=record_type))
                    continue
                schema_id = schema.get("schema_id")
                versions = schema.get("versions")
                if (
                    not isinstance(schema_id, str)
                    or SAFE_ID.fullmatch(schema_id) is None
                    or schema_id in seen_schemas
                    or not isinstance(versions, list)
                    or not versions
                    or len(versions) != len(set(versions))
                    or any(type(item) is not int or item < 1 for item in versions)
                ):
                    errors.append(issue("CONTINUITY_RECORD_TYPE_SCHEMAS_INVALID", record_type=record_type))
                else:
                    seen_schemas.add(schema_id)
        if not bounded_string_list(entry.get("revision_types"), REVISION_TYPES):
            errors.append(issue("CONTINUITY_RECORD_TYPE_REVISIONS_INVALID", record_type=record_type))
        list_contracts = (
            ("allowed_requirements", REQUIREMENTS),
            ("allowed_load_policies", LOAD_POLICIES),
            ("allowed_dependency_relations", DEPENDENCY_RELATIONS),
            ("allowed_retention_classes", RETENTION_CLASSES),
        )
        for field, allowed in list_contracts:
            if not bounded_string_list(entry.get(field), allowed):
                errors.append(issue("CONTINUITY_RECORD_TYPE_CONTRACT_INVALID", record_type=record_type, field=field))
        if type(entry.get("missing_state_allowed")) is not bool:
            errors.append(issue("CONTINUITY_RECORD_TYPE_CONTRACT_INVALID", record_type=record_type, field="missing_state_allowed"))
        if entry.get("migration_provider") is not None and not isinstance(entry.get("migration_provider"), str):
            errors.append(issue("CONTINUITY_RECORD_TYPE_CONTRACT_INVALID", record_type=record_type, field="migration_provider"))
        if entry.get("payload_in_catalog") is not False or entry.get("raw_conversation_allowed") is not False:
            errors.append(issue("CONTINUITY_RECORD_TYPE_PAYLOAD_BOUNDARY_INVALID", record_type=record_type))
        namespace_value = entry.get("extension_namespace")
        if namespace_value is not None and not isinstance(namespace_value, str):
            errors.append(issue("CONTINUITY_RECORD_TYPE_CONTRACT_INVALID", record_type=record_type, field="extension_namespace"))
        by_id[record_type] = entry
    return by_id, errors


def validate_profiles(
    document: Any,
    type_registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(document, dict) or set(document) != PROFILE_REGISTRY_FIELDS:
        return {}, [issue("CONTINUITY_PROFILE_REGISTRY_FIELDS_INVALID")]
    if document.get("schema_version") != 1:
        errors.append(issue("CONTINUITY_PROFILE_REGISTRY_SCHEMA_UNSUPPORTED"))
    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 32:
        return {}, [*errors, issue("CONTINUITY_PROFILES_INVALID")]
    by_id: dict[str, dict[str, Any]] = {}
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict) or set(profile) != PROFILE_FIELDS:
            errors.append(issue("CONTINUITY_PROFILE_FIELDS_INVALID", index=index))
            continue
        profile_id = profile.get("profile_id")
        version = profile.get("profile_version")
        key = f"{profile_id}@{version}"
        if (
            not isinstance(profile_id, str)
            or SAFE_ID.fullmatch(profile_id) is None
            or type(version) is not int
            or version < 1
            or key in by_id
        ):
            errors.append(issue("CONTINUITY_PROFILE_ID_INVALID", index=index))
            continue
        for field, minimum, maximum in (
            ("catalog_max_bytes", 4096, MAX_JSON_BYTES),
            ("projection_max_bytes", 512, 65536),
        ):
            value = profile.get(field)
            if type(value) is not int or not minimum <= value <= maximum:
                errors.append(issue("CONTINUITY_PROFILE_BUDGET_INVALID", profile_id=profile_id, field=field))
        roles = profile.get("roles")
        if not isinstance(roles, list) or not 1 <= len(roles) <= 128:
            errors.append(issue("CONTINUITY_PROFILE_ROLES_INVALID", profile_id=profile_id))
            continue
        seen_roles: set[str] = set()
        for role in roles:
            if not isinstance(role, dict) or set(role) != ROLE_FIELDS:
                errors.append(issue("CONTINUITY_PROFILE_ROLE_FIELDS_INVALID", profile_id=profile_id))
                continue
            role_id = role.get("profile_role")
            record_type = role.get("record_type")
            minimum = role.get("minimum")
            maximum = role.get("maximum")
            if (
                not isinstance(role_id, str)
                or SAFE_ID.fullmatch(role_id) is None
                or role_id in seen_roles
            ):
                errors.append(issue("CONTINUITY_PROFILE_ROLE_ID_INVALID", profile_id=profile_id))
                continue
            seen_roles.add(role_id)
            if record_type not in type_registry:
                errors.append(issue("CONTINUITY_PROFILE_RECORD_TYPE_UNKNOWN", profile_role=role_id))
            if (
                type(minimum) is not int
                or type(maximum) is not int
                or minimum < 0
                or maximum < 1
                or minimum > maximum
                or maximum > MAX_REFERENCES
            ):
                errors.append(issue("CONTINUITY_PROFILE_CARDINALITY_INVALID", profile_role=role_id))
            if role.get("requirement") not in REQUIREMENTS:
                errors.append(issue("CONTINUITY_PROFILE_REQUIREMENT_INVALID", profile_role=role_id))
            if role.get("load_policy") not in LOAD_POLICIES:
                errors.append(issue("CONTINUITY_PROFILE_LOAD_POLICY_INVALID", profile_role=role_id))
            if role.get("activation") not in ACTIVATIONS:
                errors.append(issue("CONTINUITY_PROFILE_ACTIVATION_INVALID", profile_role=role_id))
        by_id[key] = profile
    return by_id, errors


def supported_schema(entry: dict[str, Any], schema_id: Any, schema_version: Any) -> tuple[bool, bool]:
    schemas = entry.get("supported_schemas", [])
    if not schemas:
        return schema_id is None and schema_version is None, False
    if not isinstance(schema_id, str) or type(schema_version) is not int:
        return False, False
    matched = next((item for item in schemas if item.get("schema_id") == schema_id), None)
    if matched is None:
        return False, True
    return schema_version in matched.get("versions", []), schema_version not in matched.get("versions", [])


def validate_catalog_shape(document: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(document, dict):
        return [issue("CONTINUITY_CATALOG_NOT_OBJECT")]
    if document.get("schema_version") != 2:
        return [issue("CONTINUITY_GENERATION_UNSUPPORTED", schema_version=document.get("schema_version"))]
    if forbidden_payload(document):
        errors.append(issue("CONTINUITY_CATALOG_FORBIDDEN_PAYLOAD"))
    fields = set(document)
    if not CATALOG_FIELDS <= fields or fields - CATALOG_FIELDS - CATALOG_OPTIONAL_FIELDS:
        errors.append(issue("CONTINUITY_CATALOG_FIELDS_INVALID"))
    project_id = document.get("project_id")
    if not isinstance(project_id, str) or PROJECT_ID.fullmatch(project_id) is None:
        errors.append(issue("CONTINUITY_PROJECT_ID_INVALID"))
    catalog_id = document.get("catalog_id")
    if (
        not isinstance(catalog_id, str)
        or not catalog_id.startswith("continuity-")
        or SAFE_ID.fullmatch(catalog_id) is None
    ):
        errors.append(issue("CONTINUITY_CATALOG_ID_INVALID"))
    if type(document.get("catalog_revision")) is not int or document["catalog_revision"] < 1:
        errors.append(issue("CONTINUITY_CATALOG_REVISION_INVALID"))
    if not valid_datetime(document.get("created_at")) or not valid_datetime(document.get("updated_at")):
        errors.append(issue("CONTINUITY_CATALOG_TIMESTAMP_INVALID"))
    references = document.get("references")
    if not isinstance(references, list) or len(references) > MAX_REFERENCES:
        errors.append(issue("CONTINUITY_REFERENCES_INVALID"))
        return errors
    for field, required in (
        ("record_type_registry", REGISTRY_REFERENCE_FIELDS),
        ("recovery_profile", PROFILE_REFERENCE_FIELDS),
    ):
        value = document.get(field)
        if not isinstance(value, dict) or set(value) != required:
            errors.append(issue("CONTINUITY_REGISTRY_REFERENCE_INVALID", field=field))
    extension = document.get("project_record_type_registry")
    if extension is not None and (not isinstance(extension, dict) or set(extension) != PROJECT_REGISTRY_REFERENCE_FIELDS):
        errors.append(issue("CONTINUITY_REGISTRY_REFERENCE_INVALID", field="project_record_type_registry"))
    errors.extend(validate_migration_extensions(document.get("migration_extensions", [])))
    return errors


def validate_reference_shape(reference: Any, index: int) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(reference, dict) or set(reference) != REFERENCE_FIELDS:
        return [issue("CONTINUITY_REFERENCE_FIELDS_INVALID", index=index)]
    for field in ("reference_id", "record_type", "profile_role", "authority_provider"):
        value = reference.get(field)
        if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
            errors.append(issue("CONTINUITY_REFERENCE_ID_INVALID", index=index, field=field))
    record_id = reference.get("record_id")
    if not isinstance(record_id, str) or not 1 <= len(record_id) <= 256:
        errors.append(issue("CONTINUITY_RECORD_ID_INVALID", index=index))
    if type_name(reference.get("record_revision")) == "invalid":
        errors.append(issue("CONTINUITY_RECORD_REVISION_INVALID", index=index))
    if reference.get("requirement") not in REQUIREMENTS:
        errors.append(issue("CONTINUITY_REQUIREMENT_INVALID", index=index))
    if reference.get("lifecycle") not in LIFECYCLES:
        errors.append(issue("CONTINUITY_LIFECYCLE_INVALID", index=index))
    if reference.get("load_policy") not in LOAD_POLICIES:
        errors.append(issue("CONTINUITY_LOAD_POLICY_INVALID", index=index))
    if reference.get("retention_class") not in RETENTION_CLASSES:
        errors.append(issue("CONTINUITY_RETENTION_CLASS_INVALID", index=index))
    if reference.get("privacy_class") not in PRIVACY_CLASSES:
        errors.append(issue("CONTINUITY_PRIVACY_CLASS_INVALID", index=index))
    if not valid_datetime(reference.get("created_at")) or not valid_datetime(reference.get("updated_at")):
        errors.append(issue("CONTINUITY_REFERENCE_TIMESTAMP_INVALID", index=index))
    source = reference.get("source")
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        errors.append(issue("CONTINUITY_SOURCE_FIELDS_INVALID", index=index))
    else:
        digest = source.get("sha256")
        commit = source.get("git_commit")
        if digest is not None and (not isinstance(digest, str) or SHA256.fullmatch(digest) is None):
            errors.append(issue("CONTINUITY_SOURCE_HASH_INVALID", index=index))
        if commit is not None and (not isinstance(commit, str) or GIT_COMMIT.fullmatch(commit) is None):
            errors.append(issue("CONTINUITY_SOURCE_COMMIT_INVALID", index=index))
        schema_id = source.get("schema_id")
        schema_version = source.get("schema_version")
        if schema_id is not None and (not isinstance(schema_id, str) or SAFE_ID.fullmatch(schema_id) is None):
            errors.append(issue("CONTINUITY_SOURCE_SCHEMA_INVALID", index=index))
        if schema_version is not None and (type(schema_version) is not int or schema_version < 1):
            errors.append(issue("CONTINUITY_SOURCE_SCHEMA_INVALID", index=index))
    dependencies = reference.get("dependencies")
    if not isinstance(dependencies, list) or len(dependencies) > MAX_LIST_ITEMS:
        errors.append(issue("CONTINUITY_DEPENDENCIES_INVALID", index=index))
    else:
        seen_dependencies: set[tuple[str, str]] = set()
        for dependency in dependencies:
            if not isinstance(dependency, dict) or set(dependency) != DEPENDENCY_FIELDS:
                errors.append(issue("CONTINUITY_DEPENDENCY_FIELDS_INVALID", index=index))
                continue
            relation = dependency.get("relation")
            target = dependency.get("target_reference_id")
            key = (str(relation), str(target))
            if (
                relation not in DEPENDENCY_RELATIONS
                or not isinstance(target, str)
                or SAFE_ID.fullmatch(target) is None
                or key in seen_dependencies
            ):
                errors.append(issue("CONTINUITY_DEPENDENCY_INVALID", index=index))
            seen_dependencies.add(key)
    supersedes = reference.get("supersedes")
    if (
        not isinstance(supersedes, list)
        or len(supersedes) > MAX_LIST_ITEMS
        or len(supersedes) != len(set(supersedes))
        or any(not isinstance(item, str) or SAFE_ID.fullmatch(item) is None for item in supersedes)
    ):
        errors.append(issue("CONTINUITY_SUPERSEDES_INVALID", index=index))
    return errors


def cycle_nodes(graph: dict[str, set[str]]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            if node in stack:
                cycles.update(stack[stack.index(node):])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for target in graph.get(node, set()):
            visit(target, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [])
    return cycles


def generic_json_identity(document: Any, rule: str) -> Any:
    if not rule.startswith("json-field:") or not isinstance(document, dict):
        return None
    return document.get(rule.split(":", 1)[1])


def revision_matches(document: Any, rule: str, expected: Any) -> bool:
    if rule == "constant:null":
        return expected is None
    if rule == "catalog-field:record_revision":
        return True
    if rule.startswith("json-field:") and isinstance(document, dict):
        return document.get(rule.split(":", 1)[1]) == expected
    return False


def provider_state(
    agent_root: Path,
    reference: dict[str, Any],
    record_contract: dict[str, Any],
    path: Path | None,
) -> tuple[str, list[dict[str, Any]]]:
    project_root = agent_root.parent
    source = reference["source"]
    relative = source["path"]
    expected_hash = source["sha256"]
    commit = source["git_commit"]
    issues: list[dict[str, Any]] = []
    if path is None:
        return "invalid", [issue("CONTINUITY_SOURCE_PATH_INVALID")]
    exists = path.is_file() and not path.is_symlink()
    if expected_hash is None:
        if (
            reference["requirement"] != "state-aware"
            or record_contract.get("missing_state_allowed") is not True
        ):
            return "invalid", [issue("CONTINUITY_NULL_HASH_NOT_ALLOWED")]
        if exists:
            return "stale", [issue("CONTINUITY_STATE_AWARE_SOURCE_APPEARED", path=relative)]
        if reference["record_type"] == "project-genesis":
            state = genesis_doctor(agent_root).get("state")
            if state != "missing":
                return "invalid", [issue("CONTINUITY_PROVIDER_MISSING_STATE_MISMATCH", provider_state=state)]
        return "missing", [issue("CONTINUITY_STATE_AWARE_SOURCE_MISSING", path=relative)]
    if not exists:
        return "missing", [issue("CONTINUITY_REQUIRED_SOURCE_MISSING", path=relative)]
    if commit is None:
        return "stale", [issue("CONTINUITY_SOURCE_COMMIT_MISSING", path=relative)]
    if not git_commit_exists(project_root, commit) or not git_commit_is_ancestor(project_root, commit):
        return "stale", [issue("CONTINUITY_SOURCE_COMMIT_UNREACHABLE", path=relative)]
    committed = git_blob(project_root, commit, relative)
    if committed is None or sha256_bytes(committed) != expected_hash:
        return "stale", [issue("CONTINUITY_SOURCE_PROVENANCE_MISMATCH", path=relative)]
    head = git_head(project_root)
    current_blob = git_blob(project_root, head, relative) if head else None
    if current_blob is None or sha256_bytes(current_blob) != expected_hash or not git_path_clean(project_root, relative):
        return "stale", [issue("CONTINUITY_SOURCE_DRIFT", path=relative)]
    try:
        document = load_json(path) if source.get("schema_id") is not None else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "invalid", [issue("CONTINUITY_SOURCE_DOCUMENT_INVALID", path=relative)]
    identity = generic_json_identity(document, str(record_contract.get("identity_rule", "")))
    if identity is not None and identity != reference.get("record_id"):
        return "invalid", [issue("CONTINUITY_RECORD_ID_MISMATCH", path=relative)]
    if not revision_matches(
        document,
        str(record_contract.get("revision_rule", "")),
        reference.get("record_revision"),
    ):
        return "stale", [issue("CONTINUITY_RECORD_REVISION_MISMATCH", path=relative)]
    record_type = reference["record_type"]
    if record_type == "project-binding":
        if not isinstance(document, dict) or document.get("project_id") != reference["record_id"]:
            return "invalid", [issue("CONTINUITY_BINDING_INVALID")]
    elif record_type == "agent-os-release":
        if (
            not isinstance(document, dict)
            or document.get("release_id") != reference["record_id"]
            or document.get("agent_os_version") != reference.get("record_revision")
        ):
            return "invalid", [issue("CONTINUITY_RELEASE_MANIFEST_INVALID")]
        release_health = verify_release_tree(agent_root)
        if release_health.get("ok") is not True:
            return "invalid", [
                issue(
                    "CONTINUITY_RELEASE_MANIFEST_INVALID",
                    provider_reason_codes=release_health.get("reason_codes", []),
                )
            ]
    elif record_type == "project-genesis":
        state = genesis_doctor(agent_root).get("state")
        if state == "confirmed":
            return "available", []
        mapped = {
            "missing": "missing",
            "stale": "stale",
            "conflicting": "conflicting",
            "contaminated": "invalid",
            "draft": "unavailable",
        }
        return mapped.get(str(state), "invalid"), [issue("CONTINUITY_GENESIS_NOT_READY", provider_state=state)]
    elif record_type == "context-manifest":
        state = ContextMemoryService(agent_root).doctor().get("state")
        mapped = {"FRESH": "available", "STALE": "stale", "DEGRADED": "invalid", "UNCONFIGURED": "missing"}
        readiness = mapped.get(str(state), "invalid")
        return readiness, [] if readiness == "available" else [issue("CONTINUITY_CONTEXT_NOT_READY", provider_state=state)]
    elif record_type == "active-task-ledger":
        binding = load_json(agent_root / BINDING_REL)
        project_id = binding.get("project_id") if isinstance(binding, dict) else ""
        task_errors, task_stale, task_conflicts = ContextMemoryService(agent_root).validate_tasks(
            document,
            str(project_id),
        )
        if task_conflicts:
            return "conflicting", [issue("CONTINUITY_TASK_LEDGER_CONFLICTING")]
        if task_errors:
            return "invalid", [issue("CONTINUITY_TASK_LEDGER_INVALID")]
        if task_stale:
            return "stale", [issue("CONTINUITY_TASK_LEDGER_STALE")]
    elif record_type == "handoff-receipt":
        validation = ContextMemoryService(agent_root).validate_handoffs()
        valid_ids = {
            item.get("id")
            for item in validation.get("valid_receipts", [])
            if isinstance(item, dict)
        }
        if reference["record_id"] not in valid_ids:
            return "invalid", [issue("CONTINUITY_HANDOFF_INVALID_OR_TAMPERED")]
    elif record_type == "context-record":
        stores = ContextMemoryService(agent_root).current_stores()
        records = [
            item
            for store in stores.values()
            for item in store.get("records", [])
            if isinstance(store, dict) and isinstance(item, dict)
        ]
        if not any(item.get("id") == reference["record_id"] for item in records):
            return "missing", [issue("CONTINUITY_CONTEXT_RECORD_MISSING")]
    return "available", issues


def derive_topology(
    *,
    structural: list[dict[str, Any]],
    contaminated: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
    incomplete: list[dict[str, Any]],
) -> str:
    if contaminated:
        return "contaminated"
    if structural:
        return "corrupt"
    if unsupported:
        return "unsupported"
    if incomplete:
        return "incomplete"
    return "complete"


def doctor(agent_root: Path = ROOT, catalog_path: Path | None = None) -> dict[str, Any]:
    agent_root = agent_root.resolve()
    project_root = agent_root.parent
    catalog_path = catalog_path or agent_root / CATALOG_REL
    result_base = {
        "project_id": None,
        "catalog_path": catalog_path.relative_to(project_root).as_posix()
        if catalog_path.is_relative_to(project_root)
        else None,
        "raw_conversation_stored": False,
        "write_performed": False,
    }
    if not catalog_path.exists():
        return {
            "ok": False,
            "state": "UNCONFIGURED",
            "topology_state": "unconfigured",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_CATALOG_MISSING"],
            "errors": [],
            "warnings": [],
            "references": [],
            **result_base,
        }
    if catalog_path.is_symlink() or not catalog_path.is_file():
        return {
            "ok": False,
            "state": "CONTAMINATED",
            "topology_state": "contaminated",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_CATALOG_PATH_INVALID"],
            "errors": [issue("CONTINUITY_CATALOG_PATH_INVALID")],
            "warnings": [],
            "references": [],
            **result_base,
        }
    try:
        catalog_size = catalog_path.stat().st_size
    except OSError as exc:
        return {
            "ok": False,
            "state": "CORRUPT",
            "topology_state": "corrupt",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_CATALOG_UNREADABLE"],
            "errors": [issue("CONTINUITY_CATALOG_UNREADABLE", detail=str(exc)[:240])],
            "warnings": [],
            "references": [],
            **result_base,
        }
    if catalog_size > MAX_JSON_BYTES:
        return {
            "ok": False,
            "state": "CORRUPT",
            "topology_state": "corrupt",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_CATALOG_READ_BOUND_EXCEEDED"],
            "errors": [
                issue(
                    "CONTINUITY_CATALOG_READ_BOUND_EXCEEDED",
                    bytes=catalog_size,
                    maximum=MAX_JSON_BYTES,
                )
            ],
            "warnings": [],
            "references": [],
            **result_base,
        }
    raw_catalog = catalog_path.read_bytes()
    try:
        catalog = load_json(catalog_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        return {
            "ok": False,
            "state": "CORRUPT",
            "topology_state": "corrupt",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_CATALOG_INVALID_JSON"],
            "errors": [issue("CONTINUITY_CATALOG_INVALID_JSON", detail=str(exc)[:240])],
            "warnings": [],
            "references": [],
            **result_base,
        }
    try:
        catalog_forbidden = forbidden_payload(catalog)
    except RecursionError:
        catalog_forbidden = False
        catalog_nesting_invalid = True
    else:
        catalog_nesting_invalid = False
    if catalog_forbidden or catalog_nesting_invalid:
        code = (
            "CONTINUITY_CATALOG_FORBIDDEN_PAYLOAD"
            if catalog_forbidden
            else "CONTINUITY_CATALOG_NESTING_INVALID"
        )
        return {
            "ok": False,
            "state": "CORRUPT",
            "topology_state": "corrupt",
            "authority_state": "unavailable",
            "reason_codes": [code],
            "errors": [issue(code)],
            "warnings": [],
            "references": [],
            **result_base,
        }
    if isinstance(catalog, dict) and catalog.get("schema_version") == 1:
        return {
            "ok": False,
            "state": "MIGRATION_REQUIRED",
            "topology_state": "migration-required",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_MIGRATION_REQUIRED"],
            "errors": [
                issue(
                    "CONTINUITY_MIGRATION_REQUIRED",
                    source_generation=1,
                    target_generation=2,
                )
            ],
            "warnings": [],
            "references": [],
            "preserved_catalog_sha256": sha256_bytes(raw_catalog),
            **result_base,
        }
    try:
        shape_errors = validate_catalog_shape(catalog)
    except RecursionError:
        shape_errors = [issue("CONTINUITY_CATALOG_NESTING_INVALID")]
    if any(item["code"] == "CONTINUITY_GENERATION_UNSUPPORTED" for item in shape_errors):
        return {
            "ok": False,
            "state": "UNSUPPORTED",
            "topology_state": "unsupported",
            "authority_state": "unavailable",
            "reason_codes": ["CONTINUITY_GENERATION_UNSUPPORTED"],
            "errors": shape_errors,
            "warnings": [],
            "references": [],
            "preserved_catalog_sha256": sha256_bytes(raw_catalog),
            **result_base,
        }
    structural = list(shape_errors)
    contaminated: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if structural:
        topology = derive_topology(
            structural=structural,
            contaminated=contaminated,
            unsupported=unsupported,
            incomplete=incomplete,
        )
        return {
            "ok": False,
            "state": topology.upper(),
            "topology_state": topology,
            "authority_state": "unavailable",
            "reason_codes": list(dict.fromkeys(item["code"] for item in structural)),
            "errors": structural,
            "warnings": [],
            "references": [],
            **result_base,
        }
    project_id = catalog["project_id"]
    result_base["project_id"] = project_id
    binding_path = agent_root / BINDING_REL
    try:
        binding = load_json(binding_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        binding = None
    binding_project_id = binding.get("project_id") if isinstance(binding, dict) else None
    if binding_project_id != project_id:
        contaminated.append(
            issue(
                "CONTINUITY_PROJECT_BINDING_MISMATCH",
                catalog_project_id=project_id,
                binding_project_id=binding_project_id,
            )
        )

    core_registry_path = agent_root / CORE_REGISTRY_REL
    profile_registry_path = agent_root / PROFILE_REGISTRY_REL
    try:
        core_registry_document = load_json(core_registry_path)
        profile_registry_document = load_json(profile_registry_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        structural.append(issue("CONTINUITY_CORE_CONTRACT_UNREADABLE", detail=str(exc)[:240]))
        core_registry_document = {}
        profile_registry_document = {}
    type_registry, registry_errors = validate_registry(core_registry_document)
    structural.extend(registry_errors)
    profiles, profile_errors = validate_profiles(profile_registry_document, type_registry)
    structural.extend(profile_errors)

    registry_ref = catalog["record_type_registry"]
    profile_ref = catalog["recovery_profile"]
    if (
        registry_ref.get("registry_id") != core_registry_document.get("registry_id")
        or registry_ref.get("registry_version") != core_registry_document.get("registry_version")
        or registry_ref.get("registry_sha256") != optional_sha256_file(core_registry_path)
    ):
        structural.append(issue("CONTINUITY_CORE_REGISTRY_DRIFT"))
    profile_key = f"{profile_ref.get('profile_id')}@{profile_ref.get('profile_version')}"
    profile = profiles.get(profile_key)
    if (
        profile is None
        or profile_ref.get("profile_sha256") != optional_sha256_file(profile_registry_path)
    ):
        structural.append(issue("CONTINUITY_RECOVERY_PROFILE_DRIFT"))
    if profile is not None and len(raw_catalog) > profile.get("catalog_max_bytes", 0):
        structural.append(
            issue(
                "CONTINUITY_CATALOG_BUDGET_EXCEEDED",
                bytes=len(raw_catalog),
                maximum=profile["catalog_max_bytes"],
            )
        )

    extension_ref = catalog.get("project_record_type_registry")
    if isinstance(extension_ref, dict):
        extension_path, path_errors = source_path(project_root, extension_ref["path"])
        contaminated.extend(path_errors)
        if extension_path is None or not extension_path.is_file() or extension_path.is_symlink():
            structural.append(issue("CONTINUITY_EXTENSION_REGISTRY_MISSING"))
        else:
            try:
                extension_document = load_json(extension_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                structural.append(issue("CONTINUITY_EXTENSION_REGISTRY_INVALID"))
            else:
                extension_types, extension_errors = validate_registry(
                    extension_document,
                    project_id=project_id,
                    extension=True,
                )
                structural.extend(extension_errors)
                if (
                    extension_ref.get("registry_id") != extension_document.get("registry_id")
                    or extension_ref.get("registry_version") != extension_document.get("registry_version")
                    or extension_ref.get("registry_sha256") != sha256_file(extension_path)
                ):
                    structural.append(issue("CONTINUITY_EXTENSION_REGISTRY_DRIFT"))
                collisions = set(type_registry) & set(extension_types)
                if collisions:
                    structural.append(issue("CONTINUITY_EXTENSION_OVERRIDES_CORE", record_types=sorted(collisions)))
                else:
                    type_registry.update(extension_types)

    references = catalog["references"]
    for index, reference in enumerate(references):
        structural.extend(validate_reference_shape(reference, index))
    if structural or contaminated:
        topology = derive_topology(
            structural=structural,
            contaminated=contaminated,
            unsupported=unsupported,
            incomplete=incomplete,
        )
        all_errors = [*contaminated, *structural]
        return {
            "ok": False,
            "state": topology.upper(),
            "topology_state": topology,
            "authority_state": "unavailable",
            "reason_codes": list(dict.fromkeys(item["code"] for item in all_errors)),
            "errors": all_errors,
            "warnings": warnings,
            "references": [],
            **result_base,
        }

    by_id: dict[str, dict[str, Any]] = {}
    identity_keys: dict[tuple[str, str, Any], str] = {}
    for reference in references:
        reference_id = reference["reference_id"]
        if reference_id in by_id:
            structural.append(issue("CONTINUITY_REFERENCE_ID_DUPLICATE", reference_id=reference_id))
        else:
            by_id[reference_id] = reference
        identity_key = (
            reference["record_type"],
            reference["record_id"],
            reference["record_revision"],
        )
        if identity_key in identity_keys:
            structural.append(
                issue(
                    "CONTINUITY_RECORD_IDENTITY_DUPLICATE",
                    reference_id=reference_id,
                    previous_reference_id=identity_keys[identity_key],
                )
            )
        else:
            identity_keys[identity_key] = reference_id

    role_map = {
        role["profile_role"]: role
        for role in (profile.get("roles", []) if isinstance(profile, dict) else [])
    }
    role_counts = Counter(
        reference["profile_role"]
        for reference in references
        if reference["lifecycle"] == "active"
    )
    conditional_roles: list[dict[str, Any]] = []
    for role_id, role in role_map.items():
        count = role_counts.get(role_id, 0)
        minimum = role["minimum"]
        maximum = role["maximum"]
        if role["activation"] == "always" and count < minimum:
            incomplete.append(
                issue(
                    "CONTINUITY_PROFILE_ROLE_MISSING",
                    profile_role=role_id,
                    minimum=minimum,
                    actual=count,
                )
            )
        elif role["activation"] != "always":
            conditional_roles.append(
                {
                    "profile_role": role_id,
                    "activation": role["activation"],
                    "actual": count,
                    "maximum": maximum,
                }
            )
        if count > maximum:
            structural.append(
                issue(
                    "CONTINUITY_PROFILE_CARDINALITY_EXCEEDED",
                    profile_role=role_id,
                    maximum=maximum,
                    actual=count,
                )
            )
    for role_id in sorted(set(role_counts) - set(role_map)):
        structural.append(issue("CONTINUITY_PROFILE_ROLE_UNKNOWN", profile_role=role_id))

    dependency_graph: dict[str, set[str]] = defaultdict(set)
    supersession_graph: dict[str, set[str]] = defaultdict(set)
    active_successors: dict[str, list[str]] = defaultdict(list)
    terminal_handoffs: set[str] = set()
    reference_results: list[dict[str, Any]] = []
    for reference in references:
        reference_id = reference["reference_id"]
        contract = type_registry.get(reference["record_type"])
        if contract is None:
            unsupported.append(
                issue(
                    "CONTINUITY_RECORD_TYPE_UNSUPPORTED",
                    reference_id=reference_id,
                    record_type=reference["record_type"],
                )
            )
            reference_results.append(
                {
                    "reference_id": reference_id,
                    "record_type": reference["record_type"],
                    "profile_role": reference["profile_role"],
                    "readiness": "unavailable",
                    "reason_codes": ["CONTINUITY_RECORD_TYPE_UNSUPPORTED"],
                }
            )
            continue
        role = role_map.get(reference["profile_role"])
        if role is not None:
            if (
                role["record_type"] != reference["record_type"]
                or role["requirement"] != reference["requirement"]
                or role["load_policy"] != reference["load_policy"]
            ):
                structural.append(issue("CONTINUITY_PROFILE_ROLE_CONTRACT_MISMATCH", reference_id=reference_id))
        if reference["authority_provider"] != contract["authority_provider"]:
            structural.append(issue("CONTINUITY_AUTHORITY_PROVIDER_MISMATCH", reference_id=reference_id))
        if reference["requirement"] not in contract["allowed_requirements"]:
            structural.append(issue("CONTINUITY_REQUIREMENT_NOT_ALLOWED", reference_id=reference_id))
        if reference["load_policy"] not in contract["allowed_load_policies"]:
            structural.append(issue("CONTINUITY_LOAD_POLICY_NOT_ALLOWED", reference_id=reference_id))
        if reference["retention_class"] not in contract["allowed_retention_classes"]:
            structural.append(issue("CONTINUITY_RETENTION_NOT_ALLOWED", reference_id=reference_id))
        if type_name(reference["record_revision"]) not in contract["revision_types"]:
            structural.append(issue("CONTINUITY_REVISION_TYPE_NOT_ALLOWED", reference_id=reference_id))
        schema_ok, generation_unsupported = supported_schema(
            contract,
            reference["source"]["schema_id"],
            reference["source"]["schema_version"],
        )
        if not schema_ok:
            target = unsupported if generation_unsupported else structural
            target.append(issue("CONTINUITY_SOURCE_SCHEMA_UNSUPPORTED", reference_id=reference_id))
        path, path_errors = source_path(project_root, reference["source"]["path"])
        contaminated.extend(path_errors)
        for dependency in reference["dependencies"]:
            relation = dependency["relation"]
            target_id = dependency["target_reference_id"]
            if relation not in contract["allowed_dependency_relations"]:
                structural.append(
                    issue(
                        "CONTINUITY_DEPENDENCY_RELATION_NOT_ALLOWED",
                        reference_id=reference_id,
                        relation=relation,
                    )
                )
            if target_id not in by_id:
                target = (
                    incomplete
                    if reference["requirement"] in {"required", "state-aware"}
                    or relation in {"requires", "generated-from", "verified-by", "hands-off"}
                    else warnings
                )
                target.append(
                    issue(
                        "CONTINUITY_DEPENDENCY_DANGLING",
                        reference_id=reference_id,
                        target_reference_id=target_id,
                    )
                )
            if relation in {"requires", "generated-from"}:
                dependency_graph[reference_id].add(target_id)
        for target_id in reference["supersedes"]:
            supersession_graph[reference_id].add(target_id)
            target_reference = by_id.get(target_id)
            if target_id == reference_id:
                structural.append(issue("CONTINUITY_SUPERSESSION_SELF_REFERENCE", reference_id=reference_id))
            elif target_reference is None:
                structural.append(issue("CONTINUITY_SUPERSESSION_DANGLING", reference_id=reference_id))
            elif target_reference["record_type"] != reference["record_type"]:
                structural.append(issue("CONTINUITY_SUPERSESSION_CROSS_TYPE", reference_id=reference_id))
            elif reference["lifecycle"] == "active":
                active_successors[target_id].append(reference_id)
        readiness, readiness_issues = provider_state(agent_root, reference, contract, path)
        if readiness == "missing" and reference["requirement"] == "required":
            incomplete.append(issue("CONTINUITY_REQUIRED_SOURCE_MISSING", reference_id=reference_id))
        if reference["record_type"].startswith(f"project.{project_id}."):
            readiness = "unavailable"
            readiness_issues.append(issue("CONTINUITY_EXTENSION_PROVIDER_UNAVAILABLE", reference_id=reference_id))
        if reference["record_type"] == "handoff-receipt" and path is not None and path.is_file():
            try:
                handoff_document = load_json(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                handoff_document = None
            if (
                isinstance(handoff_document, dict)
                and handoff_document.get("to_owner") is None
                and handoff_document.get("verified_outcomes")
            ):
                terminal_handoffs.add(reference_id)
        reference_results.append(
            {
                "reference_id": reference_id,
                "record_type": reference["record_type"],
                "profile_role": reference["profile_role"],
                "requirement": reference["requirement"],
                "load_policy": reference["load_policy"],
                "lifecycle": reference["lifecycle"],
                "readiness": readiness,
                "reason_codes": list(dict.fromkeys(item["code"] for item in readiness_issues)),
            }
        )

    dependency_cycles = cycle_nodes(dependency_graph)
    if dependency_cycles:
        structural.append(issue("CONTINUITY_DEPENDENCY_CYCLE", reference_ids=sorted(dependency_cycles)))
    supersession_cycles = cycle_nodes(supersession_graph)
    if supersession_cycles:
        structural.append(issue("CONTINUITY_SUPERSESSION_CYCLE", reference_ids=sorted(supersession_cycles)))
    for target_id, successors in active_successors.items():
        if len(successors) > 1:
            structural.append(
                issue(
                    "CONTINUITY_ACTIVE_SUCCESSOR_CONFLICT",
                    target_reference_id=target_id,
                    successor_reference_ids=sorted(successors),
                )
            )
            for item in reference_results:
                if item.get("reference_id") in successors:
                    item["readiness"] = "conflicting"
                    item["reason_codes"] = list(
                        dict.fromkeys(
                            [
                                *item.get("reason_codes", []),
                                "CONTINUITY_ACTIVE_SUCCESSOR_CONFLICT",
                            ]
                        )
                    )
        target = by_id.get(target_id)
        if target is not None and target["lifecycle"] == "active":
            structural.append(issue("CONTINUITY_SUPERSEDED_TARGET_STILL_ACTIVE", reference_id=target_id))
    for reference in references:
        if (
            reference["lifecycle"] in {"archived", "superseded"}
            and reference["requirement"] == "required"
            and reference["reference_id"] not in active_successors
        ):
            incomplete.append(
                issue(
                    "CONTINUITY_REQUIRED_REFERENCE_NOT_ACTIVE",
                    reference_id=reference["reference_id"],
                )
            )
    verification_ids = {
        reference["reference_id"]
        for reference in references
        if reference["profile_role"] == "completion-verification"
        and reference["lifecycle"] == "active"
    }
    for handoff_id in terminal_handoffs:
        verified_targets = {
            dependency["target_reference_id"]
            for dependency in by_id[handoff_id]["dependencies"]
            if dependency["relation"] == "verified-by"
        }
        if not verified_targets or not verified_targets <= verification_ids:
            incomplete.append(
                issue(
                    "CONTINUITY_COMPLETION_VERIFICATION_MISSING",
                    reference_id=handoff_id,
                )
            )

    topology = derive_topology(
        structural=structural,
        contaminated=contaminated,
        unsupported=unsupported,
        incomplete=incomplete,
    )
    active_required = [
        item
        for item in reference_results
        if item.get("lifecycle") == "active" and item.get("requirement") == "required"
    ]
    unavailable_required = [item for item in active_required if item.get("readiness") != "available"]
    unavailable_state_aware = [
        item
        for item in reference_results
        if item.get("lifecycle") == "active"
        and item.get("requirement") == "state-aware"
        and item.get("readiness") != "available"
    ]
    authority_state = (
        "available"
        if not unavailable_required and not unavailable_state_aware
        else "partial"
        if topology == "complete" and not unavailable_required
        else "unavailable"
    )
    projection = {
        "schema_version": 1,
        "project_id": project_id,
        "catalog_id": catalog["catalog_id"],
        "catalog_revision": catalog["catalog_revision"],
        "catalog_sha256": sha256_bytes(raw_catalog),
        "registry_sha256": registry_ref["registry_sha256"],
        "profile_sha256": profile_ref["profile_sha256"],
        "boot_references": [
            {
                "reference_id": item["reference_id"],
                "record_type": item["record_type"],
                "profile_role": item["profile_role"],
                "readiness": item["readiness"],
            }
            for item in reference_results
            if item.get("load_policy") == "boot"
            and item.get("lifecycle") == "active"
            and item.get("readiness") == "available"
        ],
    }
    if profile is not None and len(json_bytes(projection)) > profile["projection_max_bytes"]:
        structural.append(
            issue(
                "CONTINUITY_PROJECTION_BUDGET_EXCEEDED",
                bytes=len(json_bytes(projection)),
                maximum=profile["projection_max_bytes"],
            )
        )
        topology = "corrupt"
        authority_state = "unavailable"
        projection = {}
    all_errors = [*contaminated, *structural, *unsupported, *incomplete]
    readiness_codes = [
        code
        for item in reference_results
        for code in item.get("reason_codes", [])
    ]
    return {
        "ok": topology == "complete",
        "state": topology.upper(),
        "topology_state": topology,
        "authority_state": authority_state,
        "reason_codes": list(
            dict.fromkeys([*(item["code"] for item in all_errors), *readiness_codes])
        ),
        "errors": all_errors,
        "warnings": warnings,
        "references": reference_results,
        "summary": {
            "references": len(reference_results),
            "active_required": len(active_required),
            "available_required": len(active_required) - len(unavailable_required),
            "state_aware_unavailable": len(unavailable_state_aware),
            "executable_provider_checks": len(reference_results),
            "conditional_roles": conditional_roles,
        },
        "projection_preview": projection,
        **result_base,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS continuity catalog doctor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    args = parser.parse_args()
    result = doctor() if args.command == "doctor" else {"ok": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") or result.get("state") == "UNCONFIGURED" else 2)


if __name__ == "__main__":
    main()
