#!/usr/bin/env python3
"""Capability catalog validation and explainable deterministic candidate ranking."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "routing" / "capability-registry.json"
DESCRIPTORS_PATH = ROOT / "routing" / "capability-descriptors.json"
POLICY_PATH = ROOT / "routing" / "capability-policy.json"
DECISIONS_PATH = ROOT / "routing" / "capability-decisions.json"
VENDOR_LOCK_PATH = ROOT / "vendor" / "vendor-lock.json"
PROJECT_SETTINGS_PATH = ROOT / "project" / "skill-config.json"

ACTIVE_STATES = {"active"}
AUTO_BLOCKED_STATES = {"manual-only", "disabled", "quarantined", "deprecated"}
INTEGRATION_MODES = {
    "native",
    "vendor-pin",
    "adapt-local-skill",
    "adapt-local-principles",
    "project-local",
    "research-only",
}
STOP_WORDS = {
    "a", "an", "and", "any", "for", "from", "in", "is", "it", "of", "on",
    "or", "the", "this", "to", "use", "when", "with", "work", "task",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]+", text.lower())
        if token not in STOP_WORDS and len(token) > 1
    }


def trigger_matches_text(trigger: Any, normalized_text: str, prompt_tokens: set[str]) -> bool:
    """Match exact phrases first, then tolerate harmless word reordering.

    Routing metadata is intentionally small and human-readable. A trigger such
    as ``review PR`` must still match ``review this PR`` without requiring a
    second catalog entry or a fuzzy model call. Single-token triggers remain
    exact substring matches to avoid broad accidental activation.
    """
    phrase = str(trigger).strip().lower()
    if not phrase:
        return False
    if phrase in normalized_text:
        return True
    trigger_tokens = tokens(phrase)
    return len(trigger_tokens) >= 2 and trigger_tokens.issubset(prompt_tokens)


def descriptor_map() -> dict[str, dict[str, Any]]:
    document = load_json(DESCRIPTORS_PATH, {})
    records = document.get("capabilities", []) if isinstance(document, dict) else []
    return {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def route_map(registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    source = registry if isinstance(registry, dict) else load_json(REGISTRY_PATH, {})
    routes: dict[str, dict[str, Any]] = {}
    for capability_id, route in (source.get("capabilities") or {}).items():
        if isinstance(route, dict):
            routes[capability_id] = {**route, "type": "capability"}
    for capability_id, route in (source.get("vendor_skills") or {}).items():
        if isinstance(route, dict):
            routes[capability_id] = {**route, "type": "vendor_skill"}
    return routes


def decision_ids() -> set[str]:
    document = load_json(DECISIONS_PATH, {})
    receipts = document.get("receipts", []) if isinstance(document, dict) else []
    return {
        receipt["id"]
        for receipt in receipts
        if isinstance(receipt, dict) and isinstance(receipt.get("id"), str)
    }


def decision_receipt_hash(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "content_sha256"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_catalog() -> dict[str, Any]:
    registry = load_json(REGISTRY_PATH, {})
    descriptors_document = load_json(DESCRIPTORS_PATH, {})
    policy = load_json(POLICY_PATH, {})
    decisions = load_json(DECISIONS_PATH, {})
    vendors = load_json(VENDOR_LOCK_PATH, {})
    errors: list[dict[str, Any]] = []

    if descriptors_document.get("schema_version") != 1:
        errors.append({"code": "DESCRIPTOR_SCHEMA_INVALID"})
    if descriptors_document.get("agent_os_version") != registry.get("version"):
        errors.append({"code": "DESCRIPTOR_VERSION_MISMATCH"})
    if policy.get("schema_version") != 1:
        errors.append({"code": "CAPABILITY_POLICY_INVALID"})
    if decisions.get("schema_version") != 1:
        errors.append({"code": "DECISION_LEDGER_INVALID"})

    records = descriptors_document.get("capabilities", [])
    if not isinstance(records, list):
        records = []
        errors.append({"code": "DESCRIPTOR_RECORDS_INVALID"})
    ids: list[str] = [record.get("id") for record in records if isinstance(record, dict)]
    if len(ids) != len(set(ids)):
        errors.append({"code": "CAPABILITY_ID_DUPLICATED"})

    routes = route_map(registry)
    descriptors = descriptor_map()
    for missing in sorted(set(routes) - set(descriptors)):
        errors.append({"code": "CAPABILITY_DESCRIPTOR_MISSING", "id": missing})
    for stale in sorted(set(descriptors) - set(routes)):
        errors.append({"code": "CAPABILITY_DESCRIPTOR_UNROUTED", "id": stale})

    known_decisions = decision_ids()
    required = {
        "id", "version", "lifecycle_state", "summary", "when_to_use", "not_for",
        "integration_mode", "source", "risk", "permissions", "dependencies",
        "conflicts", "token_profile", "eval", "decision_ref",
    }
    permission_fields = {"filesystem", "shell", "git", "network", "secrets", "external_state"}
    for capability_id, descriptor in descriptors.items():
        missing = sorted(required - set(descriptor))
        if missing:
            errors.append({"code": "CAPABILITY_DESCRIPTOR_FIELDS_MISSING", "id": capability_id, "fields": missing})
        if descriptor.get("integration_mode") not in INTEGRATION_MODES:
            errors.append({"code": "CAPABILITY_INTEGRATION_MODE_INVALID", "id": capability_id})
        if descriptor.get("lifecycle_state") not in ACTIVE_STATES | AUTO_BLOCKED_STATES:
            errors.append({"code": "CAPABILITY_STATE_INVALID", "id": capability_id})
        if descriptor.get("decision_ref") not in known_decisions:
            errors.append({"code": "CAPABILITY_DECISION_MISSING", "id": capability_id})
        permissions = descriptor.get("permissions")
        if not isinstance(permissions, dict) or set(permissions) != permission_fields:
            errors.append({"code": "CAPABILITY_PERMISSIONS_INVALID", "id": capability_id})
        for relative in descriptor.get("dependencies", []):
            if not isinstance(relative, str) or not (ROOT / relative).exists():
                errors.append({"code": "CAPABILITY_DEPENDENCY_MISSING", "id": capability_id, "path": relative})

    package_commits = {
        package.get("commit")
        for package in vendors.get("packages", [])
        if isinstance(package, dict)
    }
    for capability_id, route in routes.items():
        if route.get("type") != "vendor_skill":
            continue
        descriptor = descriptors.get(capability_id, {})
        source = descriptor.get("source", {}) if isinstance(descriptor.get("source"), dict) else {}
        if descriptor.get("integration_mode") != "vendor-pin" or source.get("commit") not in package_commits:
            errors.append({"code": "VENDOR_CAPABILITY_PROVENANCE_INVALID", "id": capability_id})

    receipt_capabilities: set[str] = set()
    seen_receipts: set[str] = set()
    for receipt in decisions.get("receipts", []) if isinstance(decisions.get("receipts"), list) else []:
        if not isinstance(receipt, dict):
            continue
        receipt_id = receipt.get("id")
        if not isinstance(receipt_id, str) or receipt_id in seen_receipts:
            errors.append({"code": "CAPABILITY_DECISION_ID_INVALID", "id": receipt_id})
        if receipt.get("content_sha256") != decision_receipt_hash(receipt):
            errors.append({"code": "CAPABILITY_DECISION_HASH_INVALID", "id": receipt_id})
        supersedes = receipt.get("supersedes")
        if supersedes is not None and supersedes not in seen_receipts:
            errors.append({"code": "CAPABILITY_DECISION_SUPERSEDES_UNKNOWN", "id": receipt_id})
        if isinstance(receipt_id, str):
            seen_receipts.add(receipt_id)
        receipt_capabilities.update(str(value) for value in receipt.get("capability_ids", []))
    for missing in sorted(set(descriptors) - receipt_capabilities):
        errors.append({"code": "CAPABILITY_DECISION_COVERAGE_MISSING", "id": missing})

    return {
        "ok": not errors,
        "version": registry.get("version"),
        "routes": len(routes),
        "descriptors": len(descriptors),
        "decisions": len(known_decisions),
        "errors": errors,
    }


def capability_cards() -> list[dict[str, Any]]:
    routes = route_map()
    descriptors = descriptor_map()
    cards: list[dict[str, Any]] = []
    overrides = project_overrides()
    for capability_id in sorted(descriptors):
        descriptor = descriptors[capability_id]
        route = routes.get(capability_id, {})
        cards.append({**descriptor, "project_override": overrides.get(capability_id, "automatic"), "route": route})
    return cards


def capability_card(capability_id: str) -> dict[str, Any] | None:
    return next((card for card in capability_cards() if card["id"] == capability_id), None)


def project_overrides() -> dict[str, str]:
    settings = load_json(PROJECT_SETTINGS_PATH, {})
    raw = settings.get("capability_overrides") if isinstance(settings, dict) else {}
    return {
        str(capability_id): str(value)
        for capability_id, value in (raw.items() if isinstance(raw, dict) else [])
        if value in {"automatic", "manual-only", "disabled"}
    }


def route_capability(text: str, registry: dict[str, Any] | None = None, overrides: dict[str, str] | None = None) -> dict[str, Any]:
    normalized = text.lower()
    prompt_tokens = tokens(text)
    routes = route_map(registry)
    descriptors = descriptor_map()
    effective_overrides = project_overrides() if overrides is None else overrides
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for capability_id, route in routes.items():
        descriptor = descriptors.get(capability_id)
        if not descriptor:
            excluded.append({"id": capability_id, "reason": "descriptor_missing"})
            continue
        state = descriptor.get("lifecycle_state")
        if state != "active":
            excluded.append({"id": capability_id, "reason": f"lifecycle_state:{state}"})
            continue
        override = effective_overrides.get(capability_id, "automatic")
        explicit_name = capability_id.replace("_", " ").replace("-", " ") in normalized
        if override == "disabled":
            excluded.append({"id": capability_id, "reason": "project_override:disabled"})
            continue
        if override == "manual-only" and not explicit_name:
            excluded.append({"id": capability_id, "reason": "project_override:manual-only"})
            continue

        trigger_values = route.get("triggers", route.get("high_triggers", []))
        trigger_matches = [
            trigger
            for trigger in trigger_values
            if trigger_matches_text(trigger, normalized, prompt_tokens)
        ]
        evidence: list[str] = [f"trigger:{trigger}" for trigger in trigger_matches]
        score = 0
        if trigger_matches:
            score += 70 + min(20, (len(trigger_matches) - 1) * 10)
        normalized_id = capability_id.replace("_", " ").replace("-", " ")
        if normalized_id in normalized:
            score += 25
            evidence.append("explicit-capability-name")

        positive_text = " ".join([descriptor.get("summary", ""), *descriptor.get("when_to_use", [])])
        overlap = sorted(prompt_tokens & tokens(positive_text))
        if overlap:
            score += min(25, len(overlap) * 5)
            evidence.extend(f"semantic-token:{token}" for token in overlap[:5])

        negative_text = " ".join(descriptor.get("not_for", []))
        trigger_token_set = tokens(" ".join(str(value) for value in trigger_values))
        negative_only_tokens = tokens(negative_text) - tokens(positive_text) - trigger_token_set
        negative_overlap = sorted(prompt_tokens & negative_only_tokens)
        if len(negative_overlap) >= 2:
            score -= min(35, len(negative_overlap) * 7)
            evidence.extend(f"counterexample-token:{token}" for token in negative_overlap[:5])

        ranked.append(
            {
                "id": capability_id,
                "type": route.get("type", "capability"),
                "path": route.get("path", ""),
                "load": route.get("load", []),
                "group": route.get("group", ""),
                "role": route.get("role", ""),
                "mode": route.get("mode", "STANDARD"),
                "score": max(0, min(100, score)),
                "evidence": evidence,
                "summary": descriptor.get("summary"),
                "risk": descriptor.get("risk"),
                "permissions": descriptor.get("permissions"),
                "approval_required": any(value == "explicit-approval" for value in descriptor.get("permissions", {}).values()),
                "project_override": override,
            }
        )

    ranked.sort(key=lambda candidate: (candidate["score"], candidate["id"]), reverse=True)
    policy = load_json(POLICY_PATH, {})
    minimum = int(policy.get("activation", {}).get("minimum_confidence", 55))
    best = ranked[0] if ranked else None
    if not best or best["score"] < minimum:
        fallback_route = routes.get("standard_feature", {})
        fallback_descriptor = descriptors.get("standard_feature", {})
        selected = {
            "id": "standard_feature",
            "type": fallback_route.get("type", "capability"),
            "path": fallback_route.get("path", ""),
            "load": fallback_route.get("load", []),
            "mode": fallback_route.get("mode", "STANDARD"),
            "score": best["score"] if best else 0,
            "confidence": "low",
            "evidence": best["evidence"] if best else [],
            "summary": fallback_descriptor.get("summary"),
            "fallback": True,
        }
        gap = {
            "detected": True,
            "reason": "no_active_capability_reached_minimum_confidence",
            "task_tokens": sorted(prompt_tokens),
            "research_suggested": True,
        }
    else:
        selected = {**best, "confidence": "high" if best["score"] >= 75 else "medium"}
        gap = {"detected": False, "research_suggested": False}

    alternatives = [candidate for candidate in ranked if candidate["id"] != selected["id"]][:3]
    return {
        "selected": selected,
        "alternatives": alternatives,
        "excluded": excluded,
        "capability_gap": gap,
        "minimum_confidence": minimum,
    }
