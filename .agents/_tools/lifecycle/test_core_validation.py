#!/usr/bin/env python3
"""Eight focused checks for lifecycle Core-validation extraction."""

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
owner = importlib.import_module("lifecycle.core_validation")
transaction = importlib.import_module("lifecycle.update_transaction")
NAMES = ("verify_vendors", "parse_frontmatter", "validate_skills", "verify_core")
ORDERED_AST_SHA256 = "b4077a8d1bd38720723c1be020884d092edfa1c497dc340015caf8d6427b93fc"


# fmt: off
def main() -> None:
    cases: list[dict[str, object]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/core_validation.py").read_text(encoding="utf-8")
    nodes = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
    ordered = "\n".join(ast.dump(nodes[name], include_attributes=False) for name in NAMES)
    check("ordered-core-validation-ast-is-preserved", hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256)
    check("facade-reexports-exact-identities", all(getattr(facade, name) is getattr(owner, name) for name in NAMES))
    signatures = {name: str(inspect.signature(getattr(owner, name))) for name in NAMES}
    check("signatures-remain-stable", signatures == {"verify_vendors": "() -> 'dict[str, Any]'", "parse_frontmatter": "(path: 'Path') -> 'tuple[dict[str, str], list[str]]'", "validate_skills": "() -> 'dict[str, Any]'", "verify_core": "() -> 'dict[str, Any]'"})
    check("owner-has-no-reverse-facade-import", "import agent_os_lifecycle" not in source and "from agent_os_lifecycle" not in source)
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    entry = entries["_tools/lifecycle/core_validation.py"]
    check("topology-routes-core-validation-owner", entry["focused_shard"] == "_tools/lifecycle/test_core_validation.py" and entry["depends_on"] == ["_tools/lifecycle/release_tree.py", "_tools/lifecycle/shared.py"] and "_tools/lifecycle/core_validation.py" in entries["_tools/agent_os_lifecycle.py"]["depends_on"])

    with tempfile.TemporaryDirectory(prefix="lifecycle-core-validation-") as temporary:
        root = Path(temporary)
        good = root / "skills/good-skill/SKILL.md"
        good.parent.mkdir(parents=True)
        good.write_text("---\nname: good-skill\ndescription: first\n  second\n---\n", encoding="utf-8")
        skipped = root / "skills/project-memory/SKILL.md"
        skipped.parent.mkdir(parents=True)
        skipped.write_text("invalid", encoding="utf-8")
        bad = root / "vendor/bad-skill/SKILL.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("invalid", encoding="utf-8")
        original_root = owner.ROOT
        owner.ROOT = root
        try:
            metadata, parse_errors = owner.parse_frontmatter(good)
            skills = owner.validate_skills()
        finally:
            owner.ROOT = original_root
        check("frontmatter-and-skill-boundaries-remain-stable", metadata == {"name": "good-skill", "description": "first second"} and not parse_errors and skills["checked"] == 1 and [item["path"] for item in skills["errors"]] == ["vendor/bad-skill/SKILL.md"])

    original_load = owner.load_json
    owner.load_json = lambda path, default=None: {"packages": [{}], "research_sources": "invalid"}
    try:
        vendors = owner.verify_vendors()
    finally:
        owner.load_json = original_load
    check("vendor-validation-remains-fail-closed-and-ordered", [item["code"] for item in vendors["errors"]] == ["VENDOR_ROOT_INVALID", "VENDOR_COMMIT_INVALID", "VENDOR_LICENSE_MISSING", "VENDOR_FILE_ALLOWLIST_EMPTY", "RESEARCH_SOURCES_INVALID"] and vendors["verified_files"] == 0 and vendors["validated_research_records"] == 0)

    originals = (owner.load_json, owner.manifest_entries, owner.collect_release_entries, owner.verify_vendors, owner.validate_skills)
    owner.load_json = lambda path, default=None: {"agent_os_version": "0.0.0", "release_id": "fixture"}
    owner.manifest_entries = lambda manifest: ({"missing": {"type": "file", "sha256": "a"}, "changed": {"type": "file", "sha256": "a"}}, ["schema"])
    owner.collect_release_entries = lambda: ({"changed": {"type": "file", "sha256": "b"}, "extra": {"type": "file", "sha256": "c"}, "unsafe": {"type": "symlink", "target_within_release": False}}, ["mystery"])
    owner.verify_vendors = lambda: {"ok": False}
    owner.validate_skills = lambda: {"ok": False}
    original_facade_verify = facade.verify_core
    marker = {"ok": True, "source": "facade-binding"}
    try:
        result = owner.verify_core()
        facade.verify_core = lambda: marker
        live_binding = transaction.verify_core()
    finally:
        owner.load_json, owner.manifest_entries, owner.collect_release_entries, owner.verify_vendors, owner.validate_skills = originals
        facade.verify_core = original_facade_verify
    expected_reasons = ["CORE_MANIFEST_SCHEMA_INVALID", "UNCLASSIFIED_STABLE_PATH", "CORE_MANIFEST_MISMATCH", "CORE_SYMLINK_OUTSIDE_RELEASE", "CORE_VERSION_MISMATCH", "VENDOR_LOCK_MISMATCH", "SKILL_VALIDATION_FAILED"]
    check("core-reason-precedence-and-transaction-binding-remain-live", result["reason_codes"] == expected_reasons and result["missing"] == ["missing"] and result["extra"] == ["extra", "unsafe"] and result["changed"] == ["changed"] and live_binding is marker)

    payload = {"ok": all(bool(case["passed"]) for case in cases), "passed": sum(bool(case["passed"]) for case in cases), "total": len(cases), "cases": cases}
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0 if payload["ok"] else 1)
# fmt: on


if __name__ == "__main__":
    main()
