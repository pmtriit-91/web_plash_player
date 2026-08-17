"""Bounded JSON contract validation for governed reasoning artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

AGENT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = AGENT_ROOT / "core/contracts"
MAX_ARTIFACT_BYTES = 131072


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def content_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes({key: item for key, item in value.items() if key != "content_sha256"})).hexdigest()


def load_contract(name: str, contract_root: Path = CONTRACT_ROOT) -> dict[str, Any]:
    if name not in {"request", "plan", "challenge", "decision", "policy"}:
        raise ValueError("GOVERNED_CONTRACT_UNKNOWN")
    filename = "governed-reasoning-request.schema.json" if name == "request" else f"governed-{name}-receipt.schema.json" if name != "policy" else "governed-reasoning-policy.schema.json"
    path = contract_root / filename
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("GOVERNED_CONTRACT_UNAVAILABLE")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(schema: dict[str, Any], node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        target: Any = schema
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _valid(schema: dict[str, Any], node: Any, value: Any) -> bool:
    node = _resolve(schema, node)
    if "oneOf" in node and sum(_valid(schema, item, value) for item in node["oneOf"]) != 1:
        return False
    if "const" in node and value != node["const"] or "enum" in node and value not in node["enum"]:
        return False
    expected = node.get("type")
    types = expected if isinstance(expected, list) else [expected] if expected else []
    checks = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list), "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int, "boolean": lambda: type(value) is bool, "null": lambda: value is None}
    if types and not any(checks[item]() for item in types):
        return False
    if isinstance(value, str):
        if not node.get("minLength", 0) <= len(value) <= node.get("maxLength", 10**9):
            return False
        if "pattern" in node and re.fullmatch(node["pattern"], value) is None:
            return False
        if node.get("format") == "date-time":
            try:
                if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    return False
            except ValueError:
                return False
    if type(value) is int and not node.get("minimum", value) <= value <= node.get("maximum", value):
        return False
    if isinstance(value, list):
        if not node.get("minItems", 0) <= len(value) <= node.get("maxItems", 10**9):
            return False
        if node.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            return False
        if "items" in node and not all(_valid(schema, node["items"], item) for item in value):
            return False
    if isinstance(value, dict):
        required, properties = set(node.get("required", [])), node.get("properties", {})
        if not required <= set(value) or node.get("additionalProperties") is False and not set(value) <= set(properties):
            return False
        if any(key in properties and not _valid(schema, properties[key], item) for key, item in value.items()):
            return False
    for rule in node.get("allOf", []):
        condition = rule.get("if")
        branch = rule.get("then") if condition and _valid(schema, condition, value) else rule.get("else")
        if branch is not None and not _valid(schema, branch, value):
            return False
    return True


def _request_semantic_reasons(document: dict[str, Any]) -> list[str]:
    evidence_ids = [item["evidence_id"] for item in document["evidence"]]
    reasons: list[str] = []
    if len(evidence_ids) != len(set(evidence_ids)):
        reasons.append("GOVERNED_EVIDENCE_ID_DUPLICATE")
    available = set(evidence_ids)
    claims = document["assumptions"]
    if any(
        claim["status"] in {"verified", "inferred"} and not claim["evidence_refs"]
        for claim in claims
    ):
        reasons.append("GOVERNED_CLAIM_EVIDENCE_REQUIRED")
    references = [
        reference
        for item in [*claims, *document["options"]]
        for reference in item["evidence_refs"]
    ]
    if any(reference not in available for reference in references):
        reasons.append("GOVERNED_EVIDENCE_REF_INVALID")
    return reasons


def validate_artifact(name: str, document: Any, contract_root: Path = CONTRACT_ROOT) -> list[str]:
    if not isinstance(document, dict):
        return ["GOVERNED_ARTIFACT_INVALID"]
    if len(canonical_bytes(document)) > MAX_ARTIFACT_BYTES:
        return ["GOVERNED_ARTIFACT_OVERSIZED"]
    try:
        schema = load_contract(name, contract_root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return ["GOVERNED_CONTRACT_UNAVAILABLE"]
    reasons = [] if _valid(schema, schema, document) else ["GOVERNED_ARTIFACT_INVALID"]
    if not reasons and name == "request":
        reasons.extend(_request_semantic_reasons(document))
    if document.get("content_sha256") != content_hash(document):
        reasons.append("GOVERNED_CONTENT_HASH_INVALID")
    return reasons
