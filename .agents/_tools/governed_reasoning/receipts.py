"""Integrity validation for project-owned governed reasoning receipt graphs."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime
from typing import Any

from governed_reasoning.contracts import content_hash, validate_artifact

RECEIPT_KINDS = ("plan", "challenge", "decision")


def _rejected(reasons: Iterable[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "REJECTED",
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def receipt_kind(receipt: Any) -> str | None:
    if not isinstance(receipt, dict):
        return None
    identifier = receipt.get("receipt_id")
    if not isinstance(identifier, str):
        return None
    return next(
        (kind for kind in RECEIPT_KINDS if identifier.startswith(f"{kind}-")),
        None,
    )


def seal_receipt(kind: str, receipt: Any) -> dict[str, Any]:
    """Return a copied receipt with a canonical hash, or reject invalid content."""
    if kind not in RECEIPT_KINDS or not isinstance(receipt, dict):
        return _rejected(["RECEIPT_KIND_INVALID"])
    sealed = deepcopy(receipt)
    sealed.pop("content_sha256", None)
    sealed["content_sha256"] = content_hash(sealed)
    reasons = validate_artifact(kind, sealed)
    if receipt_kind(sealed) != kind:
        reasons.append("RECEIPT_KIND_MISMATCH")
    if reasons:
        return _rejected(reasons)
    return {
        "ok": True,
        "state": "SEALED",
        "reason_codes": ["RECEIPT_SEALED"],
        "receipt": sealed,
    }


def _supersession_reasons(
    receipts_by_id: dict[str, dict[str, Any]],
    kinds_by_id: dict[str, str],
) -> tuple[list[str], set[str]]:
    reasons: list[str] = []
    superseded: set[str] = set()
    for identifier, receipt in receipts_by_id.items():
        predecessor = receipt.get("supersedes")
        if predecessor is None:
            continue
        if predecessor == identifier:
            reasons.append("RECEIPT_SUPERSESSION_SELF_REFERENCE")
            continue
        target = receipts_by_id.get(predecessor)
        if target is None:
            reasons.append("RECEIPT_SUPERSESSION_DANGLING")
            continue
        if kinds_by_id.get(predecessor) != kinds_by_id[identifier]:
            reasons.append("RECEIPT_SUPERSESSION_KIND_MISMATCH")
        if target.get("project_id") != receipt.get("project_id"):
            reasons.append("RECEIPT_SUPERSESSION_PROJECT_MISMATCH")
        try:
            current_time = datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
            target_time = datetime.fromisoformat(target["created_at"].replace("Z", "+00:00"))
        except (AttributeError, KeyError, ValueError):
            reasons.append("RECEIPT_SUPERSESSION_TIME_INVALID")
        else:
            if current_time < target_time:
                reasons.append("RECEIPT_SUPERSESSION_ORDER_INVALID")
        superseded.add(predecessor)

    for start in receipts_by_id:
        seen: set[str] = set()
        cursor: str | None = start
        while cursor is not None and cursor in receipts_by_id:
            if cursor in seen:
                reasons.append("RECEIPT_SUPERSESSION_CYCLE")
                break
            seen.add(cursor)
            candidate = receipts_by_id[cursor].get("supersedes")
            cursor = candidate if isinstance(candidate, str) else None
    return reasons, superseded


def validate_receipt_graph(
    receipts: Any,
    *,
    project_id: str,
    request_sha256: str,
    authority_sha256: str,
    expected_active_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate hashes, lineage, and typed cross-receipt bindings fail closed."""
    if not isinstance(receipts, list) or not receipts:
        return _rejected(["RECEIPT_GRAPH_INVALID"])
    reasons: list[str] = []
    identifiers = [item.get("receipt_id") for item in receipts if isinstance(item, dict)]
    if len(identifiers) != len(receipts) or len(identifiers) != len(set(identifiers)):
        reasons.append("RECEIPT_ID_DUPLICATE_OR_INVALID")

    receipts_by_id: dict[str, dict[str, Any]] = {}
    kinds_by_id: dict[str, str] = {}
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for receipt in receipts:
        kind = receipt_kind(receipt)
        if kind is None:
            reasons.append("RECEIPT_KIND_INVALID")
            continue
        identifier = receipt["receipt_id"]
        kinds_by_id[identifier] = kind
        receipts_by_id[identifier] = receipt
        reasons.extend(validate_artifact(kind, receipt))
        if receipt.get("project_id") != project_id:
            reasons.append("RECEIPT_PROJECT_MISMATCH")
        if receipt.get("request_sha256") != request_sha256:
            reasons.append("RECEIPT_REQUEST_MISMATCH")
        if receipt.get("authority_sha256") != authority_sha256:
            reasons.append("RECEIPT_AUTHORITY_MISMATCH")
        digest = receipt.get("content_sha256")
        if isinstance(digest, str):
            by_hash.setdefault(digest, []).append(receipt)

    lineage_reasons, superseded = _supersession_reasons(receipts_by_id, kinds_by_id)
    reasons.extend(lineage_reasons)
    for receipt in receipts_by_id.values():
        kind = receipt_kind(receipt)
        if kind in {"challenge", "decision"}:
            plans = by_hash.get(receipt.get("plan_sha256", ""), [])
            if len(plans) != 1 or receipt_kind(plans[0]) != "plan":
                reasons.append("RECEIPT_PLAN_BINDING_DANGLING")
        if kind == "decision":
            challenges = by_hash.get(receipt.get("challenge_sha256", ""), [])
            if len(challenges) != 1 or receipt_kind(challenges[0]) != "challenge":
                reasons.append("RECEIPT_CHALLENGE_BINDING_DANGLING")

    active = sorted(set(receipts_by_id) - superseded)
    if expected_active_ids is not None:
        expected = list(expected_active_ids)
        if len(expected) != len(set(expected)) or any(item not in receipts_by_id for item in expected):
            reasons.append("RECEIPT_ACTIVE_SET_INVALID")
        elif sorted(expected) != active:
            reasons.append("RECEIPT_ACTIVE_SET_STALE")
    if reasons:
        return _rejected(reasons)
    return {
        "ok": True,
        "state": "VALID",
        "reason_codes": ["RECEIPT_GRAPH_VALID"],
        "active_receipt_ids": active,
    }
