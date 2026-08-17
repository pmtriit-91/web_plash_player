#!/usr/bin/env python3
"""Eight focused checks for lifecycle health-orchestration extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_lifecycle")
owner = importlib.import_module("lifecycle.health")
NAMES = ("verify_adapter", "verify_bridge", "doctor")
ORDERED_AST_SHA256 = "09a7146e0b43fdc32aa69c7a23da93bb494cbc46ec5dd8250ae7ac10033687c8"


# fmt: off
def main() -> None:
    cases: list[dict[str, object]] = []
    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/health.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-health-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    check("facade-reexports-exact-identities", all(getattr(facade, name) is getattr(owner, name) for name in NAMES))
    signatures = {name: str(inspect.signature(getattr(owner, name))) for name in NAMES}
    check("public-signatures-remain-stable", signatures == {name: "() -> 'dict[str, Any]'" for name in NAMES})
    check("owner-has-no-reverse-facade-import", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source)
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    entry = entries["_tools/lifecycle/health.py"]
    dependencies = ["_tools/lifecycle/core_validation.py", "_tools/lifecycle/binding_validation.py", "_tools/agent_os_genesis.py", "_tools/agent_os_genesis_transactions.py"]
    check("topology-routes-health-owner", entry["depends_on"] == dependencies and entry["focused_shard"] == "_tools/lifecycle/test_health.py" and "_tools/lifecycle/health.py" in entries["_tools/agent_os_lifecycle.py"]["depends_on"])

    with tempfile.TemporaryDirectory(prefix="lifecycle-health-adapter-") as temporary:
        root = Path(temporary) / ".agents"
        binding_path = root / "project/project-binding.json"
        binding_path.parent.mkdir(parents=True)
        originals = (owner.ROOT, owner.BINDING_PATH, owner.FINGERPRINT_PATH, owner.load_json, owner.validate_binding, owner.validate_fingerprint, owner.adapter_reason_codes, owner.expected_adapter_digests)
        owner.ROOT, owner.BINDING_PATH, owner.FINGERPRINT_PATH = root, binding_path, root / "project/adapter-fingerprint.json"
        missing = owner.verify_adapter()
        binding_path.write_text("[]", encoding="utf-8")
        invalid = owner.verify_adapter()
        binding_path.write_text("{}", encoding="utf-8")
        owner.load_json = lambda path, default=None: {"project_id": "fixture"}
        owner.validate_binding = lambda binding: (["first"], ["warning"])
        owner.validate_fingerprint = lambda binding: ["second"]
        owner.adapter_reason_codes = lambda errors: ["ORDERED"] if errors == ["first", "second"] else ["BAD"]
        owner.expected_adapter_digests = lambda binding: {"digest": "stable"}
        validated = owner.verify_adapter()
        owner.ROOT, owner.BINDING_PATH, owner.FINGERPRINT_PATH, owner.load_json, owner.validate_binding, owner.validate_fingerprint, owner.adapter_reason_codes, owner.expected_adapter_digests = originals
        check("adapter-fails-closed-and-preserves-order", missing["state"] == "UNBOUND" and missing["reason_codes"] == ["BINDING_MISSING"] and invalid["reason_codes"] == ["BINDING_SCHEMA_INVALID"] and validated["errors"] == ["first", "second"] and validated["reason_codes"] == ["ORDERED"] and validated["warnings"] == ["warning"] and validated["expected_digests"] == {"digest": "stable"})

    with tempfile.TemporaryDirectory(prefix="lifecycle-health-bridge-") as temporary:
        path = Path(temporary) / "AGENTS.md"
        original = owner.ROOT_BRIDGE_PATH
        owner.ROOT_BRIDGE_PATH = path
        missing = owner.verify_bridge()
        path.write_bytes(b"\xff")
        invalid_encoding = owner.verify_bridge()
        path.write_text("read something else", encoding="utf-8")
        invalid_target = owner.verify_bridge()
        path.write_text("Read .agents/AGENTS.md first.", encoding="utf-8")
        valid = owner.verify_bridge()
        owner.ROOT_BRIDGE_PATH = original
        check("bridge-path-and-root-contract-remain-stable", missing["reason_code"] == "CLIENT_BRIDGE_MISSING" and invalid_encoding["reason_code"] == "CLIENT_BRIDGE_INVALID" and invalid_target["reason_code"] == "CLIENT_BRIDGE_INVALID" and valid == {"ok": True, "path": "AGENTS.md"})

    originals = (owner.verify_core, owner.verify_adapter, owner.verify_bridge, owner.genesis_doctor, owner.GenesisService)
    owner.verify_core = lambda: {"ok": False, "reason_codes": ["DUP"]}
    owner.verify_adapter = lambda: {"ok": False, "state": "UNBOUND", "reason_codes": ["DUP", "ADAPTER"]}
    owner.verify_bridge = lambda: {"ok": False, "reason_code": "BRIDGE"}
    owner.genesis_doctor = lambda: {"state": "draft"}
    owner.GenesisService = lambda: type("Projection", (), {"projection_status": lambda self: {"ok": False}})()
    unbound = owner.doctor()
    owner.verify_core = lambda: {"ok": True, "reason_codes": []}
    owner.verify_adapter = lambda: {"ok": True, "state": "BOUND", "reason_codes": []}
    owner.verify_bridge = lambda: {"ok": True}
    owner.genesis_doctor = lambda: {"state": "confirmed"}
    owner.GenesisService = lambda: type("Projection", (), {"projection_status": lambda self: {"ok": True}})()
    bound = owner.doctor()
    owner.verify_adapter = lambda: {"ok": False, "state": "DEGRADED", "reason_codes": ["ADAPTER"]}
    degraded = owner.doctor()
    owner.verify_core, owner.verify_adapter, owner.verify_bridge, owner.genesis_doctor, owner.GenesisService = originals
    check("doctor-precedence-and-genesis-disclosure-remain-stable", unbound["state"] == "UNBOUND" and unbound["reason_codes"] == ["DUP", "ADAPTER", "BRIDGE"] and not unbound["genesis"]["constitutional_authority_available"] and unbound["blocked"] and bound["state"] == "BOUND" and bound["ok"] and bound["genesis"]["constitutional_authority_available"] and bound["blocked"] == [] and degraded["state"] == "DEGRADED")

    result = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
