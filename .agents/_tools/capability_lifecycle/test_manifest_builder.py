#!/usr/bin/env python3
"""Eight focused checks for working-manifest builder extraction."""

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
facade = importlib.import_module("agent_os_capability_lifecycle")
owner = importlib.import_module("capability_lifecycle.manifest_builder")
candidate = importlib.import_module("capability_lifecycle.candidate_validation")
telemetry = importlib.import_module("capability_lifecycle.telemetry")
base = importlib.import_module("capability_lifecycle.shared")

# fmt: off
METHODS = ("release_entries_with_overlay", "render_working_manifest", "verify_working_manifest")
EXPECTED_AST = "b494ade9e5844ec1716b82bc892bdd22e12a17031a9c5265443beeb328680072"
POLICY = {"release_owned_roots": ["_manifest", "core", "routing", "vendor"], "application_owned_scopes": ["project/**"], "runtime_scopes": ["_runtime/**"], "manifest_self": facade.MANIFEST}


class Harness(facade.CapabilityLifecycleService):
    def git(self, *arguments: str) -> str | None:
        return "https://example.invalid/os.git" if arguments[:3] == ("remote", "get-url", "origin") else "a" * 40


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fixture(parent: Path) -> Harness:
    root = parent / ".agents"
    write(root / "core/contracts/ownership-policy.json", facade.json_bytes(POLICY))
    write(root / facade.REGISTRY, facade.json_bytes({"version": "9.1.0"}))
    write(root / "core/a.txt", b"a")
    write(root / "core/deleted.txt", b"delete")
    write(root / "project/private.txt", b"private")
    write(root / "_runtime/state.json", b"runtime")
    return Harness(root)


def raises(callable_value: object, text: str) -> bool:
    try:
        callable_value()  # type: ignore[operator]
    except ValueError as error:
        return text in str(error)
    return False


def main() -> None:
    cases: list[dict[str, object]] = []
    check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8"))
    mixin = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "ManifestBuilderMixin")
    nodes = {node.name: node for node in mixin.body if isinstance(node, ast.FunctionDef)}
    selected = [nodes[name] for name in METHODS]
    digest = hashlib.sha256("\n".join(ast.dump(node, include_attributes=False) for node in selected).encode()).hexdigest()
    check("exact-family-ast-and-lines", digest == EXPECTED_AST and sum(node.end_lineno - node.lineno + 1 for node in selected) == 74)
    service_class = facade.CapabilityLifecycleService
    check("facade-identity-mro-and-constructor", all(getattr(service_class, name) is getattr(owner.ManifestBuilderMixin, name) for name in METHODS) and service_class.__mro__[-5:-1] == (owner.ManifestBuilderMixin, candidate.CandidateValidationMixin, telemetry.TelemetryMixin, base.CapabilityLifecycleBase) and inspect.signature(service_class) == inspect.signature(base.CapabilityLifecycleBase))

    with tempfile.TemporaryDirectory(prefix="manifest-builder-") as directory:
        service = fixture(Path(directory))
        write(service.root / "stray.txt", b"stray")
        entries, unclassified = service.release_entries_with_overlay({"core/a.txt": b"changed", "core/deleted.txt": None, "core/new.txt": b"new"})
        by_path = {item["path"]: item for item in entries}
        check("overlay-is-deterministic-and-ownership-bounded", list(by_path) == sorted(by_path) and set(by_path) == {"core/a.txt", "core/contracts/ownership-policy.json", "core/new.txt", facade.REGISTRY} and by_path["core/a.txt"]["sha256"] == facade.sha256_bytes(b"changed") and unclassified == ["stray.txt"])
        (service.root / "stray.txt").unlink()
        (service.root / "core/safe-link").symlink_to("a.txt")
        (service.root / "core/unsafe-link").symlink_to("/outside-release")
        links = {item["path"]: item for item in service.release_entries_with_overlay({})[0] if item["type"] == "symlink"}
        check("symlink-targets-are-hashed-and-bounded", links["core/safe-link"]["target_within_release"] is True and links["core/unsafe-link"]["target_within_release"] is False and links["core/safe-link"]["sha256"] == facade.sha256_bytes(b"a.txt"))
        (service.root / "core/unsafe-link").unlink()
        rendered = json.loads(service.render_working_manifest({facade.REGISTRY: facade.json_bytes({"version": "10.0.0"})}, "2026-08-07T00:00:00Z", "1234567890abcdef-more"))
        check("render-binds-version-provenance-exclusions-and-release-key", rendered["agent_os_version"] == "10.0.0" and rendered["release_id"] == "aos10-working-1234567890abcdef" and rendered["excluded_scopes"] == ["project/**", "_runtime/**"] and rendered["vendor_lock"] == facade.VENDOR_LOCK and rendered["provenance"] == {"status": "working-baseline", "source_locator": "https://example.invalid/os.git", "source_commit": None, "created_from_repository_head": "a" * 40})
        check("render-rejects-unclassified-stable-paths", raises(lambda: service.render_working_manifest({"unknown.txt": b"x"}, "now", "key"), "unclassified stable paths: unknown.txt"))
        (service.root / "core/unsafe-link").symlink_to("/outside-release")
        check("render-rejects-unsafe-release-symlinks", raises(lambda: service.render_working_manifest({}, "now", "key"), "unsafe release symlinks: core/unsafe-link"))
        (service.root / "core/unsafe-link").unlink()
        write(service.root / facade.MANIFEST, service.render_working_manifest({}, "now", "key"))
        before = service.verify_working_manifest()
        write(service.root / "core/a.txt", b"drift")
        topology = json.loads((TOOLS_ROOT / "capability_lifecycle/topology.json").read_text())
        entry = next(item for item in topology["entries"] if item.get("entrypoint", "").endswith("manifest_builder.py"))
        check("verification-and-one-way-topology-detect-drift", before and not service.verify_working_manifest() and entry["depends_on"] == ["_tools/capability_lifecycle/shared.py"] and entry["focused_shard"].endswith("test_manifest_builder.py") and "agent_os_capability_lifecycle" not in Path(owner.__file__).read_text())
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(bool(item["passed"]) for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
# fmt: on
