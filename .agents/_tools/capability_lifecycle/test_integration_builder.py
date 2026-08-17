#!/usr/bin/env python3
"""Eight focused checks for capability integration builder extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from copy import deepcopy
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
owner = importlib.import_module("capability_lifecycle.integration_builder")
manifest = importlib.import_module("capability_lifecycle.manifest_builder")
candidate_validation = importlib.import_module(
    "capability_lifecycle.candidate_validation"
)
telemetry = importlib.import_module("capability_lifecycle.telemetry")
base = importlib.import_module("capability_lifecycle.shared")

# fmt: off
EXPECTED_AST = "b3073a11430c22d7c0d76e3ba7fd33b9afcbe5316fae12c8f32001dd07d1e8da"
NOW = "2026-08-07T00:00:00Z"


def base_documents() -> dict[str, object]:
    return {
        facade.REGISTRY: {"capabilities": {}, "vendor_skills": {}},
        facade.DESCRIPTORS: {"capabilities": []},
        facade.CAPABILITY_DECISIONS: {"receipts": []},
        facade.LIFECYCLE_LEDGER: {"receipts": []},
        facade.CANDIDATES: {"candidates": []},
        facade.RESEARCH_DECISIONS: {"receipts": []},
        facade.VENDOR_LOCK: {"packages": []},
        facade.ROUTING_CORPUS: {"cases": []},
    }


class Harness(facade.CapabilityLifecycleService):
    def __init__(self) -> None:
        self.documents = base_documents()
        self.files = {"skills/widget/SKILL.md": b"skill"}
        self.calls: list[object] = []

    def validate_candidate_for_activation(self, candidate: dict[str, object]) -> list[dict[str, object]]: return []
    def prepare_assembly_files(self, candidate: dict[str, object], assembly: dict[str, object], mode: str, capability_id: str) -> tuple[dict[str, bytes], list[dict[str, object]]]: return self.files, []
    def base_documents(self) -> dict[str, object]: return deepcopy(self.documents)
    def validate_descriptor(self, descriptor: dict[str, object]) -> list[dict[str, object]]: return []
    def validate_shadow(self, capability_id: str, registry: dict[str, object], descriptors: dict[str, object], routing: dict[str, object]) -> list[dict[str, object]]: return []
    def validate_snapshot(self, documents: dict[str, object], files: dict[str, bytes]) -> list[dict[str, object]]: self.calls.append((documents, files)); return []
    def render_working_manifest(self, desired: dict[str, bytes | None], created_at: str, release_key: str) -> bytes: self.calls.append((desired, created_at, release_key)); return b"manifest"
    def read_bytes(self, relative: str) -> bytes | None: return b"guard"


def source(recommendation: str = "adapt-local-skill") -> dict[str, object]:
    return {"id": "widget-source", "recommendation": recommendation, "source": {"snapshot_sha256": "a" * 64, "repository": "https://example.invalid/widget", "commit": "b" * 40, "license": "MIT"}, "decision_history": []}


def assembly(mode: str = "adapt-local-skill") -> dict[str, object]:
    route = {"mode": "STANDARD", "triggers": ["widget"], "load": [], "checks": ["focused"]} if mode != "vendor-pin" else {"path": "vendor/widget-source/SKILL.md", "group": "tools", "role": "primary", "high_triggers": ["widget"]}
    return {"schema_version": 1, "candidate_id": "widget-source", "capability_id": "widget", "integration_mode": mode, "route": route, "routing": {"positive": ["widget"], "negative": ["other"]}, "descriptor": {}, "rationale": "Evidence-backed integration."}


def decoded(desired: dict[str, bytes], path: str) -> dict[str, object]: return json.loads(desired[path])


def main() -> None:
    cases: list[dict[str, object]] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8"))
    mixin = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "IntegrationBuilderMixin")
    method = next(item for item in mixin.body if isinstance(item, ast.FunctionDef) and item.name == "build_integration")
    digest = hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest()
    check("exact-family-ast-and-lines", digest == EXPECTED_AST and method.end_lineno - method.lineno + 1 == 203)
    service_class = facade.CapabilityLifecycleService
    expected_mro = (owner.IntegrationBuilderMixin, manifest.ManifestBuilderMixin, candidate_validation.CandidateValidationMixin, telemetry.TelemetryMixin, base.CapabilityLifecycleBase)
    check("facade-identity-mro-and-constructor", service_class.build_integration is owner.IntegrationBuilderMixin.build_integration and service_class.__mro__[-6:-1] == expected_mro and inspect.signature(service_class) == inspect.signature(base.CapabilityLifecycleBase))

    service = Harness()
    schema_codes = {item["code"] for item in service.build_integration(source(), {}, NOW)[2]}
    invalid = assembly(); invalid.update({"candidate_id": "wrong", "capability_id": "!", "integration_mode": "vendor-pin"})
    invalid_codes = {item["code"] for item in service.build_integration(source(), invalid, NOW)[2]}
    bad_route = assembly(); bad_route["route"] = {}
    route_codes = {item["code"] for item in service.build_integration(source(), bad_route, NOW)[2]}
    check("invalid-assembly-fields-and-routes-fail-closed", schema_codes == {"ASSEMBLY_SCHEMA_INVALID"} and {"ASSEMBLY_CANDIDATE_MISMATCH", "CAPABILITY_ID_INVALID", "ASSEMBLY_INTEGRATION_MODE_INVALID"} <= invalid_codes and route_codes == {"LOCAL_ROUTE_INVALID"})

    desired, metadata, errors = service.build_integration(source(), assembly(), NOW)
    desired_again, metadata_again, errors_again = Harness().build_integration(source(), assembly(), NOW)
    registry = decoded(desired, facade.REGISTRY); descriptors = decoded(desired, facade.DESCRIPTORS); decisions = decoded(desired, facade.CAPABILITY_DECISIONS); lifecycle = decoded(desired, facade.LIFECYCLE_LEDGER); corpus = decoded(desired, facade.ROUTING_CORPUS)
    check("local-integration-is-complete-and-deterministic", not errors and not errors_again and desired == desired_again and metadata == metadata_again and registry["capabilities"]["widget"]["mode"] == "STANDARD" and descriptors["capabilities"][0]["source"]["kind"] == "local" and decisions["receipts"][0]["decision"] == "adapt-local-skill" and lifecycle["receipts"][0]["action"] == "integrate" and corpus["cases"][0]["status"] == "passing")

    vendor_service = Harness(); vendor_service.files = {"vendor/widget-source/LICENSE": b"MIT", "vendor/widget-source/SKILL.md": b"vendor"}
    vendor_desired, vendor_metadata, vendor_errors = vendor_service.build_integration(source("vendor-pin"), assembly("vendor-pin"), NOW)
    package = decoded(vendor_desired, facade.VENDOR_LOCK)["packages"][0]
    check("vendor-pin-binds-route-files-and-license", not vendor_errors and vendor_metadata["integration_mode"] == "vendor-pin" and package["license_path"] == "vendor/widget-source/LICENSE" and package["files"] == {path: facade.sha256_bytes(content) for path, content in sorted(vendor_service.files.items())})

    update_service = Harness(); update_service.documents[facade.DESCRIPTORS] = {"capabilities": [{"id": "widget", "integration_mode": "adapt-local-skill", "decision_ref": "old-decision"}]}
    update_desired, update_metadata, update_errors = update_service.build_integration(source(), assembly(), NOW)
    changed = assembly("vendor-pin"); change_errors = update_service.build_integration(source("vendor-pin"), changed, NOW)[2]
    update_receipt = decoded(update_desired, facade.CAPABILITY_DECISIONS)["receipts"][0]
    check("updates-supersede-but-cannot-change-mode", not update_errors and update_metadata["operation"] == "capability-update" and update_receipt["supersedes"] == "old-decision" and {item["code"] for item in change_errors} == {"UPDATE_INTEGRATION_MODE_CHANGE_REJECTED"})

    check("downstream-contracts-guards-and-zero-write-proof", len(service.calls) == 2 and service.calls[1][1:] == (NOW, metadata["lifecycle_receipt_id"]) and desired[facade.MANIFEST] == b"manifest" and set(metadata["guard_hashes"].values()) == {facade.sha256_bytes(b"guard")} and metadata["runtime_candidate"]["state"] == "active")
    topology = json.loads((TOOLS_ROOT / "capability_lifecycle/topology.json").read_text())
    entry = next(item for item in topology["entries"] if item.get("entrypoint", "").endswith("integration_builder.py"))
    check("one-way-topology-and-discoverability", entry["depends_on"] == ["_tools/agent_os_research.py", "_tools/capability_lifecycle/candidate_validation.py", "_tools/capability_lifecycle/manifest_builder.py", "_tools/capability_lifecycle/platform_privacy.py", "_tools/capability_lifecycle/shared.py"] and entry["focused_shard"].endswith("test_integration_builder.py") and "agent_os_capability_lifecycle" not in Path(owner.__file__).read_text())
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(bool(item["passed"]) for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__": main()
# fmt: on
