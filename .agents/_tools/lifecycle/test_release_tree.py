#!/usr/bin/env python3
"""Eight focused checks for lifecycle release-tree extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_lifecycle")
owner = importlib.import_module("lifecycle.release_tree")
shared = importlib.import_module("lifecycle.shared")
# fmt: off
NAMES = (
    "ownership_policy", "matches_scope", "classify", "symlink_within_release",
    "collect_release_entries", "collect_release_entries_at_commit",
    "configured_remote_urls", "verified_release_provenance", "manifest_entries",
    "verify_release_tree",
)
ORDERED_AST_SHA256 = "8f87f3858e8ef784c30fb0dcad6a3ce76431ce21962bb444704e6eeb5d35f724"


def main() -> None:
    cases: list[dict[str, object]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/release_tree.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-release-tree-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    check("facade-reexports-exact-identities", all(getattr(facade, name) is getattr(owner, name) for name in NAMES))
    constants = ("FULL_COMMIT", "FULL_SHA256", "FORBIDDEN_UPDATE_SCOPES")
    check("shared-constants-have-one-identity", all(getattr(facade, name) is getattr(owner, name) is getattr(shared, name) for name in constants))
    signatures = {name: inspect.signature(getattr(owner, name)) for name in NAMES}
    check("public-signatures-remain-stable", signatures["ownership_policy"].parameters["root"].default == owner.ROOT and str(signatures["verify_release_tree"]) == "(root: 'Path') -> 'dict[str, Any]'")
    check("owner-has-no-reverse-facade-import", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source)
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    check("topology-routes-release-tree-owner", entries["_tools/lifecycle/release_tree.py"]["focused_shard"] == "_tools/lifecycle/test_release_tree.py")
    parsed, errors = owner.manifest_entries({"entries": [{"path": "../bad", "type": "file", "sha256": "x" * 64}]})
    policy = owner.ownership_policy()
    check("classification-and-manifest-contracts-remain-closed", owner.matches_scope("project/a", "project/**") and owner.classify("project/a", policy) == "application" and not parsed and bool(errors))
    inventory, unclassified = owner.collect_release_entries(owner.ROOT)
    check("working-release-inventory-remains-valid", len(inventory) >= 344 and not unclassified)
    result = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
