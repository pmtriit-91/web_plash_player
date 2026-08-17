#!/usr/bin/env python3
"""Eight focused checks for lifecycle binding-validation extraction."""

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
owner = importlib.import_module("lifecycle.binding_validation")
NAMES = (
    "normalized_binding_sections",
    "expected_adapter_digests",
    "safe_relative",
    "contains_absolute_or_secret",
    "valid_timestamp",
    "unique_string_list",
    "resolve_json_pointer",
    "validate_binding",
    "validate_fingerprint",
    "adapter_reason_codes",
)
ORDERED_AST_SHA256 = "0a62a1e5c91d7a5742fd572f63476e741df3705a9fe8ee239b5d6f2ed2d0397d"


# fmt: off
def main() -> None:
    cases: list[dict[str, object]] = []
    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/binding_validation.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-binding-validation-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    check("facade-reexports-exact-identities", all(getattr(facade, name) is getattr(owner, name) for name in NAMES))
    signatures = {name: str(inspect.signature(getattr(owner, name))) for name in NAMES}
    check("public-signatures-remain-stable", signatures["safe_relative"] == "(raw: 'Any') -> 'tuple[Path | None, str | None]'" and signatures["validate_binding"] == "(binding: 'dict[str, Any]') -> 'tuple[list[str], list[str]]'" and signatures["adapter_reason_codes"] == "(errors: 'list[str]') -> 'list[str]'")
    check("owner-has-no-reverse-facade-import", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source)
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    entry = entries["_tools/lifecycle/binding_validation.py"]
    check("topology-routes-binding-validation-owner", entry["depends_on"] == ["_tools/lifecycle/shared.py"] and entry["focused_shard"] == "_tools/lifecycle/test_binding_validation.py" and "_tools/lifecycle/binding_validation.py" in entries["_tools/agent_os_lifecycle.py"]["depends_on"])

    normalized = owner.normalized_binding_sections({"project_id": "p", "repository": {"kind": "git", "root_markers": ["b", "a"], "remote_aliases": []}, "workspaces": [], "commands": [], "context_entrypoints": ["z", "a"]})
    pointer, pointer_error = owner.resolve_json_pointer({"a/b": ["x"]}, "/a~1b/0")
    findings = owner.contains_absolute_or_secret({"token": "x", "path": "/tmp/x"})
    check("pure-helper-contracts-remain-stable", normalized["project_identity"]["repository"]["root_markers"] == ["a", "b"] and pointer == "x" and pointer_error is None and findings == ["SENSITIVE_FIELD:$.token", "ABSOLUTE_PATH:$.path"] and owner.valid_timestamp("2026-08-07T00:00:00Z") and owner.unique_string_list(["a", "b"], non_empty=True))

    with tempfile.TemporaryDirectory(prefix="binding-validation-") as temporary:
        original_root = owner.PROJECT_ROOT
        owner.PROJECT_ROOT = Path(temporary)
        try:
            safe, safe_error = owner.safe_relative("child")
            outside, outside_error = owner.safe_relative("../outside")
            errors, warnings = owner.validate_binding({})
        finally:
            owner.PROJECT_ROOT = original_root
        check("path-and-binding-validation-remain-fail-closed", safe == (Path(temporary) / "child").resolve() and safe_error is None and outside is None and outside_error == "PATH_OUTSIDE_PROJECT" and errors[:4] == ["schema_version must equal 1", "project_id is invalid", "created_at must be an ISO-8601 timestamp", "last_verified_at must be an ISO-8601 timestamp"] and warnings == [])

    with tempfile.TemporaryDirectory(prefix="binding-fingerprint-") as temporary:
        binding = {"schema_version": 1, "project_id": "fixture", "repository": {"kind": "directory", "root_markers": []}, "workspaces": [], "commands": [], "context_entrypoints": [], "last_verified_at": "2026-08-07T00:00:00Z", "last_verified_commit": None}
        fingerprint = {"schema_version": 1, "project_id": "fixture", "binding_schema_version": 1, "algorithm": "sha256", "digests": owner.expected_adapter_digests(binding), "verified_at": binding["last_verified_at"], "verified_commit": None}
        path = Path(temporary) / "fingerprint.json"
        path.write_text(json.dumps(fingerprint), encoding="utf-8")
        original_path = owner.FINGERPRINT_PATH
        owner.FINGERPRINT_PATH = path
        try:
            fingerprint_errors = owner.validate_fingerprint(binding)
        finally:
            owner.FINGERPRINT_PATH = original_path
        reasons = owner.adapter_reason_codes(["project_id mismatch", "command 1 evidence", "context entrypoint missing", "adapter fingerprint invalid"])
        check("fingerprint-and-reason-code-order-remain-stable", fingerprint_errors == [] and reasons == ["PROJECT_IDENTITY_MISMATCH", "COMMAND_EVIDENCE_MISSING", "CONTEXT_ENTRY_MISSING", "ADAPTER_FINGERPRINT_INVALID", "ADAPTER_VALIDATION_FAILED"])

    result = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
