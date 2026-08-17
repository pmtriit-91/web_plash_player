#!/usr/bin/env python3
"""Eight focused checks for capability state-planning extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
owner = importlib.import_module("capability_lifecycle.state_planning")
integration = importlib.import_module("capability_lifecycle.integration_builder")
manifest = importlib.import_module("capability_lifecycle.manifest_builder")
candidate_validation = importlib.import_module(
    "capability_lifecycle.candidate_validation"
)
telemetry = importlib.import_module("capability_lifecycle.telemetry")
base = importlib.import_module("capability_lifecycle.shared")

# fmt: off
METHODS = ("diff_for", "create_plan", "plan_integration", "compare_update", "plan_state_change")
EXPECTED_AST = "0f1387b550544a635a85e7bcc30690b8bd862126082e7185639eba48d438386b"


class Harness(facade.CapabilityLifecycleService):
    def __init__(self, root: Path) -> None:
        self.plans = root / "plans"; self.plans.mkdir()
        self.before: dict[str, bytes] = {"a.txt": b"old"}
        self.integration_result: tuple[dict[str, bytes], dict[str, object], list[dict[str, object]]] = ({"a.txt": b"new"}, {"operation": "capability-integrate"}, [])
        self.docs: dict[str, object] = {facade.DESCRIPTORS: {"capabilities": []}, facade.LIFECYCLE_LEDGER: {"receipts": []}}
        self.runtime_records: list[dict[str, object]] = []

    def clean_head(self) -> tuple[str | None, list[str]]: return "a" * 40, []
    def now(self) -> datetime: return datetime(2026, 8, 7, tzinfo=timezone.utc)
    def read_bytes(self, relative: str) -> bytes | None: return self.before.get(relative)
    def protected_digest(self) -> str: return "protected"
    def build_integration(self, candidate: object, assembly: object, created_at: str) -> tuple[dict[str, bytes], dict[str, object], list[dict[str, object]]]: return self.integration_result
    def document(self, relative: str, default: object) -> object: return deepcopy(self.docs.get(relative, default))
    def validate_candidate_for_activation(self, candidate: object) -> list[dict[str, object]]: return candidate.get("errors", []) if isinstance(candidate, dict) else [{"code": "INVALID"}]
    def base_documents(self) -> dict[str, object]: return deepcopy(self.docs)
    def validate_snapshot(self, documents: dict[str, object], files: dict[str, bytes]) -> list[dict[str, object]]: return []
    def render_working_manifest(self, desired: dict[str, bytes | None], created_at: str, release_key: str) -> bytes: return b"manifest"
    def runtime_candidate_records(self) -> list[dict[str, object]]: return deepcopy(self.runtime_records)


def descriptor(identifier: str = "widget", state: str = "active") -> dict[str, object]:
    return {"id": identifier, "version": "1", "lifecycle_state": state, "integration_mode": "adapt-local-skill", "source": {"commit": "old", "license": "MIT"}, "decision_ref": "decision", "eval": {"case_ids": ["case"]}}


def main() -> None:
    cases: list[dict[str, object]] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8")); mixin = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "StatePlanningMixin")
    nodes = {node.name: node for node in mixin.body if isinstance(node, ast.FunctionDef)}; selected = [nodes[name] for name in METHODS]
    digest = hashlib.sha256("\n".join(ast.dump(node, include_attributes=False) for node in selected).encode()).hexdigest()
    check("exact-family-ast-and-lines", digest == EXPECTED_AST and sum(node.end_lineno - node.lineno + 1 for node in selected) == 157)
    service_class = facade.CapabilityLifecycleService
    expected_mro = (owner.StatePlanningMixin, integration.IntegrationBuilderMixin, manifest.ManifestBuilderMixin, candidate_validation.CandidateValidationMixin, telemetry.TelemetryMixin, base.CapabilityLifecycleBase)
    check("facade-identity-mro-and-constructor", all(getattr(service_class, name) is getattr(owner.StatePlanningMixin, name) for name in METHODS) and service_class.__mro__[-7:-1] == expected_mro and inspect.signature(service_class) == inspect.signature(base.CapabilityLifecycleBase))

    with tempfile.TemporaryDirectory(prefix="state-planning-") as directory:
        service = Harness(Path(directory))
        diff = service.diff_for(b"old\n", b"new\n", "x.txt")
        check("exact-diff-binds-agent-paths", diff.startswith("--- a/.agents/x.txt\n+++ b/.agents/x.txt\n") and "-old\n+new\n" in diff)
        valid = service.create_plan({"a.txt": b"new"}, {"operation": "test"}, 60)
        no_changes = service.create_plan({"a.txt": b"old"}, {}, 60); bad_expiry = service.create_plan({"a.txt": b"new"}, {}, 59)
        plan = valid["plan"]
        check("create-plan-is-hashed-bounded-and-reviewable", valid["ok"] and len(plan["plan_id"]) == 24 and plan["input"]["git_head"] == "a" * 40 and plan["input"]["protected_digest"] == "protected" and plan["input"]["changes"][0]["before_sha256"] == facade.sha256_bytes(b"old") and (service.plans / f"{plan['plan_id']}.json").is_file() and no_changes["reason_codes"] == ["NO_CHANGES"] and bad_expiry["reason_codes"] == ["PLAN_EXPIRY_INVALID"])
        integrated = service.plan_integration({}, {}, 60); service.integration_result = ({}, {}, [{"code": "BLOCKED"}]); rejected = service.plan_integration({}, {})
        check("integration-planning-dispatches-and-fails-closed", integrated["ok"] and integrated["plan"]["input"]["operation"] == "capability-integrate" and rejected == {"ok": False, "reason_codes": ["INTEGRATION_VALIDATION_FAILED"], "errors": [{"code": "BLOCKED"}]})
        service.docs[facade.DESCRIPTORS] = {"capabilities": [descriptor()]}
        same = service.compare_update("widget", {"id": "candidate", "source": {"commit": "old", "license": "MIT", "snapshot_sha256": "s"}, "recommendation": "adapt-local-skill"})
        newer = service.compare_update("widget", {"id": "candidate", "source": {"commit": "new", "license": "MIT", "snapshot_sha256": "s"}, "recommendation": "adapt-local-skill"})
        missing = service.compare_update("missing", {})
        check("update-comparison-preserves-old-pin-until-apply", same["same_pin"] and not same["eligible_for_plan"] and newer["eligible_for_plan"] and newer["old_pin_remains_active_until_apply"] and missing["reason_codes"] == ["CAPABILITY_NOT_FOUND"])
        service.runtime_records = [{"target_capability_id": "widget", "state": "active", "decision_history": []}]
        changed = service.plan_state_change("widget", "deprecated", expiry_seconds=60); payload = changed["plan"]["input"]
        self_ref = service.plan_state_change("widget", "deprecated", "widget"); invalid = service.plan_state_change("!", "active")
        receipt_change = next(item for item in payload["changes"] if item["path"] == facade.LIFECYCLE_LEDGER)
        receipt = json.loads(facade.decoded(receipt_change["after_base64"]))["receipts"][0]
        service.docs[facade.DESCRIPTORS] = {"capabilities": [descriptor(), descriptor("replacement", "disabled")]}
        replacement = service.plan_state_change("widget", "deprecated", "replacement")
        check("state-change-is-receipted-and-fails-closed", changed["ok"] and payload["state"] == "deprecated" and payload["runtime_candidate"]["state"] == "deprecated" and receipt["action"] == "state-change" and receipt["content_sha256"] == facade.receipt_hash(receipt) and self_ref["reason_codes"] == ["REPLACEMENT_CAPABILITY_SELF_REFERENCE"] and invalid["reason_codes"] == ["STATE_CHANGE_INVALID"] and replacement["reason_codes"] == ["REPLACEMENT_CAPABILITY_NOT_ACTIVE"] and service.plan_state_change("widget", "deprecated", "missing")["reason_codes"] == ["REPLACEMENT_CAPABILITY_NOT_FOUND"])
        topology = json.loads((TOOLS_ROOT / "capability_lifecycle/topology.json").read_text()); entry = next(item for item in topology["entries"] if item.get("entrypoint", "").endswith("state_planning.py"))
        check("one-way-topology-and-discoverability", entry["depends_on"] == ["_tools/capability_lifecycle/candidate_validation.py", "_tools/capability_lifecycle/integration_builder.py", "_tools/capability_lifecycle/manifest_builder.py", "_tools/capability_lifecycle/shared.py"] and entry["focused_shard"].endswith("test_state_planning.py") and "agent_os_capability_lifecycle" not in Path(owner.__file__).read_text())
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(bool(item["passed"]) for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__": main()
# fmt: on
