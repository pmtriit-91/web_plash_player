#!/usr/bin/env python3
"""Eight focused checks for lifecycle builders and CLI extraction."""

from __future__ import annotations

import argparse
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
owner = importlib.import_module("lifecycle.builders")
NAMES = ("purity_scan", "build_manifest", "build_adapter_fingerprint", "main")
ORDERED_AST_SHA256 = "74ef00d058ca827cd62e6962ea7238bef9ed104844764c35306ad4c2eca3052e"


# fmt: off
def main() -> None:
    cases: list[dict[str, object]] = []
    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/builders.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-builders-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    signatures = {name: str(inspect.signature(getattr(owner, name))) for name in NAMES}
    check("facade-identities-and-signatures-remain-stable", all(getattr(facade, name) is getattr(owner, name) for name in NAMES) and signatures == {"purity_scan": "(entries: 'dict[str, dict[str, Any]]', forbidden_tokens: 'list[str]') -> 'list[dict[str, str]]'", "build_manifest": "(args: 'argparse.Namespace') -> 'dict[str, Any]'", "build_adapter_fingerprint": "(args: 'argparse.Namespace') -> 'dict[str, Any]'", "main": "() -> 'None'"})
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    route = entries["_tools/lifecycle/builders.py"]
    check("dependency-direction-and-topology-remain-bounded", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source and route["focused_shard"] == "_tools/lifecycle/test_builders.py" and route["depends_on"] == ["_tools/lifecycle/shared.py", "_tools/lifecycle/release_tree.py", "_tools/lifecycle/core_validation.py", "_tools/lifecycle/binding_validation.py", "_tools/lifecycle/health.py", "_tools/lifecycle/update_planning.py", "_tools/lifecycle/update_transaction.py"] and "_tools/lifecycle/builders.py" in entries["_tools/agent_os_lifecycle.py"]["depends_on"])

    with tempfile.TemporaryDirectory(prefix="lifecycle-builders-purity-") as temporary:
        root = Path(temporary)
        (root / "visible.txt").write_text("Secret TOKEN", encoding="utf-8")
        (root / "ignored.bin").write_text("secret", encoding="utf-8")
        original_root = owner.ROOT
        owner.ROOT = root
        findings = owner.purity_scan({"visible.txt": {"type": "file"}, "ignored.bin": {"type": "file"}, "link": {"type": "symlink"}}, [" token ", "SECRET", ""])
        owner.ROOT = original_root
        check("purity-scan-normalization-and-file-boundary-remain-stable", findings == [{"path": "visible.txt", "token": "secret"}, {"path": "visible.txt", "token": "token"}] and owner.purity_scan({}, []) == [])

    no_confirm = owner.build_manifest(argparse.Namespace(confirm=False))
    incomplete = owner.build_manifest(argparse.Namespace(confirm=True, source_locator="fixture", source_commit=None))
    check("manifest-write-boundary-fails-closed", no_confirm["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and incomplete["reason_codes"] == ["SOURCE_PROVENANCE_ARGUMENTS_INCOMPLETE"])

    with tempfile.TemporaryDirectory(prefix="lifecycle-builders-manifest-") as temporary:
        root = Path(temporary) / ".agents"
        originals = (owner.ROOT, owner.MANIFEST_PATH, owner.collect_release_entries, owner.ownership_policy, owner.git_output, owner.utc_now, owner.purity_scan)
        owner.ROOT, owner.MANIFEST_PATH = root, root / "_manifest/base-release-manifest.json"
        owner.collect_release_entries = lambda: ({"README.md": {"path": "README.md", "type": "file", "sha256": "stable"}}, [])
        owner.ownership_policy = lambda: {"application_owned_scopes": ["project/**"], "runtime_scopes": ["_runtime/**"]}
        owner.git_output, owner.utc_now, owner.purity_scan = lambda *args: "a" * 40, lambda: "2026-08-07T00:00:00Z", lambda entries, tokens: []
        built = owner.build_manifest(argparse.Namespace(confirm=True, source_locator=None, source_commit=None, forbid_token=[], release_id="fixture"))
        manifest = json.loads(owner.MANIFEST_PATH.read_text())
        owner.ROOT, owner.MANIFEST_PATH, owner.collect_release_entries, owner.ownership_policy, owner.git_output, owner.utc_now, owner.purity_scan = originals
        check("working-manifest-build-remains-atomic-and-ordered", built == {"ok": True, "manifest": "_manifest/base-release-manifest.json", "release_id": "fixture", "provenance_status": "working-baseline", "entries": 1} and manifest["provenance"]["created_from_repository_head"] == "a" * 40 and manifest["excluded_scopes"] == ["project/**", "_runtime/**"] and manifest["entries"][0]["path"] == "README.md")

    with tempfile.TemporaryDirectory(prefix="lifecycle-builders-fingerprint-") as temporary:
        root = Path(temporary) / ".agents"
        binding = {"schema_version": 1, "project_id": "fixture", "last_verified_at": "2026-08-07T00:00:00Z", "last_verified_commit": None}
        originals = (owner.ROOT, owner.BINDING_PATH, owner.FINGERPRINT_PATH, owner.load_json, owner.validate_binding, owner.expected_adapter_digests)
        owner.ROOT, owner.BINDING_PATH, owner.FINGERPRINT_PATH = root, root / "project/project-binding.json", root / "project/adapter-fingerprint.json"
        owner.load_json, owner.validate_binding, owner.expected_adapter_digests = lambda path, default=None: binding, lambda value: ([], ["warning"]), lambda value: {"digest": "stable"}
        rejected = owner.build_adapter_fingerprint(argparse.Namespace(confirm=False))
        built = owner.build_adapter_fingerprint(argparse.Namespace(confirm=True))
        fingerprint = json.loads(owner.FINGERPRINT_PATH.read_text())
        owner.ROOT, owner.BINDING_PATH, owner.FINGERPRINT_PATH, owner.load_json, owner.validate_binding, owner.expected_adapter_digests = originals
        check("adapter-fingerprint-boundary-and-atomic-build-remain-stable", rejected["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and built["project_id"] == "fixture" and built["warnings"] == ["warning"] and fingerprint["digests"] == {"digest": "stable"})

    captured: list[dict[str, object]] = []
    originals = (sys.argv, owner.doctor, owner.dump)
    sys.argv, owner.doctor, owner.dump = ["agent_os_lifecycle.py", "doctor"], lambda: {"ok": True, "state": "BOUND"}, captured.append
    try:
        owner.main()
    except SystemExit as error:
        exit_code = error.code
    finally:
        sys.argv, owner.doctor, owner.dump = originals
    check("cli-dispatch-and-exit-contract-remain-stable", exit_code == 0 and captured == [{"ok": True, "state": "BOUND"}])

    result = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
