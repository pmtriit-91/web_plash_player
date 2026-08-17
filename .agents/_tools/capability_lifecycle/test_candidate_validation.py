#!/usr/bin/env python3
"""Eight focused checks for candidate-validation extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
owner = importlib.import_module("capability_lifecycle.candidate_validation")
telemetry = importlib.import_module("capability_lifecycle.telemetry")
base = importlib.import_module("capability_lifecycle.shared")

# fmt: off
METHODS = ("validate_candidate_for_activation", "validate_descriptor", "inventory_files", "prepare_assembly_files", "route_from_documents", "validate_shadow", "validate_snapshot")
CONSTANTS = ("SCRIPT_SUFFIXES", "ALLOWED_MODES", "ALLOWED_STATES", "PERMISSION_FIELDS")
EXPECTED_AST = "09bb74c8846d87461006a3fe4b26b52c857bea9472fe792c2738f1cadef58caa"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class Harness(facade.CapabilityLifecycleService):
    def __init__(self) -> None:
        self.docs = {"research/research-policy.json": {"license": {"vendor_allowlist": ["MIT"]}}, "evals/agent-os-evals.json": {"cases": []}}

    def document(self, relative: str, default: Any) -> Any:
        return self.docs.get(relative, default)

    def budget(self) -> int:
        return 64

    def path(self, relative: str) -> Path:
        return Path("/definitely-missing") / relative

    def read_bytes(self, relative: str) -> bytes | None:
        return None


def candidate() -> dict[str, Any]:
    files = [{"path": "SKILL.md", "type": "file", "sha256": facade.sha256_bytes(b"skill")}]
    return {"schema_version": 1, "id": "widget", "state": "recommended", "source": {"commit": COMMIT, "license": "MIT", "snapshot_sha256": facade.sha256_bytes(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())}, "inventory": {"files": files}, "gate_results": [], "shadow_eval": {"status": "passing"}, "recommendation": "adapt-local-skill", "decision_history": [{"state": "recommended"}]}


def descriptor() -> dict[str, Any]:
    return {"id": "widget", "version": "1", "lifecycle_state": "active", "summary": "Widget routing capability.", "when_to_use": ["widget work"], "not_for": ["other work"], "integration_mode": "native", "source": {}, "risk": {}, "permissions": {key: "none" for key in owner.PERMISSION_FIELDS}, "dependencies": [], "conflicts": [], "token_profile": {}, "eval": {"status": "passing", "case_ids": ["route-widget"]}, "decision_ref": "decision-widget"}


def main() -> None:
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8"))
    mixin = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "CandidateValidationMixin")
    nodes = {node.name: node for node in mixin.body if isinstance(node, ast.FunctionDef)}
    selected = [nodes[name] for name in METHODS]
    digest = hashlib.sha256("\n".join(ast.dump(node, include_attributes=False) for node in selected).encode()).hexdigest()
    check("exact-family-ast-and-lines", digest == EXPECTED_AST and sum(node.end_lineno - node.lineno + 1 for node in selected) == 246)
    service_class = facade.CapabilityLifecycleService
    check("facade-reexports-owner-with-stable-constructor", all(getattr(service_class, name) is getattr(owner.CandidateValidationMixin, name) for name in METHODS) and all(getattr(facade, name) is getattr(owner, name) for name in CONSTANTS) and service_class.__mro__[-4:-1] == (owner.CandidateValidationMixin, telemetry.TelemetryMixin, base.CapabilityLifecycleBase) and inspect.signature(service_class) == inspect.signature(base.CapabilityLifecycleBase))

    service = Harness()
    good = candidate()
    blocked = candidate()
    blocked.update({"state": "blocked", "recommendation": "reject", "shadow_eval": {"status": "failing"}})
    blocked["source"] = {"commit": "short", "license": "GPL", "snapshot_sha256": "0" * 64}
    blocked["gate_results"] = [{"gate": "license", "status": "block"}]
    codes = {item["code"] for item in service.validate_candidate_for_activation(blocked)}
    check("candidate-activation-gates-provenance-license-snapshot-and-shadow", service.validate_candidate_for_activation(good) == [] and {"CANDIDATE_NOT_RECOMMENDED", "INTEGRATION_MODE_NOT_ACTIVATABLE", "CANDIDATE_GATE_NOT_PASSING", "FULL_COMMIT_REQUIRED", "LICENSE_NOT_ALLOWED", "CANDIDATE_SNAPSHOT_HASH_INVALID", "SHADOW_EVAL_NOT_PASSING"} <= codes)

    valid_descriptor = descriptor()
    invalid_descriptor = descriptor()
    invalid_descriptor.update({"id": "bad id", "lifecycle_state": "unknown", "summary": "x", "permissions": {}, "eval": {}})
    descriptor_codes = {item["code"] for item in service.validate_descriptor(invalid_descriptor)}
    check("descriptor-schema-state-permissions-and-eval-are-closed", service.validate_descriptor(valid_descriptor) == [] and {"CAPABILITY_ID_INVALID", "CAPABILITY_STATE_INVALID", "SUMMARY_INVALID", "PERMISSIONS_INVALID", "CAPABILITY_EVAL_NOT_PASSING"} <= descriptor_codes)

    traversal = {"files": [{"target": "skills/widget/../../project/config.json", "content": "x"}]}
    executable = {"files": [{"target": "skills/widget/run.py", "content": "print(1)"}]}
    vendor = {"files": [{"source_path": "SKILL.md", "target": "vendor/widget/SKILL.md", "content": "changed"}, {"source_path": "SKILL.md", "target": "vendor/widget/SKILL.md", "content": "changed"}]}
    assembly_codes = {item["code"] for payload, mode in ((traversal, "adapt-local-skill"), (executable, "adapt-local-skill"), (vendor, "vendor-pin")) for item in service.prepare_assembly_files(good, payload, mode, "widget")[1]}
    check("assembly-rejects-traversal-executables-duplicates-and-byte-drift", {"ASSEMBLY_TARGET_UNSAFE", "EXECUTABLE_CONTENT_NOT_ACTIVATABLE", "ASSEMBLY_TARGET_DUPLICATED", "VENDOR_BYTE_PROVENANCE_MISMATCH", "VENDOR_LICENSE_FILE_REQUIRED"} <= assembly_codes)

    registry = {"capabilities": {"widget": {"triggers": ["widget release"]}}, "vendor_skills": {}}
    descriptors = {"capabilities": [valid_descriptor]}
    check("routing-and-shadow-validation-preserve-positive-negative-parity", service.route_from_documents("widget release", registry, descriptors) == "widget" and service.route_from_documents("prepare soup", registry, descriptors) == "standard_feature" and service.validate_shadow("widget", registry, descriptors, {"positive": ["widget release"], "negative": ["prepare soup"]}) == [] and service.validate_shadow("widget", registry, descriptors, {"positive": [], "negative": []}) == [{"code": "POSITIVE_AND_NEGATIVE_ROUTING_CASES_REQUIRED"}])

    documents = {facade.REGISTRY: {"capabilities": {"ghost": {}}, "vendor_skills": {}}, facade.DESCRIPTORS: {"capabilities": []}, facade.CAPABILITY_DECISIONS: {"receipts": [{"id": "bad"}]}, facade.ROUTING_CORPUS: {"cases": []}, facade.VENDOR_LOCK: {"packages": [{"id": "vendor", "root": "vendor/x", "commit": "short", "license": None}]}, facade.LIFECYCLE_LEDGER: {"receipts": [{"id": "bad"}]}}
    snapshot_codes = {item["code"] for item in service.validate_snapshot(documents, {"skills/orphan/SKILL.md": b"x"})}
    check("snapshot-covers-routes-decisions-orphans-vendor-and-lifecycle", {"ROUTE_DESCRIPTOR_COVERAGE_INVALID", "CAPABILITY_DECISION_INVALID", "INSTALLED_SKILL_ORPHANED", "VENDOR_PACKAGE_PROVENANCE_INVALID", "LIFECYCLE_RECEIPT_INVALID"} <= snapshot_codes)

    topology = json.loads((TOOLS_ROOT / "capability_lifecycle/topology.json").read_text())
    entry = next((item for item in topology["entries"] if item.get("entrypoint", "").endswith("candidate_validation.py")), {})
    check("one-way-topology-is-discoverable", entry.get("focused_shard", "").endswith("test_candidate_validation.py") and entry.get("depends_on") == ["_tools/agent_os_capabilities.py", "_tools/agent_os_research.py", "_tools/capability_lifecycle/platform_privacy.py", "_tools/capability_lifecycle/shared.py"] and "agent_os_capability_lifecycle" not in Path(owner.__file__).read_text())
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
# fmt: on
