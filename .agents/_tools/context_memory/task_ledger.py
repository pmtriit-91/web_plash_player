"""Task-ledger validation and bounded v1/v2 mutation boundary.

This module owns task-specific rules while ``agent_os_context_memory`` remains the
stable facade and transaction engine, including bounded v1/v2 transitions.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from agent_os_paths import portable_relative

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,95}$")
LEGACY_OPAQUE_TASK_SCOPE_PREFIXES = ("NotebookLM notebook: ",)
ACTIVE_TASK_STATES = {"active", "blocked"}
TASK_STATES = ACTIVE_TASK_STATES | {"handed-off", "complete", "cancelled"}
V2_INDEX_REL = "project/context/task-ledger/index.json"
V2_SEGMENTS_REL = "project/context/task-ledger/segments"
V2_RECORD_LIMIT = 256
V2_BYTE_LIMIT = 65536
MIGRATION_MAX_SEGMENTS = 3
CLAIM_CHECKPOINT_PATHS = {
    ".agents/project/context/active-tasks.json",
    ".agents/project/context/context-manifest.json",
    ".agents/skills/project-memory/SKILL.md",
}


def _engine() -> Any:
    import agent_os_context_memory as engine

    return engine


def valid_task_scope(value: str, *, allow_legacy: bool = False) -> bool:
    """Validate a canonical repository scope expression without treating it as a file."""
    if allow_legacy and any(
        value.startswith(prefix) and len(value) > len(prefix)
        for prefix in LEGACY_OPAQUE_TASK_SCOPE_PREFIXES
    ):
        return not any(ord(character) < 32 for character in value)
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        return False
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    concrete_parts: list[str] = []
    for index, part in enumerate(parts):
        if "*" in part:
            if part == "**" and index == len(parts) - 1:
                concrete_parts.append("scope")
                continue
            if not allow_legacy or "**" in part:
                return False
        if any(character in part for character in "?[]"):
            return False
        concrete_parts.append(part.replace("*", "scope"))
    try:
        portable_relative("/".join(concrete_parts), canonical=True)
    except ValueError:
        return False
    return True


def normalized_scope(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if normalized.endswith("/**"):
        normalized = normalized[:-3].rstrip("/")
    return normalized.rstrip("/")


def scopes_overlap(left: list[str], right: list[str]) -> bool:
    for first in left:
        for second in right:
            a = normalized_scope(str(first))
            b = normalized_scope(str(second))
            if not a or not b or a == "." or b == ".":
                return True
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                return True
    return False


def _claim_checkpoint_is_current(
    service: Any,
    ledger: dict[str, Any],
    task: dict[str, Any],
    head: str,
) -> bool:
    """Admit only the exact Git edge that durably records this task claim."""
    engine = _engine()
    base = task.get("base_commit")
    if not isinstance(base, str) or engine.FULL_COMMIT.fullmatch(base) is None:
        return False
    parents = service.git("rev-list", "--parents", "-n", "1", head)
    if not isinstance(parents, str) or parents.split() != [head, base]:
        return False
    changed = service.git("diff-tree", "--no-commit-id", "--name-only", "-r", head)
    if not isinstance(changed, str) or set(changed.splitlines()) != CLAIM_CHECKPOINT_PATHS:
        return False
    if any(not service.git_path_is_clean(path) for path in CLAIM_CHECKPOINT_PATHS):
        return False
    ledger_path = ".agents/project/context/active-tasks.json"
    current_ledger = service.git_blob_bytes(head, ledger_path)
    parent_ledger = service.git_blob_bytes(base, ledger_path)
    if current_ledger != engine.json_bytes(ledger) or parent_ledger is None:
        return False
    try:
        predecessor = json.loads(parent_ledger.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(predecessor, dict):
        return False
    predecessor_tasks = predecessor.get("tasks")
    if not isinstance(predecessor_tasks, list):
        return False
    if {key: value for key, value in ledger.items() if key != "tasks"} != {
        key: value for key, value in predecessor.items() if key != "tasks"
    }:
        return False
    if ledger.get("tasks") != [*predecessor_tasks, task]:
        return False
    if (
        task.get("status") != "active"
        or task.get("claimed_at") != task.get("updated_at")
        or any(item.get("id") == task.get("id") for item in predecessor_tasks if isinstance(item, dict))
    ):
        return False
    manifest_content = service.git_blob_bytes(
        head, ".agents/project/context/context-manifest.json"
    )
    projection_content = service.git_blob_bytes(
        head, ".agents/skills/project-memory/SKILL.md"
    )
    try:
        manifest = json.loads((manifest_content or b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(manifest, dict)
        or manifest.get("refreshed_commit") != base
        or manifest.get("active_task_ledger_sha256") != engine.sha256_bytes(current_ledger)
        or type(manifest.get("budgets", {}).get("projection_max_bytes")) is not int
    ):
        return False
    try:
        expected_projection = service.render_projection(
            str(ledger.get("project_id", "")),
            service.current_stores(),
            ledger,
            manifest["budgets"]["projection_max_bytes"],
        )
    except (TypeError, ValueError):
        return False
    return projection_content == expected_projection


def claim_checkpoint_is_current(
    service: Any,
    ledger: dict[str, Any],
    task: dict[str, Any],
    head: str,
) -> bool:
    try:
        return _claim_checkpoint_is_current(service, ledger, task, head)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _v2_index(service: Any, ledger: dict[str, Any], project_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    engine = _engine()
    errors: list[dict[str, Any]] = []
    if set(ledger) != {"schema_version", "project_id", "tasks", "index"}:
        return None, [{"code": "TASK_LEDGER_V2_FIELDS_INVALID"}]
    reference = ledger.get("index")
    if not isinstance(reference, dict) or set(reference) != {"schema_version", "path", "sha256"} or reference.get("schema_version") != 2 or reference.get("path") != "task-ledger/index.json" or not engine.SHA256.fullmatch(str(reference.get("sha256", ""))):
        errors.append({"code": "TASK_LEDGER_V2_INDEX_REFERENCE_INVALID"})
        return None, errors
    content = service.read_bytes(V2_INDEX_REL)
    if content is None:
        return None, [{"code": "TASK_LEDGER_V2_INDEX_MISSING"}]
    if engine.sha256_bytes(content) != reference["sha256"]:
        errors.append({"code": "TASK_LEDGER_V2_INDEX_HASH_MISMATCH"})
    try:
        index = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, [*errors, {"code": "TASK_LEDGER_V2_INDEX_INVALID"}]
    required = {"schema_version", "project_id", "active_facade", "history_policy", "segment_record_limit", "segment_byte_limit", "entries"}
    if not isinstance(index, dict) or set(index) != required or index.get("schema_version") != 2 or index.get("project_id") != project_id or index.get("active_facade") != "active-tasks.json" or index.get("history_policy") != "explicit-only" or index.get("segment_record_limit") != V2_RECORD_LIMIT or index.get("segment_byte_limit") != V2_BYTE_LIMIT:
        errors.append({"code": "TASK_LEDGER_V2_INDEX_FIELDS_INVALID"})
        return None, errors
    entries = index.get("entries")
    if not isinstance(entries, list) or len(entries) > 4096:
        return None, [*errors, {"code": "TASK_LEDGER_V2_INDEX_ENTRIES_INVALID"}]
    seen: set[str] = set()
    sequences: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"segment_id", "sequence", "record_count", "byte_count", "sha256", "project_id", "predecessor", "successor"}:
            errors.append({"code": "TASK_LEDGER_V2_INDEX_ENTRY_INVALID"})
            continue
        segment_id = entry.get("segment_id")
        sequence = entry.get("sequence")
        if not isinstance(segment_id, str) or SAFE_ID.fullmatch(segment_id) is None or segment_id in seen or type(sequence) is not int or sequence < 0 or sequence in sequences or entry.get("project_id") != project_id or type(entry.get("record_count")) is not int or not 0 <= entry["record_count"] <= V2_RECORD_LIMIT or type(entry.get("byte_count")) is not int or not 0 <= entry["byte_count"] <= V2_BYTE_LIMIT or not engine.SHA256.fullmatch(str(entry.get("sha256", ""))) or (entry.get("predecessor") is not None and not isinstance(entry.get("predecessor"), str)) or (entry.get("successor") is not None and not isinstance(entry.get("successor"), str)):
            errors.append({"code": "TASK_LEDGER_V2_INDEX_ENTRY_INVALID", "segment_id": segment_id})
        seen.add(str(segment_id))
        if type(sequence) is int:
            sequences.add(sequence)
    for position, entry in enumerate(entries):
        expected_predecessor = entries[position - 1].get("segment_id") if position else None
        expected_successor = entries[position + 1].get("segment_id") if position + 1 < len(entries) else None
        if entry.get("sequence") != position or entry.get("predecessor") != expected_predecessor or entry.get("successor") != expected_successor:
            errors.append({"code": "TASK_LEDGER_V2_ROLLOVER_INVALID", "segment_id": entry.get("segment_id")})
    return index, errors


def _v2_history(service: Any, index: dict[str, Any], project_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for entry in index.get("entries", []):
        segment_id = entry["segment_id"]
        relative = f"{V2_SEGMENTS_REL}/{segment_id}.json"
        content = service.read_bytes(relative)
        if content is None:
            errors.append({"code": "TASK_LEDGER_V2_SEGMENT_MISSING", "segment_id": segment_id})
            continue
        engine = _engine()
        if engine.sha256_bytes(content) != entry["sha256"] or len(content) != entry["byte_count"]:
            errors.append({"code": "TASK_LEDGER_V2_SEGMENT_HASH_OR_SIZE_MISMATCH", "segment_id": segment_id})
            continue
        try:
            segment = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append({"code": "TASK_LEDGER_V2_SEGMENT_INVALID", "segment_id": segment_id})
            continue
        if not isinstance(segment, dict) or set(segment) != {"schema_version", "project_id", "segment_id", "sequence", "records", "predecessor", "successor"} or segment.get("schema_version") != 2 or segment.get("project_id") != project_id or segment.get("segment_id") != segment_id or segment.get("sequence") != entry["sequence"] or not isinstance(segment.get("records"), list) or len(segment["records"]) != entry["record_count"]:
            errors.append({"code": "TASK_LEDGER_V2_SEGMENT_FIELDS_INVALID", "segment_id": segment_id})
            continue
        for item in segment["records"]:
            identifier = item.get("id") if isinstance(item, dict) else None
            if not isinstance(identifier, str) or identifier in identifiers:
                errors.append({"code": "TASK_LEDGER_V2_HISTORY_DUPLICATE_OR_INVALID_ID", "id": identifier})
                continue
            identifiers.add(identifier)
            records.append(item)
    return records, errors


def build_v2_terminal_append(service: Any, ledger: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Build one new immutable terminal segment; never rewrites an old segment."""
    project_id = str(service.binding().get("project_id", ""))
    index, errors = _v2_index(service, ledger, project_id)
    if errors or index is None:
        return {"ok": False, "reason_codes": [item["code"] for item in errors] or ["TASK_LEDGER_V2_INDEX_INVALID"]}
    history, history_errors = _v2_history(service, index, project_id)
    if history_errors:
        return {"ok": False, "reason_codes": [item["code"] for item in history_errors]}
    if any(item.get("id") == task.get("id") for item in history):
        return {"ok": False, "reason_codes": ["TASK_LEDGER_V2_TERMINAL_DUPLICATE"]}
    entries = index["entries"]
    sequence = max((item["sequence"] for item in entries), default=-1) + 1
    predecessor = max(entries, key=lambda item: item["sequence"])["segment_id"] if entries else None
    segment_id = f"segment-{sequence:08d}"
    segment = {"schema_version": 2, "project_id": project_id, "segment_id": segment_id, "sequence": sequence, "records": [task], "predecessor": predecessor, "successor": None}
    segment_bytes = _engine().json_bytes(segment)
    if len(segment_bytes) > V2_BYTE_LIMIT or len(entries) >= 4096:
        return {"ok": False, "reason_codes": ["TASK_LEDGER_V2_SEGMENT_LIMIT"]}
    if entries:
        entries[-1]["successor"] = segment_id
    entry = {"segment_id": segment_id, "sequence": sequence, "record_count": 1, "byte_count": len(segment_bytes), "sha256": _engine().sha256_bytes(segment_bytes), "project_id": project_id, "predecessor": predecessor, "successor": None}
    index["entries"] = [*entries, entry]
    index_bytes = _engine().json_bytes(index)
    return {"ok": True, "index_bytes": index_bytes, "segment_bytes": segment_bytes, "segment_path": f"{V2_SEGMENTS_REL}/{segment_id}.json", "segment_id": segment_id, "index_sha256": _engine().sha256_bytes(index_bytes)}


def v2_history(service: Any, ledger: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return validated immutable v2 history without exposing partial results."""
    if ledger.get("schema_version") != 2:
        return [], []
    project_id = str(service.binding().get("project_id", ""))
    index, errors = _v2_index(service, ledger, project_id)
    if errors or index is None:
        return [], errors or [{"code": "TASK_LEDGER_V2_INDEX_INVALID"}]
    history, history_errors = _v2_history(service, index, project_id)
    return (history, []) if not history_errors else ([], history_errors)


def _migration_bundle(service: Any, ledger: Any) -> dict[str, Any]:
    """Build a deterministic v2 facade/index/segment bundle from a valid v1 ledger."""
    engine = _engine()
    project_id = str(service.binding().get("project_id", ""))
    errors, stale, conflicts = validate_tasks(service, ledger, project_id)
    if errors or conflicts or not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
        return {"ok": False, "reason_codes": ["TASK_LEDGER_MIGRATION_SOURCE_INVALID"], "errors": errors, "stale": stale, "conflicts": conflicts}
    tasks = ledger["tasks"]
    active = [deepcopy(item) for item in tasks if item["status"] in ACTIVE_TASK_STATES]
    terminal = [deepcopy(item) for item in tasks if item["status"] not in ACTIVE_TASK_STATES]
    segments: list[tuple[str, bytes]] = []
    entries: list[dict[str, Any]] = []
    offset = 0
    while offset < len(terminal):
        sequence = len(segments)
        if sequence >= MIGRATION_MAX_SEGMENTS:
            return {"ok": False, "reason_codes": ["TASK_LEDGER_MIGRATION_CAPACITY_EXCEEDED"]}
        segment_id = f"segment-{sequence:08d}"
        predecessor = f"segment-{sequence - 1:08d}" if sequence else None
        records: list[dict[str, Any]] = []
        while offset < len(terminal) and len(records) < V2_RECORD_LIMIT:
            candidate = [*records, terminal[offset]]
            successor = f"segment-{sequence + 1:08d}" if offset + 1 < len(terminal) else None
            payload = {"schema_version": 2, "project_id": project_id, "segment_id": segment_id, "sequence": sequence, "records": candidate, "predecessor": predecessor, "successor": successor}
            if len(engine.json_bytes(payload)) > V2_BYTE_LIMIT:
                if not records:
                    return {"ok": False, "reason_codes": ["TASK_LEDGER_MIGRATION_RECORD_TOO_LARGE"]}
                break
            records = candidate
            offset += 1
        successor = f"segment-{sequence + 1:08d}" if offset < len(terminal) else None
        segment = {"schema_version": 2, "project_id": project_id, "segment_id": segment_id, "sequence": sequence, "records": records, "predecessor": predecessor, "successor": successor}
        content = engine.json_bytes(segment)
        path = f"{V2_SEGMENTS_REL}/{segment_id}.json"
        segments.append((path, content))
        entries.append({"segment_id": segment_id, "sequence": sequence, "record_count": len(records), "byte_count": len(content), "sha256": engine.sha256_bytes(content), "project_id": project_id, "predecessor": predecessor, "successor": successor})
    index = {"schema_version": 2, "project_id": project_id, "active_facade": "active-tasks.json", "history_policy": "explicit-only", "segment_record_limit": V2_RECORD_LIMIT, "segment_byte_limit": V2_BYTE_LIMIT, "entries": entries}
    index_bytes = engine.json_bytes(index)
    facade = {"schema_version": 2, "project_id": project_id, "tasks": active, "index": {"schema_version": 2, "path": "task-ledger/index.json", "sha256": engine.sha256_bytes(index_bytes)}}
    return {"ok": True, "facade": facade, "index_bytes": index_bytes, "segments": segments}


def _transition_metadata(source: bytes, target: bytes, index: bytes, segments: list[tuple[str, bytes]], rollback_result: str, source_plan_id: str | None = None) -> dict[str, Any]:
    engine = _engine()
    metadata: dict[str, Any] = {
        "source_ledger_sha256": engine.sha256_bytes(source),
        "target_ledger_sha256": engine.sha256_bytes(target),
        "index_sha256": engine.sha256_bytes(index),
        "segments": [{"path": path, "sha256": engine.sha256_bytes(content), "byte_count": len(content)} for path, content in segments],
        "rollback_result": rollback_result,
    }
    if source_plan_id is not None:
        metadata["source_plan_id"] = source_plan_id
    return metadata


def plan_migrate(service: Any) -> dict[str, Any]:
    engine = _engine()
    source = service.read_bytes(engine.TASKS_REL)
    if source is None:
        return {"ok": False, "reason_codes": ["TASK_LEDGER_MIGRATION_SOURCE_MISSING"]}
    bundle = _migration_bundle(service, service.document(engine.TASKS_REL, {}))
    if not bundle.get("ok"):
        return bundle
    target = engine.json_bytes(bundle["facade"])
    segments = bundle["segments"]
    extra = {V2_INDEX_REL: bundle["index_bytes"], **dict(segments)}
    desired = service.desired_with_manifest(service.current_stores(), bundle["facade"], service.document(engine.MANIFEST_REL, {}), extra)
    metadata = _transition_metadata(source, target, bundle["index_bytes"], segments, "not-required")
    return service.create_plan("migrate-task-ledger", desired, metadata)


def plan_rollback(service: Any, source_plan_id: str) -> dict[str, Any]:
    engine = _engine()
    if not isinstance(source_plan_id, str) or engine.PLAN_ID.fullmatch(source_plan_id) is None:
        return {"ok": False, "reason_codes": ["TASK_LEDGER_ROLLBACK_PLAN_INVALID"]}
    plan = engine.load_json(service.plans / f"{source_plan_id}.json", None)
    if not isinstance(plan, dict) or plan.get("operation") != "migrate-task-ledger" or plan.get("status") != "applied" or plan.get("project_id") != service.binding().get("project_id") or plan.get("content_sha256") != engine.receipt_hash(plan):
        return {"ok": False, "reason_codes": ["TASK_LEDGER_ROLLBACK_PLAN_INVALID"]}
    pending = deepcopy(plan)
    pending["status"] = "pending-approval"
    pending["content_sha256"] = engine.receipt_hash(pending)
    if service.validate_plan(pending, source_plan_id) or not service.verify_changes(plan["changes"], after=True):
        return {"ok": False, "reason_codes": ["TASK_LEDGER_ROLLBACK_TARGET_DIVERGED"]}
    desired = {item["path"]: engine.decoded(item["before_base64"]) for item in plan["changes"]}
    metadata = {**plan["metadata"], "rollback_result": "byte-exact-restored", "source_plan_id": source_plan_id}
    return service.create_plan("rollback-task-ledger", desired, metadata)


def validate_transition_metadata(operation: str, metadata: Any, change_paths: set[str]) -> list[str]:
    engine = _engine()
    required = {"source_ledger_sha256", "target_ledger_sha256", "index_sha256", "segments", "rollback_result"}
    if operation == "rollback-task-ledger":
        required.add("source_plan_id")
    if not isinstance(metadata, dict) or set(metadata) != required:
        return ["CONTEXT_PLAN_METADATA_INVALID"]
    hashes = (metadata.get("source_ledger_sha256"), metadata.get("target_ledger_sha256"), metadata.get("index_sha256"))
    segments = metadata.get("segments")
    expected_result = "byte-exact-restored" if operation == "rollback-task-ledger" else "not-required"
    if not all(isinstance(item, str) and engine.SHA256.fullmatch(item) for item in hashes) or hashes[0] == hashes[1] or not isinstance(segments, list) or len(segments) > MIGRATION_MAX_SEGMENTS or metadata.get("rollback_result") != expected_result:
        return ["CONTEXT_PLAN_METADATA_INVALID"]
    if operation == "rollback-task-ledger" and (not isinstance(metadata.get("source_plan_id"), str) or engine.PLAN_ID.fullmatch(metadata["source_plan_id"]) is None):
        return ["CONTEXT_PLAN_METADATA_INVALID"]
    segment_paths: set[str] = set()
    for sequence, item in enumerate(segments):
        path = f"{V2_SEGMENTS_REL}/segment-{sequence:08d}.json"
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "byte_count"} or item.get("path") != path or not isinstance(item.get("sha256"), str) or engine.SHA256.fullmatch(item["sha256"]) is None or type(item.get("byte_count")) is not int or not 1 <= item["byte_count"] <= V2_BYTE_LIMIT:
            return ["CONTEXT_PLAN_METADATA_INVALID"]
        segment_paths.add(path)
    required_paths = {engine.TASKS_REL, engine.MANIFEST_REL, V2_INDEX_REL, *segment_paths}
    allowed_paths = {engine.PROJECTION_REL, *required_paths}
    return [] if required_paths <= change_paths <= allowed_paths else ["CONTEXT_PLAN_METADATA_INVALID"]


def validate_tasks(
    service: Any,
    ledger: Any,
    project_id: str,
    *,
    checkpoint_ledger: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    engine = _engine()
    if isinstance(ledger, dict) and ledger.get("schema_version") == 2:
        index, index_errors = _v2_index(service, ledger, project_id)
        if set(ledger) != {"schema_version", "project_id", "tasks", "index"}:
            return [{"code": "TASK_LEDGER_V2_FIELDS_INVALID"}], [], []
        normalized = {"schema_version": 1, "project_id": ledger.get("project_id"), "tasks": ledger.get("tasks")}
        errors, stale, conflicts = validate_tasks(
            service,
            normalized,
            project_id,
            checkpoint_ledger=ledger,
        )
        errors.extend(index_errors)
        errors.extend({"code": "TASK_LEDGER_V2_ACTIVE_STATUS_INVALID", "id": item.get("id")} for item in ledger.get("tasks", []) if isinstance(item, dict) and item.get("status") not in ACTIVE_TASK_STATES)
        return errors, stale, conflicts
    errors: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    if not isinstance(ledger, dict) or set(ledger) != {"schema_version", "project_id", "tasks"}:
        return [{"code": "TASK_LEDGER_FIELDS_INVALID"}], stale, conflicts
    ledger_project_id = ledger.get("project_id")
    raw_tasks = ledger.get("tasks")
    if (
        type(ledger.get("schema_version")) is not int
        or ledger.get("schema_version") != 1
        or not isinstance(ledger_project_id, str)
        or not 1 <= len(ledger_project_id) <= 128
        or not isinstance(raw_tasks, list)
    ):
        errors.append({"code": "TASK_LEDGER_FIELDS_INVALID"})
    if engine.has_forbidden_payload(ledger):
        errors.append({"code": "TASK_LEDGER_FORBIDDEN_PAYLOAD"})
    if isinstance(ledger_project_id, str) and ledger_project_id != project_id:
        errors.append({"code": "TASK_LEDGER_PROJECT_CONTAMINATION"})
    if not isinstance(raw_tasks, list):
        return errors, stale, conflicts
    identifiers: set[str] = set()
    head = service.head()
    active: list[dict[str, Any]] = []
    required = {"id", "title", "owner", "scope", "base_commit", "status", "claimed_at", "updated_at", "evidence"}
    for task in raw_tasks:
        if not isinstance(task, dict) or set(task) != required:
            errors.append({"code": "TASK_FIELDS_INVALID"})
            continue
        identifier_value = task.get("id")
        identifier = identifier_value if isinstance(identifier_value, str) else ""
        if not SAFE_ID.fullmatch(identifier) or identifier in identifiers:
            errors.append({"code": "TASK_ID_INVALID_OR_DUPLICATED", "id": identifier})
        identifiers.add(identifier)
        if engine.has_forbidden_payload(task):
            errors.append({"code": "TASK_FORBIDDEN_PAYLOAD", "id": identifier})
        if not isinstance(task.get("title"), str) or not 3 <= len(task["title"]) <= 240:
            errors.append({"code": "TASK_TITLE_INVALID", "id": identifier})
        if not isinstance(task.get("owner"), str) or not 1 <= len(task["owner"]) <= 128:
            errors.append({"code": "TASK_OWNER_INVALID", "id": identifier})
        scope = task.get("scope")
        scope_valid = engine.valid_string_list(scope, 1, 64)
        if not scope_valid:
            errors.append({"code": "TASK_SCOPE_INVALID", "id": identifier})
        else:
            for item in scope:
                if not valid_task_scope(item, allow_legacy=task.get("status") not in ACTIVE_TASK_STATES):
                    errors.append({"code": "TASK_SCOPE_UNSAFE", "id": identifier, "scope": item})
        base_commit = task.get("base_commit")
        if not isinstance(base_commit, str) or engine.FULL_COMMIT.fullmatch(base_commit) is None:
            errors.append({"code": "TASK_BASE_COMMIT_INVALID", "id": identifier})
        elif (
            task.get("status") in ACTIVE_TASK_STATES
            and head
            and task.get("base_commit") != head
            and not claim_checkpoint_is_current(
                service,
                checkpoint_ledger if checkpoint_ledger is not None else ledger,
                task,
                head,
            )
        ):
            stale.append({"code": "TASK_BASE_COMMIT_STALE", "id": identifier, "base_commit": task.get("base_commit"), "current_head": head})
        if task.get("status") not in TASK_STATES:
            errors.append({"code": "TASK_STATUS_INVALID", "id": identifier})
        for field in ("claimed_at", "updated_at"):
            if not engine.valid_date_time(task.get(field)):
                errors.append({"code": "TASK_TIMESTAMP_INVALID", "id": identifier, "field": field})
        if not engine.valid_string_list(task.get("evidence"), 0, 64):
            errors.append({"code": "TASK_EVIDENCE_INVALID", "id": identifier})
        if task.get("status") in ACTIVE_TASK_STATES and scope_valid:
            active.append(task)
    for index, first in enumerate(active):
        for second in active[index + 1 :]:
            if scopes_overlap(first.get("scope", []), second.get("scope", [])):
                conflicts.append({"code": "TASK_SCOPE_CONFLICT", "tasks": [first.get("id"), second.get("id")]})
    return errors, stale, conflicts


def plan_claim_task(service: Any, proposal: Any) -> dict[str, Any]:
    engine = _engine()
    health = service.doctor()
    if health.get("state") in {"UNCONFIGURED", "DEGRADED"}:
        return {"ok": False, "reason_codes": ["CONTEXT_NOT_MUTABLE"], "health": health}
    allowed = {"id", "title", "owner", "scope", "evidence"}
    if not isinstance(proposal, dict) or set(proposal) != allowed or engine.has_forbidden_payload(proposal):
        return {"ok": False, "reason_codes": ["TASK_PROPOSAL_INVALID"]}
    identifier, title, owner = proposal.get("id"), proposal.get("title"), proposal.get("owner")
    scope, evidence = proposal.get("scope"), proposal.get("evidence")
    if (
        not isinstance(identifier, str) or SAFE_ID.fullmatch(identifier) is None
        or not isinstance(title, str) or not 3 <= len(title) <= 240
        or not isinstance(owner, str) or not 1 <= len(owner) <= 128
        or not engine.valid_string_list(scope, 1, 64) or not engine.valid_string_list(evidence, 0, 64)
    ):
        return {"ok": False, "reason_codes": ["TASK_PROPOSAL_INVALID"]}
    for item in scope:
        if not valid_task_scope(item):
            return {"ok": False, "reason_codes": ["TASK_SCOPE_UNSAFE"], "scope": item}
    ledger = deepcopy(service.document(engine.TASKS_REL, {}))
    tasks = ledger.get("tasks") if isinstance(ledger.get("tasks"), list) else []
    if any(item.get("id") == identifier for item in tasks if isinstance(item, dict)):
        return {"ok": False, "reason_codes": ["TASK_ALREADY_EXISTS"]}
    history, history_errors = v2_history(service, ledger)
    if history_errors:
        return {
            "ok": False,
            "reason_codes": ["TASK_CLAIM_HISTORY_INVALID"],
            "errors": history_errors,
        }
    if any(item.get("id") == identifier for item in history):
        return {"ok": False, "reason_codes": ["TASK_TERMINAL_ID_REUSE"]}
    for task in tasks:
        if task.get("status") in ACTIVE_TASK_STATES and scopes_overlap(scope, task.get("scope", [])):
            return {"ok": False, "reason_codes": ["TASK_SCOPE_CONFLICT"], "conflicting_task": task.get("id")}
    timestamp = engine.iso_time(service.now())
    task = {"id": identifier, "title": title, "owner": owner, "scope": scope, "base_commit": service.head(), "status": "active", "claimed_at": timestamp, "updated_at": timestamp, "evidence": evidence}
    ledger["tasks"] = [*tasks, task]
    desired = service.desired_with_manifest(service.current_stores(), ledger, service.document(engine.MANIFEST_REL, {}))
    return service.create_plan("claim-task", desired, {"task_id": identifier, "owner": task["owner"]})


def plan_rekey_task(service: Any, proposal: Any) -> dict[str, Any]:
    """Recover one active v2 task whose ID already exists in immutable history."""
    engine = _engine()
    allowed = {"task_id", "replacement_id", "owner", "replacement_owner"}
    if not isinstance(proposal, dict) or set(proposal) != allowed or engine.has_forbidden_payload(proposal):
        return {"ok": False, "reason_codes": ["TASK_REKEY_PROPOSAL_INVALID"]}
    task_id = proposal.get("task_id")
    replacement_id = proposal.get("replacement_id")
    owner = proposal.get("owner")
    replacement_owner = proposal.get("replacement_owner")
    if (
        not isinstance(task_id, str)
        or SAFE_ID.fullmatch(task_id) is None
        or not isinstance(replacement_id, str)
        or SAFE_ID.fullmatch(replacement_id) is None
        or replacement_id == task_id
        or not isinstance(owner, str)
        or not 1 <= len(owner) <= 128
        or not isinstance(replacement_owner, str)
        or not 1 <= len(replacement_owner) <= 128
    ):
        return {"ok": False, "reason_codes": ["TASK_REKEY_PROPOSAL_INVALID"]}
    ledger = deepcopy(service.document(engine.TASKS_REL, {}))
    if ledger.get("schema_version") != 2:
        return {"ok": False, "reason_codes": ["TASK_REKEY_REQUIRES_V2"]}
    tasks = ledger.get("tasks") if isinstance(ledger.get("tasks"), list) else []
    task = next((item for item in tasks if isinstance(item, dict) and item.get("id") == task_id), None)
    if not isinstance(task, dict) or task.get("status") not in ACTIVE_TASK_STATES:
        return {"ok": False, "reason_codes": ["TASK_REKEY_NOT_ACTIVE"]}
    if task.get("owner") != owner:
        return {"ok": False, "reason_codes": ["TASK_REKEY_OWNER_MISMATCH"]}
    base = task.get("base_commit")
    head = service.head()
    if (
        not isinstance(base, str)
        or not isinstance(head, str)
        or not service.commit_exists(base)
        or not service.commit_is_ancestor(base)
    ):
        return {
            "ok": False,
            "reason_codes": ["TASK_REKEY_BASE_DIVERGED"],
            "base_commit": base,
            "current_head": head,
        }
    history, history_errors = v2_history(service, ledger)
    if history_errors:
        return {"ok": False, "reason_codes": ["TASK_REKEY_HISTORY_INVALID"], "errors": history_errors}
    history_ids = {item.get("id") for item in history}
    if task_id not in history_ids:
        return {"ok": False, "reason_codes": ["TASK_REKEY_SOURCE_NOT_TERMINAL_DUPLICATE"]}
    if replacement_id in history_ids or any(item.get("id") == replacement_id for item in tasks if isinstance(item, dict)):
        return {"ok": False, "reason_codes": ["TASK_REKEY_TARGET_EXISTS"]}
    task["id"] = replacement_id
    task["owner"] = replacement_owner
    task["base_commit"] = head
    task["updated_at"] = engine.iso_time(service.now())
    desired = service.desired_with_manifest(
        service.current_stores(), ledger, service.document(engine.MANIFEST_REL, {})
    )
    return service.create_plan(
        "rekey-task",
        desired,
        {
            "task_id": task_id,
            "replacement_id": replacement_id,
            "owner": owner,
            "replacement_owner": replacement_owner,
            "previous_base_commit": base,
            "continued_base_commit": head,
        },
    )


def plan_continue_task(service: Any, proposal: Any) -> dict[str, Any]:
    engine = _engine()
    allowed = {"task_id", "owner", "evidence"}
    if not isinstance(proposal, dict) or set(proposal) != allowed or engine.has_forbidden_payload(proposal):
        return {"ok": False, "reason_codes": ["TASK_CONTINUATION_PROPOSAL_INVALID"]}
    task_id, owner, evidence = proposal.get("task_id"), proposal.get("owner"), proposal.get("evidence")
    if (
        not isinstance(task_id, str) or SAFE_ID.fullmatch(task_id) is None
        or not isinstance(owner, str) or not 1 <= len(owner) <= 128
        or not engine.valid_string_list(evidence, 0, 64)
    ):
        return {"ok": False, "reason_codes": ["TASK_CONTINUATION_PROPOSAL_INVALID"]}
    ledger = deepcopy(service.document(engine.TASKS_REL, {}))
    project_id = str(service.binding().get("project_id", ""))
    task_errors, task_stale, task_conflicts = validate_tasks(service, ledger, project_id)
    non_base_errors = [item for item in task_errors if item.get("code") != "TASK_BASE_COMMIT_STALE"]
    tasks_by_id = {
        item.get("id"): item
        for item in ledger.get("tasks", [])
        if isinstance(item, dict)
    }
    unrelated_stale = []
    for item in task_stale:
        sibling = tasks_by_id.get(item.get("id"))
        sibling_base = sibling.get("base_commit") if isinstance(sibling, dict) else None
        same_owner_ancestor = bool(
            isinstance(sibling, dict)
            and sibling.get("owner") == owner
            and isinstance(sibling_base, str)
            and service.commit_exists(sibling_base)
            and service.commit_is_ancestor(sibling_base)
        )
        if item.get("id") != task_id and not same_owner_ancestor:
            unrelated_stale.append(item)
    if non_base_errors or unrelated_stale or task_conflicts:
        return {"ok": False, "reason_codes": ["TASK_CONTINUATION_LEDGER_INVALID"], "errors": [*non_base_errors, *unrelated_stale], "conflicts": task_conflicts}
    task = next((item for item in ledger.get("tasks", []) if isinstance(item, dict) and item.get("id") == task_id), None)
    if not isinstance(task, dict) or task.get("status") not in ACTIVE_TASK_STATES:
        return {"ok": False, "reason_codes": ["TASK_CONTINUATION_NOT_ACTIVE"]}
    if task.get("owner") != owner:
        return {"ok": False, "reason_codes": ["TASK_CONTINUATION_OWNER_MISMATCH"]}
    head, base = service.head(), task.get("base_commit")
    if not head:
        return {"ok": False, "reason_codes": ["GIT_HEAD_UNAVAILABLE"]}
    if not isinstance(base, str) or not service.commit_exists(base) or not service.commit_is_ancestor(base):
        return {"ok": False, "reason_codes": ["TASK_CONTINUATION_BASE_DIVERGED"], "base_commit": base, "current_head": head}
    for relative in evidence:
        _ref, errors = service.committed_evidence_ref(relative)
        if errors:
            return {"ok": False, "reason_codes": ["TASK_CONTINUATION_EVIDENCE_INVALID"], "errors": errors}
    task["base_commit"] = head
    task["updated_at"] = engine.iso_time(service.now())
    task["evidence"] = list(dict.fromkeys([*task.get("evidence", []), *evidence]))
    desired = service.desired_with_manifest(service.current_stores(), ledger, service.document(engine.MANIFEST_REL, {}))
    return service.create_plan("continue-task", desired, {"task_id": task_id, "owner": owner, "previous_base_commit": base, "continued_base_commit": head})


def plan_handoff(service: Any, proposal: Any) -> dict[str, Any]:
    engine = _engine()
    allowed = {"task_id", "from_owner", "to_owner", "verified_outcomes", "unresolved_risks", "next_action", "evidence"}
    if not isinstance(proposal, dict) or set(proposal) != allowed or engine.has_forbidden_payload(proposal):
        return {"ok": False, "reason_codes": ["HANDOFF_PROPOSAL_INVALID"]}
    ledger = deepcopy(service.document(engine.TASKS_REL, {}))
    task = next((item for item in ledger.get("tasks", []) if item.get("id") == proposal.get("task_id")), None)
    if not isinstance(task, dict) or task.get("status") not in ACTIVE_TASK_STATES:
        return {"ok": False, "reason_codes": ["HANDOFF_TASK_NOT_ACTIVE"]}
    if task.get("owner") != proposal.get("from_owner"):
        return {"ok": False, "reason_codes": ["HANDOFF_OWNER_MISMATCH"]}
    if proposal.get("to_owner") == task.get("owner"):
        return {"ok": False, "reason_codes": ["HANDOFF_OWNER_UNCHANGED"]}
    if task.get("base_commit") != service.head():
        return {"ok": False, "reason_codes": ["TASK_BASE_COMMIT_STALE"], "base_commit": task.get("base_commit"), "current_head": service.head()}
    outcomes = proposal.get("verified_outcomes") if isinstance(proposal.get("verified_outcomes"), list) else []
    risks = proposal.get("unresolved_risks") if isinstance(proposal.get("unresolved_risks"), list) else []
    if not outcomes or not isinstance(proposal.get("next_action"), str) or len(proposal["next_action"]) < 3:
        return {"ok": False, "reason_codes": ["HANDOFF_EVIDENCE_OR_NEXT_ACTION_REQUIRED"]}
    refs, errors = service.evidence_refs(proposal.get("evidence"))
    if errors:
        return {"ok": False, "reason_codes": ["HANDOFF_EVIDENCE_INVALID"], "errors": errors}
    created = engine.iso_time(service.now())
    seed = {"task": task["id"], "from": task["owner"], "to": proposal.get("to_owner"), "at": created, "head": service.head()}
    receipt = {"schema_version": 2, "id": f"handoff-{engine.canonical_hash(seed)[:24]}", "project_id": service.binding().get("project_id"), "task_id": task["id"], "from_owner": task["owner"], "to_owner": proposal.get("to_owner"), "base_commit": service.head(), "created_at": created, "verified_outcomes": [str(item) for item in outcomes], "unresolved_risks": [str(item) for item in risks], "next_action": proposal["next_action"], "evidence": [{"path": item["path"], "sha256": item["sha256"], "git_commit": item["git_commit"]} for item in refs]}
    receipt["content_sha256"] = engine.receipt_hash(receipt)
    to_owner = proposal.get("to_owner")
    if isinstance(to_owner, str) and to_owner:
        task["owner"], task["base_commit"], task["status"] = to_owner, service.head(), "active"
    else:
        task["status"] = "handed-off"
    task["updated_at"] = created
    handoff_relative = f"{engine.HANDOFF_DIR_REL}/{receipt['id']}.json"
    extra = {handoff_relative: engine.json_bytes(receipt)}
    metadata = {"task_id": task["id"], "handoff_id": receipt["id"]}
    if ledger.get("schema_version") == 2 and not (isinstance(to_owner, str) and to_owner):
        terminal = build_v2_terminal_append(service, ledger, task)
        if not terminal.get("ok"):
            return terminal
        ledger["tasks"] = [item for item in ledger.get("tasks", []) if item.get("id") != task["id"]]
        ledger["index"]["sha256"] = terminal["index_sha256"]
        extra.update({V2_INDEX_REL: terminal["index_bytes"], terminal["segment_path"]: terminal["segment_bytes"]})
        metadata.update({"ledger_mode": "v2-terminal-segment", "segment_id": terminal["segment_id"], "segment_path": terminal["segment_path"], "index_path": V2_INDEX_REL})
    desired = service.desired_with_manifest(service.current_stores(), ledger, service.document(engine.MANIFEST_REL, {}), extra)
    return service.create_plan("handoff", desired, metadata)


def list_tasks(service: Any) -> dict[str, Any]:
    engine = _engine()
    health = service.doctor()
    ledger = service.document(engine.TASKS_REL, {"tasks": []})
    return {"ok": health.get("state") not in {"UNCONFIGURED", "DEGRADED"}, "health": health, "tasks": ledger.get("tasks", [])}
