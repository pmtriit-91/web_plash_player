#!/usr/bin/env python3
"""Eight focused checks for lifecycle update-planning extraction."""

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
from types import SimpleNamespace

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_lifecycle")
owner = importlib.import_module("lifecycle.update_planning")
NAMES = ("collect_application_entries", "dirty_agent_paths", "plan_update")
ORDERED_AST_SHA256 = "fff50aa6ce8df65d8fab5297fb7fd10b34e62e2cc0ae570a5ddc592732fc0e21"


# fmt: off
def main() -> None:
    cases: list[dict[str, object]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/update_planning.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-update-planning-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    check("facade-reexports-exact-identities", all(getattr(facade, name) is getattr(owner, name) for name in NAMES))
    signatures = {name: inspect.signature(getattr(owner, name)) for name in NAMES}
    check("signatures-and-protected-scopes-remain-stable", signatures["collect_application_entries"].parameters["root"].default == owner.ROOT and str(signatures["dirty_agent_paths"]) == "() -> 'dict[str, list[str]]'" and str(signatures["plan_update"]) == "(args: 'argparse.Namespace') -> 'dict[str, Any]'" and facade.PROTECTED_APPLICATION_SCOPES is owner.PROTECTED_APPLICATION_SCOPES)
    check("owner-has-no-reverse-facade-import", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source)
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entry = {item["entrypoint"]: item for item in topology["entries"]}["_tools/lifecycle/update_planning.py"]
    check("topology-routes-update-planning-owner", entry["focused_shard"] == "_tools/lifecycle/test_update_planning.py" and entry["depends_on"] == ["_tools/lifecycle/release_tree.py", "_tools/lifecycle/shared.py"])
    with tempfile.TemporaryDirectory(prefix="lifecycle-update-planning-") as temporary:
        root = Path(temporary)
        expected = {"project/data.txt", "skills/project-memory/m.md", "skills/project-local/l.py"}
        for relative in [*expected, "core/ignored.txt"]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        inventory = owner.collect_application_entries(root)
        check("protected-application-inventory-remains-bounded", set(inventory) == expected and all(item["type"] == "file" and len(item["sha256"]) == 64 for item in inventory.values()))
    original_run, original_policy, original_classify = owner.subprocess.run, owner.ownership_policy, owner.classify
    owner.subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=" M .agents/core/a\nR  .agents/project/old -> .agents/project/new\n?? .agents/_manifest/base-release-manifest.json\n?? .agents/mystery\n")
    owner.ownership_policy = dict
    owner.classify = lambda path, policy: "application" if path.startswith("project/") else "manifest" if path.startswith("_manifest/") else "release" if path.startswith("core/") else "unclassified"
    dirty = owner.dirty_agent_paths()
    owner.subprocess.run, owner.ownership_policy, owner.classify = original_run, original_policy, original_classify
    check("dirty-path-grouping-and-rename-parity", dirty == {"release": ["_manifest/base-release-manifest.json", "core/a"], "application": ["project/new", "project/old"], "runtime": [], "unclassified": ["mystery"]})
    original_verify, original_load = owner.verify_release_tree, owner.load_json
    owner.verify_release_tree = lambda path: {"ok": False, "reason_codes": ["FIXTURE_INVALID"], "manifest_entries": {}}
    invalid = owner.plan_update(argparse.Namespace(source="fixture"))
    owner.verify_release_tree = lambda path: {"ok": True, "root": "fixture", "manifest_entries": {}}
    owner.load_json = lambda path, default=None: None
    missing = owner.plan_update(argparse.Namespace(source="fixture"))
    owner.verify_release_tree, owner.load_json = original_verify, original_load
    check("plan-failures-preserve-precedence-and-zero-write", invalid["reason_codes"] == ["SOURCE_RELEASE_INVALID", "FIXTURE_INVALID"] and missing["reason_codes"] == ["CURRENT_MANIFEST_MISSING"] and invalid["writes_performed"] is False and missing["writes_performed"] is False)
    result = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
