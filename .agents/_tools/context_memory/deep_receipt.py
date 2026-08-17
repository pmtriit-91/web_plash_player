"""Bounded, fail-closed contract for cached deep-doctor verdicts."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

FIELDS = {
    "schema_version", "project_id", "head", "handoff_tree_sha256",
    "task_ledger_tree_sha256", "created_at", "expires_at", "verdict", "content_sha256",
}
SUMMARY_FIELDS = {
    "receipts", "legacy_receipts", "git_durable_receipts", "evidence_references",
    "recoverable_references", "legacy_recoverable_references", "unrecoverable_references",
}
MAX_TTL_SECONDS = 300
MAX_RECEIPT_BYTES = 1_048_576
MAX_TREE_ENTRIES = 8192
MAX_TREE_BYTES = 16_777_216
CACHE_REL = "project/context/cache/deep-handoff-receipt.json"
TREE_RELS = {
    "handoff_tree_sha256": "project/context/handoffs",
    "task_ledger_tree_sha256": "project/context/task-ledger",
}


def _engine() -> Any:
    import agent_os_context_memory as engine

    return engine


def _time(value: Any) -> datetime | None:
    engine = _engine()
    if not engine.valid_date_time(value):
        return None
    try:
        return engine.parse_time(str(value).replace("z", "Z"))
    except ValueError:
        return None


def _valid_verdict(value: Any) -> bool:
    engine = _engine()
    if not isinstance(value, dict) or set(value) != {"errors", "warnings", "summary"}:
        return False
    errors, warnings, summary = value["errors"], value["warnings"], value["summary"]
    return (
        isinstance(errors, list) and len(errors) <= 4096
        and isinstance(warnings, list) and len(warnings) <= 4096
        and all(isinstance(item, dict) for item in [*errors, *warnings])
        and isinstance(summary, dict) and set(summary) == SUMMARY_FIELDS
        and all(type(summary[field]) is int and summary[field] >= 0 for field in SUMMARY_FIELDS)
        and not engine.has_forbidden_payload(value)
    )


def build_receipt(
    *, project_id: str, head: str, handoff_tree_sha256: str,
    task_ledger_tree_sha256: str, created_at: str, expires_at: str,
    verdict: dict[str, Any],
) -> dict[str, Any]:
    """Build an immutable receipt; runtime persistence belongs to BR3d1."""
    engine = _engine()
    created, expires = _time(created_at), _time(expires_at)
    if (
        not 1 <= len(project_id) <= 128 or any(ord(char) < 32 for char in project_id)
        or engine.FULL_COMMIT.fullmatch(head) is None
        or engine.SHA256.fullmatch(handoff_tree_sha256) is None
        or engine.SHA256.fullmatch(task_ledger_tree_sha256) is None
        or created is None or expires is None
        or not 0 < (expires - created).total_seconds() <= MAX_TTL_SECONDS
        or not _valid_verdict(verdict)
    ):
        raise ValueError("invalid deep receipt input")
    receipt = {
        "schema_version": 1, "project_id": project_id, "head": head,
        "handoff_tree_sha256": handoff_tree_sha256,
        "task_ledger_tree_sha256": task_ledger_tree_sha256,
        "created_at": created_at, "expires_at": expires_at, "verdict": deepcopy(verdict),
    }
    receipt["content_sha256"] = engine.receipt_hash(receipt)
    if len(engine.json_bytes(receipt)) > MAX_RECEIPT_BYTES:
        raise ValueError("deep receipt exceeds byte budget")
    return receipt


def validate_receipt(
    value: Any, *, project_id: str, head: str, handoff_tree_sha256: str,
    task_ledger_tree_sha256: str, now: datetime,
) -> dict[str, Any] | None:
    """Return a detached verdict only when every binding remains current."""
    engine = _engine()
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema_version") != 1:
        return None
    created, expires = _time(value.get("created_at")), _time(value.get("expires_at"))
    if (
        not isinstance(project_id, str) or not 1 <= len(project_id) <= 128
        or any(ord(char) < 32 for char in project_id)
        or engine.FULL_COMMIT.fullmatch(head) is None
        or engine.SHA256.fullmatch(handoff_tree_sha256) is None
        or engine.SHA256.fullmatch(task_ledger_tree_sha256) is None
        or value.get("project_id") != project_id or value.get("head") != head
        or value.get("handoff_tree_sha256") != handoff_tree_sha256
        or value.get("task_ledger_tree_sha256") != task_ledger_tree_sha256
        or created is None or expires is None or now.tzinfo is None
        or not created <= now < expires
        or not 0 < (expires - created).total_seconds() <= MAX_TTL_SECONDS
        or not _valid_verdict(value.get("verdict"))
        or value.get("content_sha256") != engine.receipt_hash(value)
        or len(engine.json_bytes(value)) > MAX_RECEIPT_BYTES
    ):
        return None
    return deepcopy(value["verdict"])


def _tree_digest(root: Path) -> str | None:
    """Hash a bounded JSON-only tree; unsafe entries invalidate the cache."""
    engine = _engine()
    if not root.is_dir() or root.is_symlink():
        return None
    entries: list[dict[str, str]] = []
    seen = total_bytes = 0
    try:
        for path in root.rglob("*"):
            seen += 1
            if seen > MAX_TREE_ENTRIES:
                return None
            if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                return None
            if path.is_dir():
                continue
            size = path.stat().st_size
            total_bytes += size
            if (
                path.suffix != ".json" or size > MAX_RECEIPT_BYTES
                or total_bytes > MAX_TREE_BYTES
            ):
                return None
            with path.open("rb") as handle:
                content = handle.read(size + 1)
            if len(content) != size or path.is_symlink():
                return None
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": engine.sha256_bytes(content),
            })
    except (OSError, ValueError):
        return None
    entries.sort(key=lambda item: item["path"])
    return engine.canonical_hash(entries)


def current_bindings(service: Any) -> dict[str, str] | None:
    engine = _engine()
    binding, head = service.binding(), service.head()
    project_id = binding.get("project_id") if isinstance(binding, dict) else None
    if (
        not isinstance(project_id, str) or not 1 <= len(project_id) <= 128
        or any(ord(char) < 32 for char in project_id)
        or not isinstance(head, str) or engine.FULL_COMMIT.fullmatch(head) is None
    ):
        return None
    result = {"project_id": project_id, "head": head}
    for field, relative in TREE_RELS.items():
        digest = _tree_digest(service.path(relative))
        if digest is None:
            return None
        result[field] = digest
    return result


def load_cached(
    service: Any, bindings: dict[str, str], now: datetime,
) -> dict[str, Any] | None:
    path = service.path(CACHE_REL)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
            return None
        with path.open("rb") as handle:
            content = handle.read(MAX_RECEIPT_BYTES + 1)
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return validate_receipt(value, now=now, **bindings)


def write_cached(
    service: Any, bindings: dict[str, str], verdict: dict[str, Any], now: datetime,
) -> bool:
    engine = _engine()
    try:
        receipt = build_receipt(
            **bindings,
            created_at=engine.iso_time(now),
            expires_at=engine.iso_time(now + timedelta(seconds=MAX_TTL_SECONDS)),
            verdict=verdict,
        )
        engine.atomic_bytes(service.path(CACHE_REL), engine.json_bytes(receipt))
    except (OSError, TypeError, ValueError):
        return False
    return True
