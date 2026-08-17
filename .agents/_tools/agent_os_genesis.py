#!/usr/bin/env python3
"""Dependency-free, read-only Project Genesis lifecycle doctor."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_os_paths import portable_relative
from project_genesis.git_evidence import pinned_evidence_error, sha256_project_file

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
GENESIS_PATH = ROOT / "project" / "genesis.json"
BINDING_PATH = ROOT / "project" / "project-binding.json"
MANIFEST_PATH = ROOT / "_manifest" / "base-release-manifest.json"

REQUIRED_SLOTS = (
    "identity", "problem", "primary_user", "why_now", "input",
    "core_transformation", "output", "desired_outcome", "success",
    "acceptance_evidence", "failure_conditions", "scope", "non_goals",
    "invariants", "constraints", "assumptions", "unknowns",
)
UNCERTAINTY_SLOTS = {"assumptions", "unknowns"}
PRODUCT_SLOTS = {
    "problem", "primary_user", "why_now", "input", "core_transformation",
    "output", "desired_outcome", "success", "failure_conditions", "non_goals",
    "invariants",
}
DECISION_SLOTS = {"acceptance_evidence", "scope", "constraints"}
TRUTH_SLOTS = {"identity", *PRODUCT_SLOTS, *DECISION_SLOTS}
COLLECTION_SLOTS = {"invariants", "constraints", *UNCERTAINTY_SLOTS}
AUTHORITIES = {"binding", "user-confirmed", "project-decision", "git-evidence", "research-only", "historical"}
CONFIDENCES = {"confirmed", "verified", "inferred", "unknown"}
EVIDENCE_KINDS = {"repository-file", "binding", "decision-receipt", "confirmation-receipt", "research-artifact", "historical-record"}

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
GIT_COMMIT = re.compile(r"^[a-f0-9]{40}$")
DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
EXTENSION_NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,127}$")
SECRET = re.compile(r"(?:BEGIN [A-Z ]*PRIVATE KEY|(?:api[_-]?key|token|password|secret)\s*[:=])", re.IGNORECASE)

MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_VALUE_BYTES = 64 * 1024
MAX_PROJECTION_BYTES = 64 * 1024
MAX_HISTORY_ITEMS = 128
MAX_EVIDENCE_ITEMS = 32
MAX_SUPERSEDES_ITEMS = 64
MAX_EXTENSIONS = 32
CONFIRMATION_REF_PREFIX = ".agents/project/genesis-confirmations/"
BINDING_REF = ".agents/project/project-binding.json"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def content_hash(value: dict[str, Any]) -> str:
    return canonical_hash({key: item for key, item in value.items() if key != "content_sha256"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def load_json(path: Path) -> Any:
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


def datetime_value(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def portable_ref(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 512:
        return False
    try:
        return portable_relative(value, canonical=True) == value
    except ValueError:
        return False


def confirmation_ref(event_id: str) -> str:
    return f"{CONFIRMATION_REF_PREFIX}{event_id}.json"


def normalized_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        evidence,
        key=lambda item: (
            str(item.get("kind", "")),
            str(item.get("ref", "")),
            str(item.get("sha256", "")),
            str(item.get("git_commit") or ""),
        ),
    )


def claim_basis_hash(document: dict[str, Any], slot: str, claim: dict[str, Any]) -> str:
    """Bind confirmation to identity, semantic location, value, authority and evidence."""
    return canonical_hash(
        {
            "schema_version": 1,
            "project_id": document["project_id"],
            "document_id": document["document_id"],
            "slot": slot,
            "claim_id": claim["claim_id"],
            "value": claim["value"],
            "authority": claim["authority"],
            "confidence": claim["confidence"],
            "evidence": normalized_evidence(claim["evidence"]),
            "supersedes": sorted(claim["supersedes"]),
            "created_at": claim["created_at"],
            "updated_at": claim["updated_at"],
        }
    )


def meaningful_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and any(meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and any(meaningful_value(item) for item in value.values())
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return False


def uncertainty_is_non_blocking(value: Any) -> bool:
    if value in ([], {}):
        return True
    items = value if isinstance(value, list) else [value]
    if not items:
        return True
    for item in items:
        if not isinstance(item, dict):
            return False
        if item.get("impact") == "constitutional" or item.get("blocking") is True:
            return False
        if item.get("blocking") is not False and item.get("impact") not in {"non-blocking", "informational", "operational"}:
            return False
    return True


def projected_truth(active: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for slot in REQUIRED_SLOTS:
        if slot not in TRUTH_SLOTS or not active[slot]:
            continue
        values = [claim["value"] for claim in active[slot]]
        projection[slot] = values if slot in COLLECTION_SLOTS else values[0]
    return projection


def evidence_item_errors(item: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(item, dict) or set(item) != {"kind", "ref", "sha256", "git_commit"}:
        return [f"{prefix} is invalid"]
    kind = item.get("kind")
    ref = item.get("ref")
    if kind not in EVIDENCE_KINDS or not portable_ref(ref):
        errors.append(f"{prefix} provenance is invalid")
    if not SHA256.fullmatch(str(item.get("sha256", ""))):
        errors.append(f"{prefix}.sha256 is invalid")
    git_commit = item.get("git_commit")
    if git_commit is not None and not GIT_COMMIT.fullmatch(str(git_commit)):
        errors.append(f"{prefix}.git_commit is invalid")
    if isinstance(ref, str) and SECRET.search(ref):
        errors.append(f"{prefix}.ref resembles secret material")
    if kind == "binding" and ref != BINDING_REF:
        errors.append(f"{prefix}.binding ref must be {BINDING_REF}")
    if kind == "binding" and git_commit is not None:
        errors.append(f"{prefix}.binding evidence must validate current project state")
    if kind == "confirmation-receipt" and (
        not isinstance(ref, str)
        or not ref.startswith(CONFIRMATION_REF_PREFIX)
        or not ref.endswith(".json")
    ):
        errors.append(f"{prefix}.confirmation receipt ref is outside its application-owned ledger")
    return errors


def document_errors(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document must be an object"]
    expected = {"schema_version", "project_id", "document_id", "revision", "claims", "extensions", "created_at", "updated_at"}
    if set(document) != expected:
        errors.append("top-level keys do not match the schema")
    if document.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    if not SAFE_ID.fullmatch(str(document.get("project_id", ""))) or not SAFE_ID.fullmatch(str(document.get("document_id", ""))):
        errors.append("project_id and document_id must be portable identifiers")
    revision = document.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        errors.append("revision must be a positive integer")
    created_at = document.get("created_at")
    updated_at = document.get("updated_at")
    if not valid_datetime(created_at) or not valid_datetime(updated_at):
        errors.append("created_at and updated_at must be real UTC date-times")
    elif datetime_value(created_at) > datetime_value(updated_at):
        errors.append("document created_at must not be after updated_at")

    claims = document.get("claims")
    if not isinstance(claims, dict) or set(claims) != set(REQUIRED_SLOTS):
        errors.append("claims must contain exactly the required core slots")
        return errors
    for slot, history in claims.items():
        if not isinstance(history, list):
            errors.append(f"claims.{slot} must be an array")
            continue
        if len(history) > MAX_HISTORY_ITEMS:
            errors.append(f"claims.{slot} exceeds the history item limit")
        for index, claim in enumerate(history):
            prefix = f"claims.{slot}[{index}]"
            required = {"claim_id", "value", "authority", "confidence", "evidence", "supersedes", "created_at", "updated_at"}
            if not isinstance(claim, dict) or not required.issubset(claim) or set(claim) - (required | {"confirmation"}):
                errors.append(f"{prefix} has invalid keys")
                continue
            if not SAFE_ID.fullmatch(str(claim.get("claim_id", ""))):
                errors.append(f"{prefix}.claim_id is invalid")
            authority = claim.get("authority")
            confidence = claim.get("confidence")
            if authority not in AUTHORITIES or confidence not in CONFIDENCES:
                errors.append(f"{prefix} authority or confidence is invalid")
            if confidence == "confirmed" and authority != "user-confirmed":
                errors.append(f"{prefix} confirmed confidence requires user-confirmed authority")
            supersedes = claim.get("supersedes")
            if not isinstance(supersedes, list) or len(supersedes) > MAX_SUPERSEDES_ITEMS:
                errors.append(f"{prefix}.supersedes is invalid")
            elif (
                any(not isinstance(item, str) or SAFE_ID.fullmatch(item) is None for item in supersedes)
                or len(set(supersedes)) != len(supersedes)
            ):
                errors.append(f"{prefix}.supersedes is invalid")
            evidence = claim.get("evidence")
            if not isinstance(evidence, list) or not evidence or len(evidence) > MAX_EVIDENCE_ITEMS:
                errors.append(f"{prefix}.evidence must contain 1-{MAX_EVIDENCE_ITEMS} items")
            else:
                for evidence_index, item in enumerate(evidence):
                    errors.extend(evidence_item_errors(item, f"{prefix}.evidence[{evidence_index}]"))
                if all(isinstance(item, dict) for item in evidence):
                    fingerprints = [canonical_hash(item) for item in evidence]
                    if len(set(fingerprints)) != len(fingerprints):
                        errors.append(f"{prefix}.evidence contains duplicate items")
            confirmation = claim.get("confirmation")
            if confirmation is not None:
                confirmation_valid = (
                    isinstance(confirmation, dict)
                    and set(confirmation) == {"event_id", "receipt_ref", "receipt_sha256", "basis_sha256"}
                    and SAFE_ID.fullmatch(str(confirmation.get("event_id", ""))) is not None
                    and portable_ref(confirmation.get("receipt_ref"))
                    and confirmation.get("receipt_ref") == confirmation_ref(str(confirmation.get("event_id", "")))
                    and SHA256.fullmatch(str(confirmation.get("receipt_sha256", ""))) is not None
                    and SHA256.fullmatch(str(confirmation.get("basis_sha256", ""))) is not None
                )
                if not confirmation_valid:
                    errors.append(f"{prefix}.confirmation is invalid")
                if authority not in {"binding", "user-confirmed"}:
                    errors.append(f"{prefix}.confirmation is not allowed for authority {authority}")
            try:
                value_bytes = canonical_json(claim.get("value"))
            except (TypeError, ValueError):
                errors.append(f"{prefix}.value is not canonical JSON")
            else:
                if len(value_bytes) > MAX_VALUE_BYTES:
                    errors.append(f"{prefix}.value exceeds the size limit")
                if SECRET.search(value_bytes.decode("utf-8", errors="replace")):
                    errors.append(f"{prefix}.value resembles secret material")
            claim_created = claim.get("created_at")
            claim_updated = claim.get("updated_at")
            if not valid_datetime(claim_created) or not valid_datetime(claim_updated):
                errors.append(f"{prefix} timestamps are invalid")
            elif datetime_value(claim_created) > datetime_value(claim_updated):
                errors.append(f"{prefix}.created_at must not be after updated_at")

    extensions = document.get("extensions")
    if not isinstance(extensions, dict) or len(extensions) > MAX_EXTENSIONS:
        errors.append(f"extensions must be an object with at most {MAX_EXTENSIONS} entries")
    else:
        for namespace, extension in extensions.items():
            valid = (
                EXTENSION_NAMESPACE.fullmatch(str(namespace)) is not None
                and isinstance(extension, dict)
                and set(extension) == {"schema_ref", "owner", "required_for_confirmation", "value"}
                and isinstance(extension.get("schema_ref"), str)
                and 1 <= len(extension["schema_ref"]) <= 512
                and extension.get("owner") == "application"
                and isinstance(extension.get("required_for_confirmation"), bool)
            )
            if not valid:
                errors.append(f"extension {namespace} has an invalid envelope")
                continue
            try:
                extension_value = canonical_json(extension.get("value"))
            except (TypeError, ValueError):
                errors.append(f"extension {namespace}.value is not canonical JSON")
            else:
                if len(extension_value) > MAX_VALUE_BYTES:
                    errors.append(f"extension {namespace}.value exceeds the size limit")
                if SECRET.search(extension_value.decode("utf-8", errors="replace")):
                    errors.append(f"extension {namespace}.value resembles secret material")
    return errors


def confirmation_receipt_errors(receipt: Any) -> list[str]:
    expected = {
        "schema_version", "receipt_id", "project_id", "document_id",
        "issued_for_revision", "confirmed_by_role", "confirmed_at",
        "plan_sha256", "claim_bindings", "raw_conversation_stored",
        "content_sha256",
    }
    if not isinstance(receipt, dict):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != expected or receipt.get("schema_version") != 1:
        errors.append("receipt keys or schema_version are invalid")
    for key in ("receipt_id", "project_id", "document_id"):
        if SAFE_ID.fullmatch(str(receipt.get(key, ""))) is None:
            errors.append(f"receipt {key} is invalid")
    revision = receipt.get("issued_for_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        errors.append("receipt issued_for_revision is invalid")
    if receipt.get("confirmed_by_role") != "owner" or not valid_datetime(receipt.get("confirmed_at")):
        errors.append("receipt owner role or timestamp is invalid")
    if SHA256.fullmatch(str(receipt.get("plan_sha256", ""))) is None:
        errors.append("receipt plan_sha256 is invalid")
    if receipt.get("raw_conversation_stored") is not False:
        errors.append("receipt must not store raw conversation")
    bindings = receipt.get("claim_bindings")
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 64:
        errors.append("receipt claim_bindings are invalid")
    else:
        keys: list[tuple[str, str]] = []
        for index, binding in enumerate(bindings):
            if (
                not isinstance(binding, dict)
                or set(binding) != {"slot", "claim_id", "basis_sha256"}
                or binding.get("slot") not in REQUIRED_SLOTS
                or SAFE_ID.fullmatch(str(binding.get("claim_id", ""))) is None
                or SHA256.fullmatch(str(binding.get("basis_sha256", ""))) is None
            ):
                errors.append(f"receipt claim_bindings[{index}] is invalid")
                continue
            keys.append((binding["slot"], binding["claim_id"]))
        if len(keys) != len(set(keys)):
            errors.append("receipt claim_bindings contain duplicate claim targets")
    if SHA256.fullmatch(str(receipt.get("content_sha256", ""))) is None or receipt.get("content_sha256") != content_hash(receipt):
        errors.append("receipt content hash is invalid")
    return errors


def graph_result(claims: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    active: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    global_slots: dict[str, str] = {}
    for slot, history in claims.items():
        by_id: dict[str, dict[str, Any]] = {}
        superseded: set[str] = set()
        for claim in history:
            claim_id = claim["claim_id"]
            if claim_id in global_slots:
                errors.append(f"duplicate claim_id {claim_id}")
            else:
                global_slots[claim_id] = slot
            if claim_id in by_id:
                errors.append(f"duplicate claim_id {claim_id} in {slot}")
            else:
                by_id[claim_id] = claim
        for claim in history:
            for target in claim["supersedes"]:
                if target not in by_id:
                    errors.append(f"{claim['claim_id']} supersedes missing or cross-slot claim {target}")
                else:
                    superseded.add(target)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(claim_id: str) -> None:
            if claim_id in visiting:
                errors.append(f"supersession cycle at {claim_id}")
                return
            if claim_id in visited:
                return
            visiting.add(claim_id)
            for target in by_id[claim_id]["supersedes"]:
                if target in by_id:
                    visit(target)
            visiting.remove(claim_id)
            visited.add(claim_id)

        for claim_id in by_id:
            visit(claim_id)
        leaves = [claim for claim_id, claim in by_id.items() if claim_id not in superseded]
        if slot not in COLLECTION_SLOTS and len(leaves) > 1:
            errors.append(f"multiple active claims in singleton slot {slot}")
        active[slot] = leaves
    return active, errors


def evidence_health(
    project_root: Path,
    slot: str,
    claim: dict[str, Any],
) -> tuple[list[str], list[str]]:
    contamination: list[str] = []
    stale: list[str] = []
    resolved_root = project_root.resolve()
    for evidence in claim["evidence"]:
        ref = evidence["ref"]
        git_commit = evidence["git_commit"]
        if git_commit is not None:
            error = pinned_evidence_error(project_root, git_commit, ref, evidence["sha256"])
            if error:
                stale.append(f"evidence {error}: {slot}/{claim['claim_id']}:{ref}")
            continue
        evidence_path = project_root.joinpath(*Path(ref).parts)
        try:
            resolved = evidence_path.resolve(strict=False)
        except OSError:
            contamination.append(f"unresolvable evidence path: {slot}/{claim['claim_id']}:{ref}")
            continue
        if resolved != resolved_root and resolved_root not in resolved.parents:
            contamination.append(f"cross-project evidence: {slot}/{claim['claim_id']}:{ref}")
            continue
        if has_symlink_component(project_root, evidence_path):
            contamination.append(f"symlink evidence is not admissible: {slot}/{claim['claim_id']}:{ref}")
            continue
        if not evidence_path.is_file() or sha256_project_file(project_root, evidence_path) != evidence["sha256"]:
            stale.append(f"evidence drift: {slot}/{claim['claim_id']}:{ref}")
    return contamination, stale


def has_symlink_component(project_root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(project_root)
    except ValueError:
        return True
    current = project_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def confirmation_health(
    project_root: Path,
    document: dict[str, Any],
    slot: str,
    claim: dict[str, Any],
) -> list[str]:
    confirmation = claim.get("confirmation")
    if not isinstance(confirmation, dict):
        return []
    stale: list[str] = []
    basis = claim_basis_hash(document, slot, claim)
    if confirmation["basis_sha256"] != basis:
        stale.append(f"confirmation basis drift: {slot}/{claim['claim_id']}")
        return stale
    receipt_path = project_root.joinpath(*Path(confirmation["receipt_ref"]).parts)
    try:
        resolved_receipt = receipt_path.resolve(strict=False)
    except OSError:
        return [f"confirmation receipt path is unresolvable: {slot}/{claim['claim_id']}"]
    resolved_root = project_root.resolve()
    if (
        has_symlink_component(project_root, receipt_path)
        or (resolved_receipt != resolved_root and resolved_root not in resolved_receipt.parents)
        or not receipt_path.is_file()
    ):
        return [f"confirmation receipt missing: {slot}/{claim['claim_id']}"]
    if sha256_project_file(project_root, receipt_path) != confirmation["receipt_sha256"]:
        return [f"confirmation receipt byte drift: {slot}/{claim['claim_id']}"]
    try:
        receipt = load_json(receipt_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return [f"confirmation receipt unreadable: {slot}/{claim['claim_id']}"]
    receipt_errors = confirmation_receipt_errors(receipt)
    if receipt_errors:
        return [f"confirmation receipt invalid: {slot}/{claim['claim_id']}:{message}" for message in receipt_errors]
    if (
        receipt["receipt_id"] != confirmation["event_id"]
        or receipt["project_id"] != document["project_id"]
        or receipt["document_id"] != document["document_id"]
        or receipt["issued_for_revision"] > document["revision"]
    ):
        stale.append(f"confirmation receipt identity drift: {slot}/{claim['claim_id']}")
    expected_binding = {"slot": slot, "claim_id": claim["claim_id"], "basis_sha256": basis}
    if expected_binding not in receipt["claim_bindings"]:
        stale.append(f"confirmation receipt does not bind claim: {slot}/{claim['claim_id']}")
    return stale


def doctor(root: Path = ROOT, genesis_path: Path | None = None) -> dict[str, Any]:
    project_root = root.parent
    path = genesis_path or root / "project" / "genesis.json"
    try:
        display_path = path.relative_to(project_root).as_posix()
    except ValueError:
        display_path = str(path)
    result: dict[str, Any] = {
        "ok": False,
        "state": "missing",
        "path": display_path,
        "reason_codes": [],
        "errors": [],
        "stale": [],
    }
    if not path.is_file():
        result["reason_codes"] = ["GENESIS_MISSING"]
        return result
    resolved_root = project_root.resolve()
    try:
        resolved_path = path.resolve(strict=True)
    except OSError as exc:
        result.update(state="contaminated", reason_codes=["GENESIS_PROJECT_CONTAMINATION"], errors=[str(exc)])
        return result
    if has_symlink_component(project_root, path) or (resolved_path != resolved_root and resolved_root not in resolved_path.parents):
        result.update(
            state="contaminated",
            reason_codes=["GENESIS_PROJECT_CONTAMINATION"],
            errors=["Genesis source is a symlink or outside the bound project"],
        )
        return result
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError(f"Genesis document exceeds {MAX_DOCUMENT_BYTES} bytes")
        document = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result.update(state="draft", reason_codes=["GENESIS_DOCUMENT_INVALID"], errors=[str(exc)])
        return result
    errors = document_errors(document)
    if errors:
        result.update(state="draft", reason_codes=["GENESIS_DOCUMENT_INVALID"], errors=errors)
        return result

    binding_path = root / "project" / "project-binding.json"
    try:
        binding = load_json(binding_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        binding = {}
    contamination: list[str] = []
    if document["project_id"] != binding.get("project_id"):
        contamination.append("Genesis project_id does not match the current project binding")
    manifest_path = root / "_manifest" / "base-release-manifest.json"
    try:
        manifest = load_json(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        manifest = {}
    manifest_paths = {
        item.get("path")
        for item in manifest.get("entries", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if "project/genesis.json" in manifest_paths or any(
        path.startswith("project/genesis-confirmations/") for path in manifest_paths
    ):
        contamination.append("actual Project Genesis authority appears in the release manifest")
    if contamination:
        result.update(state="contaminated", reason_codes=["GENESIS_PROJECT_CONTAMINATION"], errors=contamination)
        return result

    active, graph_errors = graph_result(document["claims"])
    if graph_errors:
        result.update(state="conflicting", reason_codes=["GENESIS_CLAIM_GRAPH_CONFLICT"], errors=graph_errors)
        return result

    stale: list[str] = []
    for slot, claims in active.items():
        for claim in claims:
            claim_contamination, claim_stale = evidence_health(project_root, slot, claim)
            contamination.extend(claim_contamination)
            stale.extend(claim_stale)
            stale.extend(confirmation_health(project_root, document, slot, claim))
    if contamination:
        result.update(state="contaminated", reason_codes=["GENESIS_PROJECT_CONTAMINATION"], errors=contamination)
        return result
    if stale:
        result.update(state="stale", reason_codes=["GENESIS_EVIDENCE_OR_CONFIRMATION_STALE"], stale=stale)
        return result

    draft: list[str] = []
    reason_codes: list[str] = []
    for slot in REQUIRED_SLOTS:
        claims = active[slot]
        if slot in UNCERTAINTY_SLOTS:
            for claim in claims:
                if not uncertainty_is_non_blocking(claim["value"]):
                    draft.append(f"blocking uncertainty remains: {slot}/{claim['claim_id']}")
            continue
        if not claims:
            draft.append(f"required claim missing: {slot}")
            continue
        for claim in claims:
            authority = claim["authority"]
            confidence = claim["confidence"]
            confirmation = claim.get("confirmation")
            if not meaningful_value(claim["value"]):
                draft.append(f"required claim value is empty: {slot}/{claim['claim_id']}")
                if "GENESIS_REQUIRED_VALUE_EMPTY" not in reason_codes:
                    reason_codes.append("GENESIS_REQUIRED_VALUE_EMPTY")
            if slot == "identity":
                accepted = (
                    authority == "binding"
                    and confidence == "verified"
                    and confirmation is not None
                    and any(item["kind"] == "binding" and item["ref"] == BINDING_REF for item in claim["evidence"])
                )
            else:
                accepted = authority == "user-confirmed" and confidence == "confirmed" and confirmation is not None
            if not accepted:
                draft.append(f"claim lacks confirmed constitutional authority: {slot}/{claim['claim_id']}")
    required_extensions = sorted(
        namespace
        for namespace, extension in document["extensions"].items()
        if extension["required_for_confirmation"] is True
    )
    if required_extensions:
        draft.append(f"required extension validators unavailable: {', '.join(required_extensions)}")
        reason_codes.append("GENESIS_EXTENSION_VALIDATION_REQUIRED")
    if len(canonical_json(projected_truth(active))) > MAX_PROJECTION_BYTES:
        draft.append(f"confirmed truth exceeds the {MAX_PROJECTION_BYTES}-byte boot projection budget")
        reason_codes.append("GENESIS_BOOT_BUDGET_EXCEEDED")
    if draft:
        if "GENESIS_CONFIRMATION_INCOMPLETE" not in reason_codes:
            reason_codes.insert(0, "GENESIS_CONFIRMATION_INCOMPLETE")
        result.update(
            state="draft",
            reason_codes=reason_codes,
            errors=draft,
            revision=document["revision"],
            source_sha256=sha256_project_file(project_root, path),
        )
        return result
    result.update(
        ok=True,
        state="confirmed",
        reason_codes=[],
        revision=document["revision"],
        source_sha256=sha256_project_file(project_root, path),
        active_claim_ids={slot: [claim["claim_id"] for claim in claims] for slot, claims in active.items()},
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Genesis lifecycle doctor")
    parser.add_argument("command", choices=["doctor"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--genesis", type=Path)
    args = parser.parse_args()
    result = doctor(args.root.resolve(), args.genesis.resolve() if args.genesis else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
