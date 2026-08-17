"""Project binding and adapter-fingerprint validation contracts."""
# ruff: noqa: I001

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

# fmt: off
from lifecycle.shared import FULL_COMMIT, FULL_SHA256, canonical_sha256, git_output, load_json

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent
FINGERPRINT_PATH = ROOT / "project" / "adapter-fingerprint.json"
PROJECT_MEMORY_PATH = ROOT / "skills" / "project-memory" / "SKILL.md"
ALLOWED_RUNNERS = {
    "npm-script",
    "pnpm-script",
    "yarn-script",
    "bun-script",
    "make-target",
    "task-target",
}


def normalized_binding_sections(binding: dict[str, Any]) -> dict[str, Any]:
    repository = binding.get("repository", {}) if isinstance(binding.get("repository"), dict) else {}
    workspaces = binding.get("workspaces", []) if isinstance(binding.get("workspaces"), list) else []
    commands = binding.get("commands", []) if isinstance(binding.get("commands"), list) else []
    context_entrypoints = (
        binding.get("context_entrypoints", [])
        if isinstance(binding.get("context_entrypoints"), list)
        else []
    )
    normalized_workspaces = []
    for workspace in workspaces:
        if not isinstance(workspace, dict):
            normalized_workspaces.append(workspace)
            continue
        normalized_workspaces.append(
            {
                "id": workspace.get("id"),
                "path": workspace.get("path"),
                "root_markers": sorted(workspace.get("root_markers", []), key=str),
            }
        )
    normalized_commands = [command for command in commands]
    normalized_workspaces.sort(key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "")
    normalized_commands.sort(key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "")
    return {
        "project_identity": {
            "project_id": binding.get("project_id"),
            "repository": {
                "kind": repository.get("kind"),
                "root_markers": sorted(repository.get("root_markers", []), key=str),
                "remote_aliases": sorted(repository.get("remote_aliases", []), key=str),
            },
            "workspaces": normalized_workspaces,
        },
        "commands": normalized_commands,
        "context_entrypoints": sorted(context_entrypoints, key=str),
    }


def expected_adapter_digests(binding: dict[str, Any]) -> dict[str, str]:
    sections = normalized_binding_sections(binding)
    return {name: canonical_sha256(value) for name, value in sections.items()}
def safe_relative(raw: Any) -> tuple[Path | None, str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, "PATH_EMPTY"
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, "PATH_OUTSIDE_PROJECT"
    resolved = (PROJECT_ROOT / candidate).resolve()
    project_root = PROJECT_ROOT.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        return None, "PATH_OUTSIDE_PROJECT"
    return resolved, None


def contains_absolute_or_secret(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in ("secret", "password", "token", "api_key", "apikey")):
                findings.append(f"SENSITIVE_FIELD:{path}.{key}")
            findings.extend(contains_absolute_or_secret(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(contains_absolute_or_secret(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if value.startswith(("/", "~/")) or re.match(r"^[A-Za-z]:[\\/]", value):
            findings.append(f"ABSOLUTE_PATH:{path}")
    return findings


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def unique_string_list(value: Any, *, non_empty: bool = False) -> bool:
    if not isinstance(value, list) or (non_empty and not value):
        return False
    return all(isinstance(item, str) and item for item in value) and len(value) == len(set(value))


def resolve_json_pointer(document: Any, pointer: str) -> tuple[Any, str | None]:
    if pointer == "":
        return document, None
    if not pointer.startswith("/"):
        return None, "JSON_POINTER_INVALID"
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
            continue
        if isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
            continue
        return None, "JSON_POINTER_MISSING"
    return current, None


def validate_binding(binding: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    allowed_binding_fields = {
        "schema_version",
        "project_id",
        "repository",
        "workspaces",
        "commands",
        "context_entrypoints",
        "created_at",
        "last_verified_at",
        "last_verified_commit",
    }
    unknown_binding_fields = sorted(set(binding) - allowed_binding_fields)
    if unknown_binding_fields:
        errors.append(f"binding contains unsupported fields: {', '.join(unknown_binding_fields)}")
    if binding.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    project_id = binding.get("project_id")
    if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", project_id):
        errors.append("project_id is invalid")
    for field in ("created_at", "last_verified_at"):
        if not valid_timestamp(binding.get(field)):
            errors.append(f"{field} must be an ISO-8601 timestamp")
    last_verified_commit = binding.get("last_verified_commit")
    if last_verified_commit is not None and (
        not isinstance(last_verified_commit, str) or not FULL_COMMIT.fullmatch(last_verified_commit)
    ):
        errors.append("last_verified_commit must be a full Git commit or null")

    repository = binding.get("repository")
    if not isinstance(repository, dict) or repository.get("kind") not in {"git", "directory"}:
        errors.append("repository.kind must be git or directory")
        repository = {}
    else:
        unknown_repository_fields = sorted(set(repository) - {"kind", "root_markers", "remote_aliases"})
        if unknown_repository_fields:
            errors.append(f"repository contains unsupported fields: {', '.join(unknown_repository_fields)}")
    markers = repository.get("root_markers", [])
    if not unique_string_list(markers, non_empty=True):
        errors.append("repository.root_markers must be a non-empty unique list")
        markers = []
    for marker in markers:
        path, path_error = safe_relative(marker)
        if path_error or path is None or not path.exists():
            errors.append(f"root marker missing or unsafe: {marker}")
    remote_aliases = repository.get("remote_aliases", [])
    if not unique_string_list(remote_aliases):
        errors.append("repository.remote_aliases must be a unique list")
        remote_aliases = []

    workspace_ids = {"."}
    workspace_paths = {".": PROJECT_ROOT.resolve()}
    workspaces = binding.get("workspaces", [])
    if not isinstance(workspaces, list):
        errors.append("workspaces must be a list")
        workspaces = []
    for index, workspace in enumerate(workspaces):
        if not isinstance(workspace, dict):
            errors.append(f"workspace {index} must be an object")
            continue
        if set(workspace) - {"id", "path", "root_markers"}:
            errors.append(f"workspace {index} contains unsupported fields")
        workspace_id = workspace.get("id")
        workspace_path = workspace.get("path")
        workspace_markers = workspace.get("root_markers")
        if not isinstance(workspace_id, str) or not workspace_id or workspace_id in workspace_ids:
            errors.append(f"workspace {index} id is invalid or duplicated")
            continue
        workspace_ids.add(workspace_id)
        resolved_workspace, workspace_error = safe_relative(workspace_path)
        if workspace_error or resolved_workspace is None or not resolved_workspace.is_dir():
            errors.append(f"workspace {workspace_id} path is missing or unsafe")
            continue
        workspace_paths[workspace_id] = resolved_workspace
        if not unique_string_list(workspace_markers, non_empty=True):
            errors.append(f"workspace {workspace_id} root_markers must be a non-empty list")
            continue
        for marker in workspace_markers:
            marker_path, marker_error = safe_relative(str(Path(str(workspace_path)) / str(marker)))
            if marker_error or marker_path is None or not marker_path.exists():
                errors.append(f"workspace {workspace_id} marker missing or unsafe: {marker}")

    commands = binding.get("commands")
    if not isinstance(commands, list):
        errors.append("commands must be a list")
        commands = []
    command_ids: set[str] = set()
    command_fields = {"id", "workspace", "runner", "script", "evidence", "risk", "requires_confirmation"}
    required_command_fields = {"id", "workspace", "runner", "script", "evidence", "risk"}
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            errors.append(f"command {index} must be an object")
            continue
        missing_fields = sorted(required_command_fields - set(command))
        if missing_fields:
            errors.append(f"command {index} is missing fields: {', '.join(missing_fields)}")
        if set(command) - command_fields:
            errors.append(f"command {index} contains unsupported fields")
        command_id = command.get("id")
        if not isinstance(command_id, str) or not command_id or command_id in command_ids:
            errors.append(f"command {index} id is invalid or duplicated")
        else:
            command_ids.add(command_id)
        if command.get("workspace") not in workspace_ids:
            errors.append(f"command {index} references an unknown workspace")
        runner = command.get("runner")
        if runner not in ALLOWED_RUNNERS:
            errors.append(f"command {index} uses an unsupported runner")
        script = command.get("script")
        if not isinstance(script, str) or not script:
            errors.append(f"command {index} script is invalid")
        evidence = command.get("evidence")
        evidence_path, separator, pointer = evidence.partition("#") if isinstance(evidence, str) else ("", "", "")
        path, path_error = safe_relative(evidence_path)
        if path_error or path is None or not path.is_file():
            errors.append(f"command {index} evidence is missing or unsafe")
        elif runner in {"npm-script", "pnpm-script", "yarn-script", "bun-script"}:
            declared_workspace = workspace_paths.get(command.get("workspace"))
            if declared_workspace is None or (
                path != declared_workspace and declared_workspace not in path.parents
            ):
                errors.append(f"command {index} evidence is outside its declared workspace")
            document = load_json(path, None)
            resolved, pointer_error = resolve_json_pointer(document, pointer if separator else "")
            escaped_script = script.replace("~", "~0").replace("/", "~1") if isinstance(script, str) else ""
            expected_pointer = f"/scripts/{escaped_script}"
            if pointer_error or not isinstance(resolved, str) or pointer != expected_pointer:
                errors.append(f"command {index} evidence does not resolve the declared package script")
        risk = command.get("risk")
        if risk not in {"read_only", "non_destructive", "destructive"}:
            errors.append(f"command {index} risk is invalid")
        if risk == "destructive" and command.get("requires_confirmation") is not True:
            errors.append(f"command {index} is destructive without confirmation")
        if "requires_confirmation" in command and not isinstance(command.get("requires_confirmation"), bool):
            errors.append(f"command {index} requires_confirmation must be boolean")

    context_entrypoints = binding.get("context_entrypoints", [])
    if not unique_string_list(context_entrypoints):
        errors.append("context_entrypoints must be a unique list")
        context_entrypoints = []
    for entrypoint in context_entrypoints:
        path, path_error = safe_relative(entrypoint)
        if path_error or path is None or not path.is_file():
            errors.append(f"context entrypoint missing or unsafe: {entrypoint}")

    errors.extend(contains_absolute_or_secret(binding))
    if repository.get("kind") == "git" and git_output("rev-parse", "--show-toplevel") is None:
        errors.append("repository declares git but Git metadata is unavailable")
    if remote_aliases:
        remotes = git_output("remote", "-v") or ""
        if not any(str(alias) in remotes for alias in remote_aliases):
            warnings.append("No configured Git remote matches repository.remote_aliases")

    if PROJECT_MEMORY_PATH.is_file() and isinstance(project_id, str):
        memory = PROJECT_MEMORY_PATH.read_text(encoding="utf-8", errors="ignore")
        associations = re.findall(r"^Project ID:\s*`([^`]+)`\s*$", memory, flags=re.MULTILINE)
        if associations != [project_id]:
            errors.append("Project Memory project association is missing or mismatched")
    return errors, warnings


def validate_fingerprint(binding: dict[str, Any]) -> list[str]:
    if not FINGERPRINT_PATH.is_file():
        return ["adapter fingerprint is missing"]
    fingerprint = load_json(FINGERPRINT_PATH, None)
    if not isinstance(fingerprint, dict):
        return ["adapter fingerprint is not valid JSON object data"]
    errors: list[str] = []
    allowed_fields = {
        "schema_version",
        "project_id",
        "binding_schema_version",
        "algorithm",
        "digests",
        "verified_at",
        "verified_commit",
    }
    if set(fingerprint) - allowed_fields:
        errors.append("adapter fingerprint contains unsupported fields")
    if fingerprint.get("schema_version") != 1:
        errors.append("adapter fingerprint schema_version must equal 1")
    if fingerprint.get("project_id") != binding.get("project_id"):
        errors.append("adapter fingerprint project_id mismatch")
    if fingerprint.get("binding_schema_version") != binding.get("schema_version"):
        errors.append("adapter fingerprint binding schema mismatch")
    if fingerprint.get("algorithm") != "sha256":
        errors.append("adapter fingerprint algorithm must be sha256")
    if not valid_timestamp(fingerprint.get("verified_at")):
        errors.append("adapter fingerprint verified_at is invalid")
    elif fingerprint.get("verified_at") != binding.get("last_verified_at"):
        errors.append("adapter fingerprint verified_at does not match binding verification metadata")
    verified_commit = fingerprint.get("verified_commit")
    if verified_commit is not None and (
        not isinstance(verified_commit, str) or not FULL_COMMIT.fullmatch(verified_commit)
    ):
        errors.append("adapter fingerprint verified_commit must be a full Git commit or null")
    elif verified_commit != binding.get("last_verified_commit"):
        errors.append("adapter fingerprint verified_commit does not match binding verification metadata")
    digests = fingerprint.get("digests")
    expected = expected_adapter_digests(binding)
    if not isinstance(digests, dict) or set(digests) != set(expected):
        errors.append("adapter fingerprint digests are incomplete")
    else:
        for name, expected_digest in expected.items():
            actual_digest = digests.get(name)
            if not isinstance(actual_digest, str) or not FULL_SHA256.fullmatch(actual_digest):
                errors.append(f"adapter fingerprint digest is invalid: {name}")
            elif actual_digest != expected_digest:
                errors.append(f"adapter fingerprint digest mismatch: {name}")
    errors.extend(contains_absolute_or_secret(fingerprint))
    return errors


def adapter_reason_codes(errors: list[str]) -> list[str]:
    reasons: list[str] = []
    if any("project association" in error or "project_id mismatch" in error for error in errors):
        reasons.append("PROJECT_IDENTITY_MISMATCH")
    if any(error.startswith("command ") for error in errors):
        reasons.append("COMMAND_EVIDENCE_MISSING")
    if any("context entrypoint" in error for error in errors):
        reasons.append("CONTEXT_ENTRY_MISSING")
    if any("fingerprint" in error for error in errors):
        reasons.append("ADAPTER_FINGERPRINT_INVALID")
    if errors:
        reasons.append("ADAPTER_VALIDATION_FAILED")
    return reasons
# fmt: on
