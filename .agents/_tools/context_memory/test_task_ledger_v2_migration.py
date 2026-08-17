#!/usr/bin/env python3
"""Bounded BR2c1 migration/rollback acceptance shard."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import task_ledger


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(facade.json_bytes(value))


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)


def fixture(base: Path) -> facade.ContextMemoryService:
    project, root = base / "fixture", base / "fixture" / ".agents"
    (root / "memory").mkdir(parents=True)
    shutil.copy2(ROOT / "memory/context-policy.json", root / "memory/context-policy.json")
    write(root / "project/project-binding.json", {"schema_version": 1, "project_id": "fixture-project", "repository": {"kind": "git", "root_markers": ["README.md"], "remote_aliases": ["fixture/migration"]}, "commands": [], "context_entrypoints": [], "created_at": "2026-08-03T00:00:00Z", "last_verified_at": "2026-08-03T00:00:00Z", "last_verified_commit": None})
    write(root / "_manifest/base-release-manifest.json", {"schema_version": 1, "release_id": "fixture"})
    (project / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (project / ".gitignore").write_text(".agents/_runtime/\n", encoding="utf-8")
    for command in (["git", "init", "-b", "main"], ["git", "config", "user.name", "Fixture"], ["git", "config", "user.email", "fixture@example.invalid"], ["git", "add", "."], ["git", "commit", "-m", "fixture"]):
        run(command, project)
    service = facade.ContextMemoryService(root, now=lambda: datetime(2026, 8, 3, tzinfo=timezone.utc))
    initialized = service.plan_initialize()
    assert initialized["ok"] and service.apply(initialized["plan"]["plan_id"], True)["ok"]
    return service


def task(service: facade.ContextMemoryService, identifier: str, status: str, padding: int = 0) -> dict[str, object]:
    return {"id": identifier, "title": "Migration task", "owner": "codex-maintainer", "scope": ["docs/example.md"], "base_commit": service.head(), "status": status, "claimed_at": "2026-08-03T00:00:00Z", "updated_at": "2026-08-03T00:00:00Z", "evidence": (["x" * padding] if padding else [])}


def install_v1(service: facade.ContextMemoryService, tasks: list[dict[str, object]], *, canonical: bool = True) -> bytes:
    ledger = {"schema_version": 1, "project_id": "fixture-project", "tasks": tasks}
    content = facade.json_bytes(ledger) if canonical else json.dumps(ledger, ensure_ascii=False, indent=3).encode() + b"\n"
    service.path(facade.TASKS_REL).write_bytes(content)
    manifest = service.document(facade.MANIFEST_REL, {})
    manifest["active_task_ledger_sha256"] = facade.sha256_bytes(content)
    write(service.path(facade.MANIFEST_REL), manifest)
    return content


def planned(service: facade.ContextMemoryService) -> dict[str, object]:
    result = service.plan_migrate_task_ledger()
    assert result.get("ok"), result
    return result["plan"]


def case_semantics_and_hash_contract(base: Path) -> bool:
    service = fixture(base)
    source = install_v1(service, [task(service, "active-one", "active"), task(service, "done-one", "complete")])
    plan = planned(service)
    changes = {item["path"]: item for item in plan["changes"]}
    target = facade.decoded(changes[facade.TASKS_REL]["after_base64"])
    metadata = plan["metadata"]
    return metadata["source_ledger_sha256"] == facade.sha256_bytes(source) and metadata["target_ledger_sha256"] == facade.sha256_bytes(target) and metadata["index_sha256"] == changes[task_ledger.V2_INDEX_REL]["after_sha256"] and json.loads(target)["tasks"][0]["id"] == "active-one"


def case_segments_are_bounded_and_ordered(base: Path) -> bool:
    service = fixture(base)
    install_v1(service, [task(service, f"done-{index:03d}", "handed-off", 500) for index in range(180)])
    plan = planned(service)
    segments = plan["metadata"]["segments"]
    return len(segments) >= 2 and all(item["byte_count"] <= task_ledger.V2_BYTE_LIMIT for item in segments) and [Path(item["path"]).stem for item in segments] == [f"segment-{index:08d}" for index in range(len(segments))]


def case_privacy_guard_rejects_source(base: Path) -> bool:
    service = fixture(base)
    bad = task(service, "private-task", "complete")
    bad["conversation"] = "secret"
    install_v1(service, [bad])
    result = service.plan_migrate_task_ledger()
    return result.get("reason_codes") == ["TASK_LEDGER_MIGRATION_SOURCE_INVALID"]


def case_apply_receipt_binds_transition(base: Path) -> bool:
    service = fixture(base)
    install_v1(service, [task(service, "active-one", "blocked"), task(service, "done-one", "cancelled")])
    plan = planned(service)
    result = service.apply(plan["plan_id"], True)
    return result.get("ok") is True and result["receipt"]["transition"] == plan["metadata"] and service.document(facade.TASKS_REL, {})["schema_version"] == 2


def case_fault_restores_exact_v1(base: Path) -> bool:
    service = fixture(base)
    source = install_v1(service, [task(service, "active-one", "active"), task(service, "done-one", "handed-off")], canonical=False)
    plan = planned(service)
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        result = service.apply(plan["plan_id"], True, test_fail_after=2)
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    segment_paths = [item["path"] for item in plan["metadata"]["segments"]]
    return result.get("rollback_verified") is True and service.read_bytes(facade.TASKS_REL) == source and service.read_bytes(task_ledger.V2_INDEX_REL) is None and all(service.read_bytes(path) is None for path in segment_paths)


def case_explicit_rollback_is_byte_exact(base: Path) -> bool:
    service = fixture(base)
    source = install_v1(service, [task(service, "done-one", "complete")], canonical=False)
    migration = planned(service)
    assert service.apply(migration["plan_id"], True).get("ok")
    rollback = service.plan_rollback_task_ledger(migration["plan_id"])
    result = service.apply(rollback["plan"]["plan_id"], True) if rollback.get("ok") else rollback
    return result.get("ok") is True and result["receipt"]["transition"]["rollback_result"] == "byte-exact-restored" and service.read_bytes(facade.TASKS_REL) == source and service.read_bytes(task_ledger.V2_INDEX_REL) is None


def case_diverged_target_blocks_rollback(base: Path) -> bool:
    service = fixture(base)
    install_v1(service, [task(service, "done-one", "complete")])
    migration = planned(service)
    assert service.apply(migration["plan_id"], True).get("ok")
    service.path(task_ledger.V2_INDEX_REL).write_bytes(b"{}\n")
    result = service.plan_rollback_task_ledger(migration["plan_id"])
    return result.get("reason_codes") == ["TASK_LEDGER_ROLLBACK_TARGET_DIVERGED"]


def case_capacity_fails_closed(base: Path) -> bool:
    service = fixture(base)
    install_v1(service, [task(service, f"done-{index:03d}", "complete", 500) for index in range(390)])
    result = service.plan_migrate_task_ledger()
    return result.get("reason_codes") == ["TASK_LEDGER_MIGRATION_CAPACITY_EXCEEDED"]


def case_metadata_rejects_unbound_path(base: Path) -> bool:
    service = fixture(base)
    install_v1(service, [task(service, "done-one", "complete")])
    plan = planned(service)
    paths = {item["path"] for item in plan["changes"]} | {"project/context/unbound.json"}
    return service.validate_plan_metadata(plan["operation"], plan["metadata"], paths) == ["CONTEXT_PLAN_METADATA_INVALID"]


def case_cli_schema_and_topology_expose_boundary(base: Path) -> bool:
    del base
    schema = json.loads((ROOT / "core/contracts/context-memory-plan.schema.json").read_text())
    topology = json.loads((ROOT / "_tools/context_memory/topology.json").read_text())
    operations = schema["properties"]["operation"]["enum"]
    migration_shards = {item["migration_shard"] for item in topology["entries"] if isinstance(item.get("migration_shard"), str)}
    return {"migrate-task-ledger", "rollback-task-ledger"} <= set(operations) and migration_shards == {"_tools/context_memory/test_task_ledger_v2_migration.py"}


CASES = [
    ("semantic-hash-contract", case_semantics_and_hash_contract),
    ("bounded-ordered-segments", case_segments_are_bounded_and_ordered),
    ("privacy-guard", case_privacy_guard_rejects_source),
    ("receipt-transition-binding", case_apply_receipt_binds_transition),
    ("fault-exact-v1-rollback", case_fault_restores_exact_v1),
    ("explicit-byte-exact-rollback", case_explicit_rollback_is_byte_exact),
    ("diverged-target-blocked", case_diverged_target_blocks_rollback),
    ("capacity-fails-closed", case_capacity_fails_closed),
    ("metadata-path-binding", case_metadata_rejects_unbound_path),
    ("cli-schema-topology", case_cli_schema_and_topology_expose_boundary),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br2c1-") as temporary:
        for index, (name, check) in enumerate(CASES):
            try:
                passed, error = bool(check(Path(temporary) / str(index))), None
            except Exception as exc:  # noqa: BLE001 - case isolation reports bounded diagnostics
                passed, error = False, str(exc)
            results.append({"id": name, "passed": passed, **({"error": error} if error else {})})
    output = {"ok": all(item["passed"] for item in results), "passed": sum(item["passed"] for item in results), "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
