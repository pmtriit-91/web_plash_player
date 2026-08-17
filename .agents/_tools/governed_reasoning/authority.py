"""Fail-closed authority composition beneath Binding, Genesis and active policy."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_genesis import doctor as genesis_doctor  # noqa: E402
from agent_os_genesis_transactions import GenesisService  # noqa: E402
from governed_reasoning.contracts import (  # noqa: E402
    canonical_bytes,
    content_hash,
    validate_artifact,
)
from lifecycle.binding_validation import validate_binding  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_authority(agent_root: Path) -> dict[str, Any]:
    binding_path = agent_root / "project/project-binding.json"
    if not binding_path.is_file() or binding_path.is_symlink():
        return {"available": False, "reason_codes": ["BINDING_UNAVAILABLE"]}
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"available": False, "reason_codes": ["BINDING_UNAVAILABLE"]}
    if not isinstance(binding, dict) or validate_binding(binding)[0]:
        return {"available": False, "reason_codes": ["BINDING_INVALID"]}
    genesis = genesis_doctor(agent_root)
    projection = GenesisService(agent_root).projection_status()
    available = bool(
        genesis.get("ok")
        and genesis.get("state") == "confirmed"
        and projection.get("ok") is True
    )
    reason_codes = list(genesis.get("reason_codes", []))
    reason_codes.extend(projection.get("reason_codes", []))
    return {
        "available": available,
        "project_id": binding.get("project_id"),
        "binding_sha256": sha256_file(binding_path),
        "genesis_revision": genesis.get("revision"),
        "genesis_source_sha256": genesis.get("source_sha256"),
        "reason_codes": []
        if available
        else list(dict.fromkeys(reason_codes)) or ["GENESIS_AUTHORITY_UNAVAILABLE"],
    }


def _result(disposition: str, reasons: list[str], bindings: dict[str, Any]) -> dict[str, Any]:
    ordered = list(dict.fromkeys(reasons))
    authority_sha256 = hashlib.sha256(canonical_bytes(bindings)).hexdigest()
    return {"ok": disposition == "proceed", "disposition": disposition, "reason_codes": ordered, "authority_sha256": authority_sha256}


def evaluate_authority(
    request: Any,
    policy: Any,
    snapshot: dict[str, Any],
    *,
    current_intent_sha256: str,
    current_approval_sha256: str | None = None,
    approval_required: bool = False,
    transaction_gates_valid: bool = True,
    constitution_conflict: bool = False,
    confidence: str = "high",
) -> dict[str, Any]:
    request_reasons = validate_artifact("request", request)
    policy_reasons = validate_artifact("policy", policy)
    if request_reasons or policy_reasons:
        return _result("block", request_reasons + policy_reasons, {"snapshot": snapshot})
    bindings = {"project_id": request["project_id"], "authority": request["authority"], "policy_sha256": content_hash(policy), "snapshot": snapshot}
    blockers: list[str] = []
    expected = request["authority"]
    if not snapshot.get("available"):
        blockers.extend(snapshot.get("reason_codes", ["GENESIS_AUTHORITY_UNAVAILABLE"]))
    if request["project_id"] != snapshot.get("project_id"):
        blockers.append("WRONG_PROJECT")
    if policy["project_id"] != request["project_id"]:
        blockers.append("POLICY_PROJECT_MISMATCH")
    for field in ("binding_sha256", "genesis_revision", "genesis_source_sha256"):
        if expected.get(field) != snapshot.get(field):
            blockers.append(f"{field.upper()}_MISMATCH")
    if expected["policy_sha256"] != content_hash(policy):
        blockers.append("POLICY_HASH_MISMATCH")
    if expected["intent_sha256"] != current_intent_sha256:
        blockers.append("INTENT_AUTHORITY_MISMATCH")
    limits = policy["limits"]
    if len(request["options"]) > limits["max_options"]:
        blockers.append("POLICY_OPTION_LIMIT_EXCEEDED")
    if len(request["evidence"]) > limits["max_evidence_refs"]:
        blockers.append("POLICY_EVIDENCE_LIMIT_EXCEEDED")
    if len(canonical_bytes(request)) > limits["max_artifact_bytes"]:
        blockers.append("POLICY_ARTIFACT_LIMIT_EXCEEDED")
    irreversible = any(item["reversibility"] == "irreversible" for item in request["options"])
    unknown = any(item["reversibility"] == "unknown" for item in request["options"])
    needs_approval = approval_required or irreversible
    if needs_approval and (expected["approval_sha256"] is None or expected["approval_sha256"] != current_approval_sha256):
        blockers.append("APPROVAL_REQUIRED")
    if not transaction_gates_valid:
        blockers.append("TRANSACTION_GATE_INVALID")
    if constitution_conflict:
        blockers.append("CONSTITUTION_CONFLICT")
    if blockers:
        return _result("block", blockers, bindings)
    escalations: list[str] = []
    if unknown:
        disposition = policy["risk"]["unknown_reversibility"]
        (escalations if disposition == "escalate" else blockers).append("REVERSIBILITY_UNKNOWN")
    if any(item["status"] in {"owner-input-required", "unknown"} for item in request["assumptions"]):
        escalations.append("OWNER_INPUT_REQUIRED")
    if confidence == "low":
        disposition = policy["risk"]["low_confidence"]
        (escalations if disposition == "escalate" else blockers).append("LOW_CONFIDENCE")
    if blockers:
        return _result("block", blockers, bindings)
    if escalations:
        return _result("escalate", escalations, bindings)
    return _result("proceed", ["AUTHORITY_VALID"], bindings)
