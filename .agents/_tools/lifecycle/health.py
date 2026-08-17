"""Read-only lifecycle, adapter, bridge, and Genesis health orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_os_genesis import doctor as genesis_doctor
from agent_os_genesis_transactions import GenesisService
from lifecycle.binding_validation import (
    adapter_reason_codes,
    expected_adapter_digests,
    validate_binding,
    validate_fingerprint,
)
from lifecycle.core_validation import verify_core
from lifecycle.shared import load_json

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent
VERSION = "9.1.0"
BINDING_PATH = ROOT / "project" / "project-binding.json"
FINGERPRINT_PATH = ROOT / "project" / "adapter-fingerprint.json"
ROOT_BRIDGE_PATH = PROJECT_ROOT / "AGENTS.md"


# fmt: off
def verify_adapter() -> dict[str, Any]:
    if not BINDING_PATH.exists():
        return {
            "ok": False,
            "state": "UNBOUND",
            "binding": BINDING_PATH.relative_to(ROOT).as_posix(),
            "reason_codes": ["BINDING_MISSING"],
            "errors": [],
            "warnings": [],
        }
    binding = load_json(BINDING_PATH, None)
    if not isinstance(binding, dict):
        return {
            "ok": False,
            "state": "DEGRADED",
            "reason_codes": ["BINDING_SCHEMA_INVALID"],
            "errors": ["Binding is not valid JSON object data."],
            "warnings": [],
        }

    errors, warnings = validate_binding(binding)
    errors.extend(validate_fingerprint(binding))
    return {
        "ok": not errors,
        "state": "BOUND" if not errors else "DEGRADED",
        "project_id": binding.get("project_id"),
        "reason_codes": adapter_reason_codes(errors),
        "errors": errors,
        "warnings": warnings,
        "fingerprint": FINGERPRINT_PATH.relative_to(ROOT).as_posix(),
        "expected_digests": expected_adapter_digests(binding),
    }


def verify_bridge() -> dict[str, Any]:
    if not ROOT_BRIDGE_PATH.is_file():
        return {"ok": False, "reason_code": "CLIENT_BRIDGE_MISSING", "path": "AGENTS.md"}
    try:
        content = ROOT_BRIDGE_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"ok": False, "reason_code": "CLIENT_BRIDGE_INVALID", "path": "AGENTS.md"}
    if ".agents/AGENTS.md" not in content:
        return {"ok": False, "reason_code": "CLIENT_BRIDGE_INVALID", "path": "AGENTS.md"}
    return {"ok": True, "path": "AGENTS.md"}


def doctor() -> dict[str, Any]:
    core = verify_core()
    adapter = verify_adapter()
    bridge = verify_bridge()
    genesis_source = genesis_doctor()
    genesis_projection = GenesisService().projection_status()
    reasons = [*core.get("reason_codes", []), *adapter.get("reason_codes", [])]
    if not bridge.get("ok"):
        reasons.append(str(bridge.get("reason_code")))
    if adapter.get("state") == "UNBOUND":
        state = "UNBOUND"
    elif core.get("ok") and adapter.get("ok") and bridge.get("ok"):
        state = "BOUND"
    else:
        state = "DEGRADED"
    return {
        "ok": state == "BOUND",
        "state": state,
        "agent_os_version": VERSION,
        "reason_codes": list(dict.fromkeys(reasons)),
        "core": core,
        "adapter": adapter,
        "client_bridge": bridge,
        "genesis": {
            "source": genesis_source,
            "projection": genesis_projection,
            "constitutional_authority_available": (
                genesis_source.get("state") == "confirmed"
                and genesis_projection.get("ok") is True
            ),
        },
        "allowed": ["read-only audit", "doctor", "verify-core", "verify-adapter"]
        if state != "BOUND"
        else ["normal capabilities remain subject to user intent and safety policy"],
        "blocked": ["Project Memory authority", "adapter commands", "project mutation"]
        if state != "BOUND"
        else [],
    }
