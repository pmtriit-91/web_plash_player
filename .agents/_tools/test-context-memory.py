#!/usr/bin/env python3
"""Dependency-free AOS-11 Context Memory acceptance fixtures."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    COLD_REL,
    HOT_REL,
    MANIFEST_REL,
    PROJECTION_REL,
    TASKS_REL,
    ContextMemoryService,
    canonical_hash,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def run_output(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def fixture(base: Path, clock: Callable[[], datetime] | None = None) -> ContextMemoryService:
    project = base / "fixture"
    agent_root = project / ".agents"
    (agent_root / "memory").mkdir(parents=True)
    shutil.copy2(ROOT / "memory" / "context-policy.json", agent_root / "memory" / "context-policy.json")
    write_json(
        agent_root / "project" / "project-binding.json",
        {
            "schema_version": 1,
            "project_id": "fixture-project",
            "repository": {"kind": "git", "root_markers": ["README.md"], "remote_aliases": ["fixture/context-memory"]},
            "commands": [],
            "context_entrypoints": [],
            "created_at": "2026-07-19T00:00:00Z",
            "last_verified_at": "2026-07-19T00:00:00Z",
            "last_verified_commit": None,
        },
    )
    write_json(agent_root / "_manifest" / "base-release-manifest.json", {"schema_version": 1, "release_id": "fixture"})
    (project / "README.md").write_text("# Fixture project\n", encoding="utf-8")
    (project / ".gitignore").write_text(".agents/_runtime/\n", encoding="utf-8")
    for command in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Context Fixture"],
        ["git", "config", "user.email", "context@agent-os.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-m", "fixture baseline"],
    ):
        run(command, project)
    return ContextMemoryService(agent_root, now=clock or (lambda: datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)))


def initialize(service: ContextMemoryService) -> None:
    planned = service.plan_initialize()
    if not planned.get("ok"):
        raise RuntimeError(planned)
    applied = service.apply(planned["plan"]["plan_id"], True)
    if not applied.get("ok"):
        raise RuntimeError(applied)


def evidence_proposal(identifier: str, tier: str, kind: str, authority: str, summary: str = "Verified fixture context.") -> dict[str, Any]:
    return {
        "id": identifier,
        "tier": tier,
        "kind": kind,
        "title": identifier.replace("-", " ").title(),
        "summary": summary,
        "authority": authority,
        "evidence": ["README.md"],
        "supersedes": [],
        "tags": ["fixture"],
    }


def apply_plan(service: ContextMemoryService, result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return result
    return service.apply(result["plan"]["plan_id"], True)


def persist_rederived_plan(
    service: ContextMemoryService,
    source: dict[str, Any],
) -> dict[str, Any]:
    plan = deepcopy(source)
    plan["changes"] = sorted(plan["changes"], key=lambda change: change["path"])
    plan["exact_diff"] = service.render_exact_diff(plan["changes"])
    plan["plan_id"] = canonical_hash(
        {
            key: value
            for key, value in plan.items()
            if key not in {"plan_id", "content_sha256"}
        }
    )[:24]
    plan["content_sha256"] = receipt_hash(plan)
    write_json(service.plans / f"{plan['plan_id']}.json", plan)
    return plan


def replace_plan_after(change: dict[str, Any], content: bytes) -> None:
    change["after_sha256"] = sha256_bytes(content)
    change["after_base64"] = base64.b64encode(content).decode("ascii")


def rewrite_hot_reference(service: ContextMemoryService, update: Callable[[dict[str, Any]], None]) -> None:
    hot = service.document(HOT_REL, {})
    reference = hot["records"][0]["source_refs"][0]
    update(reference)
    write_json(service.path(HOT_REL), hot)
    manifest = service.document(MANIFEST_REL, {})
    next(item for item in manifest["sources"] if item["tier"] == "hot")["content_sha256"] = sha256_bytes(
        service.path(HOT_REL).read_bytes()
    )
    write_json(service.path(MANIFEST_REL), manifest)


def rewrite_task_ledger(service: ContextMemoryService, update: Callable[[dict[str, Any]], None]) -> None:
    ledger = service.document(TASKS_REL, {})
    update(ledger)
    write_json(service.path(TASKS_REL), ledger)
    manifest = service.document(MANIFEST_REL, {})
    manifest["active_task_ledger_sha256"] = sha256_bytes(service.path(TASKS_REL).read_bytes())
    write_json(service.path(MANIFEST_REL), manifest)


def case_initialize_read_only(base: Path) -> bool:
    service = fixture(base)
    planned = service.plan_initialize()
    return bool(planned.get("ok") and not service.path(MANIFEST_REL).exists() and service.path(f"_runtime/context-memory/plans/{planned['plan']['plan_id']}.json").is_file())


def case_fresh_recovery(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    applied = apply_plan(service, service.plan_upsert(evidence_proposal("current-state", "hot", "current-state", "git-evidence")))
    recovered = ContextMemoryService(service.root, now=service.now).load("hot")
    return bool(
        applied.get("ok")
        and recovered.get("ok")
        and recovered.get("authoritative") is True
        and [item.get("id") for item in recovered.get("records", [])] == ["current-state"]
        and recovered.get("raw_conversation_stored") is False
    )


def case_project_contamination(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    hot = service.document(HOT_REL, {})
    hot["project_id"] = "wrong-project"
    write_json(service.path(HOT_REL), hot)
    manifest = service.document(MANIFEST_REL, {})
    next(item for item in manifest["sources"] if item["tier"] == "hot")["content_sha256"] = sha256_bytes(service.path(HOT_REL).read_bytes())
    write_json(service.path(MANIFEST_REL), manifest)
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "CONTEXT_STORE_CONTAMINATION_OR_TIER_MISMATCH" in health.get("reason_codes", [])


def case_repository_contamination(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    manifest = service.document(MANIFEST_REL, {})
    manifest["repository"]["remote_aliases"] = ["other/project"]
    write_json(service.path(MANIFEST_REL), manifest)
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "CONTEXT_REPOSITORY_CONTAMINATION" in health.get("reason_codes", [])


def case_malformed_manifest_fails_closed(base: Path) -> bool:
    top_level_service = fixture(base / "top-level-type")
    initialize(top_level_service)
    write_json(top_level_service.path(MANIFEST_REL), "corrupt")
    top_level_health = top_level_service.doctor()
    if (
        top_level_health.get("ok") is not False
        or top_level_health.get("state") != "DEGRADED"
        or "CONTEXT_MANIFEST_FIELDS_INVALID" not in top_level_health.get("reason_codes", [])
        or not isinstance(top_level_health.get("errors"), list)
    ):
        return False
    mutations: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
        (
            "repository-type",
            lambda manifest: manifest.__setitem__("repository", "corrupt"),
            "CONTEXT_MANIFEST_REPOSITORY_INVALID",
        ),
        (
            "repository-aliases-type",
            lambda manifest: manifest["repository"].__setitem__("remote_aliases", None),
            "CONTEXT_MANIFEST_REPOSITORY_INVALID",
        ),
        (
            "sources-type",
            lambda manifest: manifest.__setitem__("sources", "corrupt"),
            "CONTEXT_MANIFEST_SOURCES_INVALID",
        ),
        (
            "source-canonical-keys-type",
            lambda manifest: manifest["sources"][0].__setitem__("canonical_keys", None),
            "CONTEXT_SOURCE_FIELDS_INVALID",
        ),
        (
            "source-tier-type",
            lambda manifest: manifest["sources"][0].__setitem__("tier", {}),
            "CONTEXT_SOURCE_FIELDS_INVALID",
        ),
        (
            "budgets-type",
            lambda manifest: manifest.__setitem__("budgets", "corrupt"),
            "CONTEXT_MANIFEST_BUDGETS_INVALID",
        ),
    ]
    for identifier, mutate, expected_code in mutations:
        service = fixture(base / identifier)
        initialize(service)
        manifest = service.document(MANIFEST_REL, {})
        mutate(manifest)
        write_json(service.path(MANIFEST_REL), manifest)
        health = service.doctor()
        if (
            health.get("ok") is not False
            or health.get("state") != "DEGRADED"
            or expected_code not in health.get("reason_codes", [])
            or not isinstance(health.get("errors"), list)
        ):
            return False
    return True


def case_stale_source_loses_authority(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    service.path(HOT_REL).write_bytes(service.path(HOT_REL).read_bytes() + b"\n")
    health = service.doctor()
    loaded = service.load("hot")
    return health.get("state") == "STALE" and loaded.get("ok") and loaded.get("authoritative") is False and "CONTEXT_SOURCE_STALE" in health.get("reason_codes", [])


def case_ancestor_refresh_remains_fresh(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    marker = service.project_root / "unrelated.txt"
    marker.write_text("unrelated commit\n", encoding="utf-8")
    run(["git", "add", "unrelated.txt"], service.project_root)
    run(["git", "commit", "-m", "unrelated evidence-neutral change"], service.project_root)
    health = service.doctor()
    return health.get("state") == "FRESH" and health.get("refreshed_commit") != health.get("git_head")


def case_refresh_rebinds_evidence(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    proposal = evidence_proposal("refresh-record", "hot", "current-state", "git-evidence")
    if not apply_plan(service, service.plan_upsert(proposal)).get("ok"):
        return False
    (service.project_root / "README.md").write_text("# Fixture project\n\nUpdated evidence.\n", encoding="utf-8")
    if service.doctor().get("state") != "STALE":
        return False
    blocked = service.plan_refresh()
    if blocked.get("ok") or not any(
        item.get("code") == "CONTEXT_EVIDENCE_UNCOMMITTED" for item in blocked.get("errors", [])
    ):
        return False
    run(["git", "add", "README.md"], service.project_root)
    run(["git", "commit", "-m", "commit updated evidence"], service.project_root)
    refreshed = apply_plan(service, service.plan_refresh())
    return bool(refreshed.get("ok") and service.doctor().get("state") == "FRESH")


def case_uncommitted_evidence_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    (service.project_root / "README.md").write_text("# Dirty fixture evidence\n", encoding="utf-8")
    result = service.plan_upsert(evidence_proposal("dirty-evidence", "hot", "current-state", "git-evidence"))
    return bool(
        not result.get("ok")
        and any(item.get("code") == "CONTEXT_EVIDENCE_UNCOMMITTED" for item in result.get("errors", []))
    )


def case_untracked_evidence_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    (service.project_root / "untracked.md").write_text("not committed\n", encoding="utf-8")
    proposal = evidence_proposal("untracked-evidence", "hot", "current-state", "git-evidence")
    proposal["evidence"] = ["untracked.md"]
    result = service.plan_upsert(proposal)
    return bool(
        not result.get("ok")
        and any(item.get("code") == "CONTEXT_EVIDENCE_NOT_COMMITTED" for item in result.get("errors", []))
    )


def case_missing_evidence_commit_degrades(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    if not apply_plan(
        service,
        service.plan_upsert(evidence_proposal("missing-commit", "hot", "current-state", "git-evidence")),
    ).get("ok"):
        return False
    rewrite_hot_reference(service, lambda ref: ref.update({"git_commit": "f" * 40}))
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "CONTEXT_EVIDENCE_COMMIT_MISSING" in health.get("reason_codes", [])


def case_unreachable_evidence_commit_degrades(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    if not apply_plan(
        service,
        service.plan_upsert(evidence_proposal("unreachable-commit", "hot", "current-state", "git-evidence")),
    ).get("ok"):
        return False
    tree = run_output(["git", "rev-parse", "HEAD^{tree}"], service.project_root)
    orphan = run_output(["git", "commit-tree", tree, "-m", "unreachable evidence commit"], service.project_root)
    rewrite_hot_reference(service, lambda ref: ref.update({"git_commit": orphan}))
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "CONTEXT_EVIDENCE_COMMIT_UNREACHABLE" in health.get("reason_codes", [])


def case_git_evidence_hash_mismatch_degrades(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    if not apply_plan(
        service,
        service.plan_upsert(evidence_proposal("hash-mismatch", "hot", "current-state", "git-evidence")),
    ).get("ok"):
        return False
    rewrite_hot_reference(service, lambda ref: ref.update({"sha256": "0" * 64}))
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "CONTEXT_EVIDENCE_GIT_HASH_MISMATCH" in health.get("reason_codes", [])


def case_authority_conflict(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    conflict_path = "project/context/warm-conflict.json"
    conflict = {"schema_version": 1, "project_id": "fixture-project", "tier": "warm", "records": []}
    service.path(conflict_path).parent.mkdir(parents=True, exist_ok=True)
    service.path(conflict_path).write_bytes(json_bytes(conflict) + b"\n")
    manifest = service.document(MANIFEST_REL, {})
    manifest["sources"].append(
        {
            "id": "warm-conflict",
            "tier": "warm",
            "path": conflict_path,
            "owner": "application",
            "format": "context-store-json",
            "load_policy": "just-in-time",
            "authority": "project-decision",
            "content_sha256": sha256_bytes(service.path(conflict_path).read_bytes()),
            "canonical_keys": ["decisions"],
        }
    )
    write_json(service.path(MANIFEST_REL), manifest)
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "CONTEXT_AUTHORITY_CONFLICT" in health.get("reason_codes", [])


def case_notebooklm_cold_only(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    manifest = service.document(MANIFEST_REL, {})
    hot = next(item for item in manifest["sources"] if item["tier"] == "hot")
    hot["connector"] = "notebooklm"
    write_json(service.path(MANIFEST_REL), manifest)
    health = service.doctor()
    return health.get("state") == "DEGRADED" and "NOTEBOOKLM_COLD_RESEARCH_ONLY" in health.get("reason_codes", [])


def case_raw_conversation_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    proposal = evidence_proposal("raw-memory", "hot", "current-state", "git-evidence")
    proposal["conversation"] = [{"role": "user", "content": "secret"}]
    result = service.plan_upsert(proposal)
    return not result.get("ok") and "CONTEXT_PROPOSAL_INVALID" in result.get("reason_codes", [])


def case_path_traversal_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    proposal = evidence_proposal("unsafe-evidence", "hot", "current-state", "git-evidence")
    proposal["evidence"] = ["../outside.txt"]
    result = service.plan_upsert(proposal)
    return not result.get("ok") and any(item.get("code") == "CONTEXT_EVIDENCE_PATH_UNSAFE" for item in result.get("errors", []))


def case_transaction_confirmation_and_apply(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(evidence_proposal("guardrail-one", "hot", "guardrail", "user-confirmed"))
    denied = service.apply(planned["plan"]["plan_id"], False)
    applied = service.apply(planned["plan"]["plan_id"], True)
    projection = service.path(PROJECTION_REL).read_text(encoding="utf-8")
    return bool(not denied.get("ok") and applied.get("ok") and "Guardrail One" in projection and "raw prompt" not in projection.lower())


def case_failure_rolls_back(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(evidence_proposal("rollback-record", "hot", "guardrail", "user-confirmed"))
    changes = planned["plan"]["changes"]
    before = {item["path"]: service.read_bytes(item["path"]) for item in changes}
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        failed = service.apply(planned["plan"]["plan_id"], True, test_fail_after=1)
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    return bool(
        not failed.get("ok")
        and failed.get("rollback_verified") is True
        and all(service.read_bytes(path) == content for path, content in before.items())
    )


def case_post_receipt_failure_removes_false_receipt(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(
        evidence_proposal(
            "receipt-rollback-record",
            "hot",
            "guardrail",
            "user-confirmed",
        )
    )
    plan_id = planned["plan"]["plan_id"]
    changes = planned["plan"]["changes"]
    before = {item["path"]: service.read_bytes(item["path"]) for item in changes}
    receipts_before = {
        item.name for item in service.receipts.glob("*.json") if item.is_file()
    }
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        failed = service.apply(
            plan_id,
            True,
            test_fail_after_receipt=True,
        )
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    stored_plan = json.loads(
        (service.plans / f"{plan_id}.json").read_text(encoding="utf-8")
    )
    receipts_after = {
        item.name for item in service.receipts.glob("*.json") if item.is_file()
    }
    return bool(
        not failed.get("ok")
        and failed.get("rollback_verified") is True
        and stored_plan.get("status") == "failed"
        and stored_plan.get("content_sha256") == receipt_hash(stored_plan)
        and receipts_after == receipts_before
        and all(service.read_bytes(path) == content for path, content in before.items())
    )


def case_post_receipt_cleanup_failure_is_incomplete(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(
        evidence_proposal(
            "receipt-cleanup-failure",
            "hot",
            "guardrail",
            "user-confirmed",
        )
    )
    changes = planned["plan"]["changes"]
    before = {item["path"]: service.read_bytes(item["path"]) for item in changes}
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        failed = service.apply(
            planned["plan"]["plan_id"],
            True,
            test_fail_after_receipt=True,
            test_fail_receipt_cleanup=True,
        )
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    return bool(
        failed.get("ok") is False
        and failed.get("reason_codes") == ["MEMORY_APPLY_ROLLBACK_INCOMPLETE"]
        and failed.get("rollback_verified") is False
        and all(service.read_bytes(path) == content for path, content in before.items())
    )


def case_tampered_plan_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(evidence_proposal("tamper-record", "hot", "guardrail", "user-confirmed"))
    plan_path = service.path(f"_runtime/context-memory/plans/{planned['plan']['plan_id']}.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["operation"] = "compact"
    plan["content_sha256"] = receipt_hash(plan)
    write_json(plan_path, plan)
    result = service.apply(planned["plan"]["plan_id"], True)
    return bool(
        not result.get("ok")
        and "PLAN_NOT_FOUND_OR_TAMPERED" in result.get("reason_codes", [])
        and "CONTEXT_PLAN_INVALID" in result.get("validation_errors", [])
    )


def case_rederived_plan_path_escalation_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(
        evidence_proposal("path-escalation", "hot", "guardrail", "user-confirmed")
    )
    plan = planned["plan"]
    unauthorized_path = "project/context/handoffs/handoff-" + "a" * 24 + ".json"
    content = json_bytes({"unexpected": "operation target"})
    plan["changes"] = [
        {
            "path": unauthorized_path,
            "before_sha256": None,
            "after_sha256": sha256_bytes(content),
            "before_base64": None,
            "after_base64": base64.b64encode(content).decode("ascii"),
        }
    ]
    plan["exact_diff"] = service.render_exact_diff(plan["changes"])
    plan["plan_id"] = canonical_hash(
        {
            key: value
            for key, value in plan.items()
            if key not in {"plan_id", "content_sha256"}
        }
    )[:24]
    plan["content_sha256"] = receipt_hash(plan)
    write_json(service.plans / f"{plan['plan_id']}.json", plan)
    result = service.apply(plan["plan_id"], True)
    return bool(
        not result.get("ok")
        and "PLAN_NOT_FOUND_OR_TAMPERED" in result.get("reason_codes", [])
        and "CONTEXT_PLAN_METADATA_INVALID" in result.get("validation_errors", [])
        and not service.path(unauthorized_path).exists()
    )


def case_rederived_receipt_only_handoff_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {
        "id": "orphan-handoff",
        "title": "Orphan handoff guard",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    planned = service.plan_handoff(
        {
            "task_id": "orphan-handoff",
            "from_owner": "agent-a",
            "to_owner": "agent-b",
            "verified_outcomes": ["Receipt-only handoff attack fixture prepared."],
            "unresolved_risks": [],
            "next_action": "Reject the orphan handoff receipt.",
            "evidence": ["README.md"],
        }
    )
    if not planned.get("ok"):
        return False
    plan = planned["plan"]
    handoff_path = (
        f"project/context/handoffs/{plan['metadata']['handoff_id']}.json"
    )
    receipt_change = next(
        item for item in plan["changes"] if item["path"] == handoff_path
    )
    plan["changes"] = [receipt_change]
    plan["exact_diff"] = service.render_exact_diff(plan["changes"])
    plan["plan_id"] = canonical_hash(
        {
            key: value
            for key, value in plan.items()
            if key not in {"plan_id", "content_sha256"}
        }
    )[:24]
    plan["content_sha256"] = receipt_hash(plan)
    write_json(service.plans / f"{plan['plan_id']}.json", plan)
    result = service.apply(plan["plan_id"], True)
    task = next(
        item
        for item in service.document(TASKS_REL, {})["tasks"]
        if item["id"] == "orphan-handoff"
    )
    return bool(
        not result.get("ok")
        and "PLAN_NOT_FOUND_OR_TAMPERED" in result.get("reason_codes", [])
        and "CONTEXT_PLAN_METADATA_INVALID"
        in result.get("validation_errors", [])
        and task["owner"] == "agent-a"
        and not service.path(handoff_path).exists()
    )


def case_expired_plan_rejected(base: Path) -> bool:
    clock = [datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)]
    service = fixture(base, lambda: clock[0])
    initialize(service)
    planned = service.plan_upsert(evidence_proposal("expired-record", "hot", "guardrail", "user-confirmed"))
    clock[0] += timedelta(hours=1)
    result = service.apply(planned["plan"]["plan_id"], True)
    return not result.get("ok") and "PLAN_EXPIRED" in result.get("reason_codes", [])


def case_stale_head_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(evidence_proposal("stale-head", "hot", "guardrail", "user-confirmed"))
    marker = service.project_root / "marker.txt"
    marker.write_text("new head\n", encoding="utf-8")
    run(["git", "add", "marker.txt"], service.project_root)
    run(["git", "commit", "-m", "advance head"], service.project_root)
    result = service.apply(planned["plan"]["plan_id"], True)
    return not result.get("ok") and "STALE_GIT_HEAD" in result.get("reason_codes", [])


def case_concurrent_lock(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    planned = service.plan_upsert(evidence_proposal("locked-record", "hot", "guardrail", "user-confirmed"))
    descriptor = service.acquire_lock()
    if descriptor is None:
        return False
    try:
        result = service.apply(planned["plan"]["plan_id"], True)
    finally:
        service.release_lock(descriptor)
    return not result.get("ok") and "TRANSACTION_BUSY" in result.get("reason_codes", [])


def case_task_overlap_blocked(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    first = {"id": "task-one", "title": "First task", "owner": "agent-a", "scope": ["src/**"], "evidence": ["README.md"]}
    second = {"id": "task-two", "title": "Second task", "owner": "agent-b", "scope": ["src/module/**"], "evidence": ["README.md"]}
    applied = apply_plan(service, service.plan_claim_task(first))
    blocked = service.plan_claim_task(second)
    return applied.get("ok") and not blocked.get("ok") and "TASK_SCOPE_CONFLICT" in blocked.get("reason_codes", [])


def case_task_ledger_schema_and_privacy_parity(base: Path) -> bool:
    mutations: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
        ("tasks-shape", lambda ledger: ledger.update({"tasks": {}}), "TASK_LEDGER_FIELDS_INVALID"),
        ("task-shape", lambda ledger: ledger["tasks"].__setitem__(0, "corrupt"), "TASK_FIELDS_INVALID"),
        ("status-enum", lambda ledger: ledger["tasks"][0].update({"status": "mystery"}), "TASK_STATUS_INVALID"),
        ("title-type", lambda ledger: ledger["tasks"][0].update({"title": 7}), "TASK_TITLE_INVALID"),
        ("owner-type", lambda ledger: ledger["tasks"][0].update({"owner": []}), "TASK_OWNER_INVALID"),
        ("scope-type", lambda ledger: ledger["tasks"][0].update({"scope": [7]}), "TASK_SCOPE_INVALID"),
        ("commit-type", lambda ledger: ledger["tasks"][0].update({"base_commit": 7}), "TASK_BASE_COMMIT_INVALID"),
        ("timestamp-format", lambda ledger: ledger["tasks"][0].update({"claimed_at": "2026-07-24"}), "TASK_TIMESTAMP_INVALID"),
        ("evidence-shape", lambda ledger: ledger["tasks"][0].update({"evidence": "README.md"}), "TASK_EVIDENCE_INVALID"),
        (
            "privacy-marker",
            lambda ledger: ledger["tasks"][0].update({"evidence": ["<|user|> raw transcript"]}),
            "TASK_FORBIDDEN_PAYLOAD",
        ),
    ]
    for identifier, mutation, expected_code in mutations:
        service = fixture(base / identifier)
        initialize(service)
        claim = {
            "id": "schema-task",
            "title": "Schema parity task",
            "owner": "agent-a",
            "scope": ["src/**"],
            "evidence": ["README.md"],
        }
        if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
            return False
        rewrite_task_ledger(service, mutation)
        health = service.doctor()
        if health.get("state") != "DEGRADED" or expected_code not in health.get("reason_codes", []):
            return False
    return True


def case_task_claim_schema_and_privacy_gate(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    baseline: dict[str, Any] = {
        "id": "claim-schema-task",
        "title": "Claim schema task",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    invalid: list[dict[str, Any]] = []
    for field, value in (
        ("title", 7),
        ("owner", []),
        ("scope", [7]),
        ("scope", ["src/**"] * 65),
        ("evidence", "README.md"),
        ("evidence", ["README.md"] * 65),
        ("evidence", ["<|assistant|> raw transcript"]),
    ):
        proposal = dict(baseline)
        proposal[field] = value
        invalid.append(proposal)
    results = [service.plan_claim_task(proposal) for proposal in invalid]
    return all(
        not result.get("ok") and "TASK_PROPOSAL_INVALID" in result.get("reason_codes", [])
        for result in results
    )


def case_concurrent_task_plan_invalidated(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    first = {"id": "parallel-one", "title": "Parallel first", "owner": "agent-a", "scope": ["src/**"], "evidence": ["README.md"]}
    second = {"id": "parallel-two", "title": "Parallel second", "owner": "agent-b", "scope": ["src/module/**"], "evidence": ["README.md"]}
    first_plan = service.plan_claim_task(first)
    second_plan = service.plan_claim_task(second)
    if not first_plan.get("ok") or not second_plan.get("ok"):
        return False
    applied = service.apply(first_plan["plan"]["plan_id"], True)
    rejected = service.apply(second_plan["plan"]["plan_id"], True)
    return applied.get("ok") and not rejected.get("ok") and "STALE_TARGET_HASH" in rejected.get("reason_codes", [])


def case_stale_task_blocks_handoff(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {"id": "handoff-task", "title": "Handoff task", "owner": "agent-a", "scope": ["src/**"], "evidence": ["README.md"]}
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    run(["git", "add", ".agents/project/context", ".agents/skills/project-memory/SKILL.md"], service.project_root)
    run(["git", "commit", "-m", "advance after claim"], service.project_root)
    proposal = {
        "task_id": "handoff-task",
        "from_owner": "agent-a",
        "to_owner": "agent-b",
        "verified_outcomes": ["Fixture outcome verified."],
        "unresolved_risks": [],
        "next_action": "Continue fixture work.",
        "evidence": ["README.md"],
    }
    result = service.plan_handoff(proposal)
    return not result.get("ok") and "TASK_BASE_COMMIT_STALE" in result.get("reason_codes", [])


def case_same_owner_handoff_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {
        "id": "same-owner-handoff",
        "title": "Same owner handoff guard",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    result = service.plan_handoff(
        {
            "task_id": "same-owner-handoff",
            "from_owner": "agent-a",
            "to_owner": "agent-a",
            "verified_outcomes": ["Same-owner transfer is not a handoff."],
            "unresolved_risks": [],
            "next_action": "Continue under the existing owner.",
            "evidence": ["README.md"],
        }
    )
    return bool(
        not result.get("ok")
        and result.get("reason_codes") == ["HANDOFF_OWNER_UNCHANGED"]
    )


def case_task_continuation_rebases_and_unblocks_handoff(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {
        "id": "continued-task",
        "title": "Continued task",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    previous_base = next(
        item["base_commit"]
        for item in service.document(TASKS_REL, {})["tasks"]
        if item["id"] == "continued-task"
    )
    run(["git", "add", ".agents/project/context", ".agents/skills/project-memory/SKILL.md"], service.project_root)
    run(["git", "commit", "-m", "checkpoint continued task"], service.project_root)
    current_head = service.head()
    proposal = {
        "task_id": "continued-task",
        "owner": "agent-a",
        "evidence": ["README.md"],
    }
    planned = service.plan_continue_task(proposal)
    unchanged_before_apply = next(
        item["base_commit"]
        for item in service.document(TASKS_REL, {})["tasks"]
        if item["id"] == "continued-task"
    )
    applied = apply_plan(service, planned)
    task = next(
        item
        for item in service.document(TASKS_REL, {})["tasks"]
        if item["id"] == "continued-task"
    )
    handoff = service.plan_handoff(
        {
            "task_id": "continued-task",
            "from_owner": "agent-a",
            "to_owner": "agent-b",
            "verified_outcomes": ["Continuation transaction verified."],
            "unresolved_risks": [],
            "next_action": "Continue from the exact checkpoint.",
            "evidence": ["README.md"],
        }
    )
    return bool(
        previous_base != current_head
        and planned.get("ok")
        and unchanged_before_apply == previous_base
        and applied.get("ok")
        and task["base_commit"] == current_head
        and service.doctor().get("state") == "FRESH"
        and handoff.get("ok")
    )


def case_task_continuation_wrong_owner_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {
        "id": "owner-task",
        "title": "Owner task",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    result = service.plan_continue_task(
        {"task_id": "owner-task", "owner": "agent-b", "evidence": []}
    )
    return bool(
        not result.get("ok")
        and result.get("reason_codes") == ["TASK_CONTINUATION_OWNER_MISMATCH"]
    )


def case_task_continuation_diverged_base_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {
        "id": "diverged-task",
        "title": "Diverged task",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    rewrite_task_ledger(
        service,
        lambda ledger: ledger["tasks"][0].update({"base_commit": "f" * 40}),
    )
    result = service.plan_continue_task(
        {"task_id": "diverged-task", "owner": "agent-a", "evidence": []}
    )
    return bool(
        not result.get("ok")
        and result.get("reason_codes") == ["TASK_CONTINUATION_BASE_DIVERGED"]
    )


def case_task_continuation_uncommitted_evidence_rejected(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {
        "id": "evidence-task",
        "title": "Evidence task",
        "owner": "agent-a",
        "scope": ["src/**"],
        "evidence": ["README.md"],
    }
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    (service.project_root / "uncommitted.md").write_text("not committed\n", encoding="utf-8")
    result = service.plan_continue_task(
        {
            "task_id": "evidence-task",
            "owner": "agent-a",
            "evidence": ["uncommitted.md"],
        }
    )
    return bool(
        not result.get("ok")
        and result.get("reason_codes") == ["TASK_CONTINUATION_EVIDENCE_INVALID"]
    )


def handoff_fixture_receipt(
    service: ContextMemoryService,
    identifier: str,
    *,
    schema_version: int = 2,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "path": "README.md",
        "sha256": sha256_bytes(service.git_blob_bytes(service.head() or "", "README.md") or b""),
    }
    if schema_version == 2:
        evidence["git_commit"] = service.head()
    receipt = {
        "schema_version": schema_version,
        "id": identifier,
        "project_id": "fixture-project",
        "task_id": "receipt-validation-task",
        "from_owner": "agent-a",
        "to_owner": "agent-b",
        "base_commit": service.head(),
        "created_at": "2026-07-19T09:00:00Z",
        "verified_outcomes": ["Receipt validation outcome."],
        "unresolved_risks": [],
        "next_action": "Continue only from a validated receipt.",
        "evidence": [evidence],
    }
    receipt["content_sha256"] = receipt_hash(receipt)
    return receipt


def persist_handoff_fixture(
    service: ContextMemoryService,
    receipt: dict[str, Any],
    *,
    filename_id: str | None = None,
) -> None:
    receipt["content_sha256"] = receipt_hash(receipt)
    identifier = filename_id or str(receipt["id"])
    write_json(service.path("project/context/handoffs") / f"{identifier}.json", receipt)


def handoff_fails_closed(
    service: ContextMemoryService,
    expected_code: str,
    forbidden_output: str = "",
) -> bool:
    health = service.doctor()
    listing = service.list_handoffs()
    exposed = json.dumps({"health": health, "listing": listing}, ensure_ascii=False)
    return bool(
        health.get("state") == "DEGRADED"
        and expected_code in health.get("reason_codes", [])
        and not listing.get("ok")
        and listing.get("handoffs") == []
        and (not forbidden_output or forbidden_output not in exposed)
    )


def case_handoff_receipt(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    claim = {"id": "live-handoff", "title": "Live handoff", "owner": "agent-a", "scope": ["src/**"], "evidence": ["README.md"]}
    if not apply_plan(service, service.plan_claim_task(claim)).get("ok"):
        return False
    proposal = {
        "task_id": "live-handoff",
        "from_owner": "agent-a",
        "to_owner": "agent-b",
        "verified_outcomes": ["Transaction verified."],
        "unresolved_risks": ["Fixture only."],
        "next_action": "Agent B continues.",
        "evidence": ["README.md"],
    }
    applied = apply_plan(service, service.plan_handoff(proposal))
    handoff_result = service.list_handoffs()
    handoffs = handoff_result.get("handoffs", [])
    tasks = service.list_tasks().get("tasks", [])
    task = next(item for item in tasks if item["id"] == "live-handoff")
    evidence = handoffs[0].get("evidence", []) if handoffs else []
    return bool(
        applied.get("ok")
        and handoff_result.get("ok")
        and len(handoffs) == 1
        and handoffs[0].get("schema_version") == 2
        and handoffs[0]["content_sha256"] == receipt_hash(handoffs[0])
        and evidence
        and evidence[0].get("git_commit") == service.head()
        and handoff_result.get("durability", {}).get("git_durable_receipts") == 1
        and handoff_result.get("durability", {}).get("unrecoverable_references") == 0
        and task["owner"] == "agent-b"
    )


def case_foreign_project_handoff_fails_closed(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    receipt = handoff_fixture_receipt(service, "handoff-" + "4" * 24)
    foreign_project = "foreign-private-project"
    receipt["project_id"] = foreign_project
    persist_handoff_fixture(service, receipt)
    return handoff_fails_closed(service, "HANDOFF_PROJECT_CONTAMINATION", foreign_project)


def case_malformed_handoff_fields_fail_closed(base: Path) -> bool:
    mutations: list[tuple[str, Callable[[dict[str, Any]], None], str, bool]] = [
        (
            "extra-field",
            lambda receipt: receipt.update({"private_note": "do-not-expose-private-note"}),
            "HANDOFF_RECEIPT_FIELDS_INVALID",
            True,
        ),
        (
            "schema-type",
            lambda receipt: receipt.update({"schema_version": True}),
            "HANDOFF_SCHEMA_VERSION_UNSUPPORTED",
            True,
        ),
        (
            "id-shape",
            lambda receipt: receipt.update({"id": "handoff-invalid"}),
            "HANDOFF_ID_INVALID",
            True,
        ),
        (
            "task-id",
            lambda receipt: receipt.update({"task_id": "INVALID TASK"}),
            "HANDOFF_TASK_ID_INVALID",
            True,
        ),
        (
            "owner-bound",
            lambda receipt: receipt.update({"from_owner": "a" * 129}),
            "HANDOFF_OWNER_INVALID",
            True,
        ),
        (
            "to-owner-type",
            lambda receipt: receipt.update({"to_owner": []}),
            "HANDOFF_OWNER_INVALID",
            True,
        ),
        (
            "to-owner-bound",
            lambda receipt: receipt.update({"to_owner": "a" * 129}),
            "HANDOFF_OWNER_INVALID",
            True,
        ),
        (
            "timestamp",
            lambda receipt: receipt.update({"created_at": "2026-07-19"}),
            "HANDOFF_TIMESTAMP_INVALID",
            True,
        ),
        (
            "base-commit-format",
            lambda receipt: receipt.update({"base_commit": "f" * 39}),
            "HANDOFF_BASE_COMMIT_INVALID",
            True,
        ),
        (
            "base-commit-unreachable",
            lambda receipt: receipt.update({"base_commit": "f" * 40}),
            "HANDOFF_BASE_COMMIT_NOT_REACHABLE",
            True,
        ),
        (
            "outcomes-type",
            lambda receipt: receipt.update({"verified_outcomes": "not-a-list"}),
            "HANDOFF_OUTCOMES_INVALID",
            True,
        ),
        (
            "outcomes-bound",
            lambda receipt: receipt.update({"verified_outcomes": []}),
            "HANDOFF_OUTCOMES_INVALID",
            True,
        ),
        (
            "next-action-bound",
            lambda receipt: receipt.update({"next_action": "no"}),
            "HANDOFF_NEXT_ACTION_INVALID",
            True,
        ),
        (
            "unsafe-path",
            lambda receipt: receipt["evidence"][0].update({"path": "../private.txt"}),
            "HANDOFF_EVIDENCE_INVALID",
            True,
        ),
        (
            "content-hash-tamper",
            lambda receipt: receipt.update({"content_sha256": "0" * 64}),
            "HANDOFF_RECEIPT_INVALID_OR_TAMPERED",
            False,
        ),
    ]
    for index, (name, mutate, expected_code, rehash) in enumerate(mutations):
        service = fixture(base / name)
        initialize(service)
        filename_id = f"handoff-{index + 5:024x}"
        receipt = handoff_fixture_receipt(service, filename_id)
        mutate(receipt)
        if rehash:
            persist_handoff_fixture(service, receipt, filename_id=filename_id)
        else:
            write_json(service.path("project/context/handoffs") / f"{filename_id}.json", receipt)
        if not handoff_fails_closed(service, expected_code, "do-not-expose-private-note"):
            return False
    return True


def case_handoff_transcript_marker_fails_closed(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    receipt = handoff_fixture_receipt(service, "handoff-" + "c" * 24)
    private_transcript = "<|user|> do-not-expose-raw-handoff"
    receipt["next_action"] = private_transcript
    persist_handoff_fixture(service, receipt)
    return handoff_fails_closed(service, "HANDOFF_FORBIDDEN_PAYLOAD", private_transcript)


def case_handoff_filename_id_mismatch_fails_closed(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    receipt = handoff_fixture_receipt(service, "handoff-" + "d" * 24)
    persist_handoff_fixture(service, receipt, filename_id="handoff-" + "e" * 24)
    return handoff_fails_closed(service, "HANDOFF_FILENAME_ID_MISMATCH")


def case_legacy_handoff_limitation_disclosed(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    receipt = {
        "schema_version": 1,
        "id": "handoff-" + "1" * 24,
        "project_id": "fixture-project",
        "task_id": "legacy-task",
        "from_owner": "legacy-agent",
        "to_owner": None,
        "base_commit": service.head(),
        "created_at": "2026-07-19T09:00:00Z",
        "verified_outcomes": ["Legacy outcome."],
        "unresolved_risks": [],
        "next_action": "Disclose missing historical bytes.",
        "evidence": [{"path": "README.md", "sha256": "0" * 64}],
    }
    receipt["content_sha256"] = receipt_hash(receipt)
    write_json(service.path("project/context/handoffs") / f"{receipt['id']}.json", receipt)
    health = service.doctor()
    listing = service.list_handoffs()
    warning = next(
        (item for item in health.get("warnings", []) if item.get("code") == "HISTORICAL_HANDOFF_EVIDENCE_UNRECOVERABLE"),
        None,
    )
    return bool(
        health.get("state") == "FRESH"
        and warning
        and warning.get("cause") == "CONTEXT_EVIDENCE_NOT_REACHABLE"
        and listing.get("ok")
        and [item.get("id") for item in listing.get("handoffs", [])] == [receipt["id"]]
        and health.get("handoff_durability", {}).get("unrecoverable_references") == 1
    )


def case_legacy_handoff_reachable_history_recovers(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    baseline = service.head()
    (service.project_root / "README.md").write_text("# Later committed evidence\n", encoding="utf-8")
    run(["git", "add", "README.md"], service.project_root)
    run(["git", "commit", "-m", "add later evidence"], service.project_root)
    run(["git", "config", "core.autocrlf", "true"], service.project_root)
    (service.project_root / "README.md").write_bytes(b"# Later committed evidence\r\n")
    committed_blob = service.git_blob_bytes(service.head(), "README.md")
    receipt = {
        "schema_version": 1,
        "id": "handoff-" + "2" * 24,
        "project_id": "fixture-project",
        "task_id": "legacy-recoverable-task",
        "from_owner": "legacy-agent",
        "to_owner": None,
        "base_commit": baseline,
        "created_at": "2026-07-19T09:00:00Z",
        "verified_outcomes": ["Later committed evidence remains reachable."],
        "unresolved_risks": [],
        "next_action": "Resolve the exact bytes from reachable history.",
        "evidence": [{
            "path": "README.md",
            "sha256": sha256_bytes(committed_blob or b""),
        }],
    }
    receipt["content_sha256"] = receipt_hash(receipt)
    write_json(service.path("project/context/handoffs") / f"{receipt['id']}.json", receipt)
    health = service.doctor()
    listing = service.list_handoffs()
    durability = health.get("handoff_durability", {})
    return bool(
        health.get("state") == "FRESH"
        and b"\r\n" in (service.project_root / "README.md").read_bytes()
        and not health.get("warnings")
        and listing.get("ok")
        and [item.get("id") for item in listing.get("handoffs", [])] == [receipt["id"]]
        and durability.get("legacy_recoverable_references") == 1
        and durability.get("unrecoverable_references") == 0
    )


def case_v2_handoff_missing_commit_degrades(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    receipt = {
        "schema_version": 2,
        "id": "handoff-" + "3" * 24,
        "project_id": "fixture-project",
        "task_id": "v2-missing-commit-task",
        "from_owner": "agent-a",
        "to_owner": "agent-b",
        "base_commit": service.head(),
        "created_at": "2026-07-19T09:00:00Z",
        "verified_outcomes": ["Receipt is structurally complete."],
        "unresolved_risks": [],
        "next_action": "Reject the nonexistent evidence commit.",
        "evidence": [{
            "path": "README.md",
            "sha256": sha256_bytes((service.project_root / "README.md").read_bytes()),
            "git_commit": "f" * 40,
        }],
    }
    receipt["content_sha256"] = receipt_hash(receipt)
    write_json(service.path("project/context/handoffs") / f"{receipt['id']}.json", receipt)
    health = service.doctor()
    listing = service.list_handoffs()
    durability = health.get("handoff_durability", {})
    return bool(
        health.get("state") == "DEGRADED"
        and "HANDOFF_EVIDENCE_NOT_GIT_DURABLE" in health.get("reason_codes", [])
        and not listing.get("ok")
        and listing.get("handoffs") == []
        and durability.get("git_durable_receipts") == 0
        and durability.get("unrecoverable_references") == 1
    )


def case_compaction_preserves_originals(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    for identifier in ("history-one", "history-two"):
        proposal = evidence_proposal(identifier, "cold", "historical", "historical")
        if not apply_plan(service, service.plan_upsert(proposal)).get("ok"):
            return False
    compact = {
        "record_ids": ["history-one", "history-two"],
        "summary": evidence_proposal("history-summary", "cold", "historical", "historical", "Summary preserves both historical records."),
    }
    planned = service.plan_compact(compact)
    applied = apply_plan(service, planned)
    records = service.document(COLD_REL, {}).get("records", [])
    by_id = {item["id"]: item for item in records}
    return bool(
        applied.get("ok")
        and len(records) == 3
        and by_id["history-one"]["status"] == "archived"
        and by_id["history-two"]["status"] == "archived"
        and by_id["history-summary"]["status"] == "active"
        and planned["plan"]["metadata"]["records_deleted"] == 0
    )


def case_rederived_compaction_cannot_delete_originals(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    for identifier in ("history-one", "history-two"):
        if not apply_plan(
            service,
            service.plan_upsert(
                evidence_proposal(identifier, "cold", "historical", "historical")
            ),
        ).get("ok"):
            return False
    planned = service.plan_compact(
        {
            "record_ids": ["history-one", "history-two"],
            "summary": evidence_proposal(
                "history-summary",
                "cold",
                "historical",
                "historical",
                "Summary preserves both historical records.",
            ),
        }
    )
    if not planned.get("ok"):
        return False
    plan = deepcopy(planned["plan"])
    cold_change = next(change for change in plan["changes"] if change["path"] == COLD_REL)
    cold_after = json.loads(base64.b64decode(cold_change["after_base64"]).decode("utf-8"))
    cold_after["records"] = [
        record for record in cold_after["records"] if record["id"] == "history-summary"
    ]
    cold_content = json_bytes(cold_after)
    replace_plan_after(cold_change, cold_content)
    manifest_change = next(
        change for change in plan["changes"] if change["path"] == MANIFEST_REL
    )
    manifest_after = json.loads(
        base64.b64decode(manifest_change["after_base64"]).decode("utf-8")
    )
    next(
        source for source in manifest_after["sources"] if source["tier"] == "cold"
    )["content_sha256"] = sha256_bytes(cold_content)
    replace_plan_after(manifest_change, json_bytes(manifest_after))
    rederived = persist_rederived_plan(service, plan)
    cold_before = service.read_bytes(COLD_REL)
    result = service.apply(rederived["plan_id"], True)
    records = service.document(COLD_REL, {}).get("records", [])
    return bool(
        not result.get("ok")
        and "PLAN_NOT_FOUND_OR_TAMPERED" in result.get("reason_codes", [])
        and "CONTEXT_COMPACTION_TRANSITION_INVALID"
        in result.get("validation_errors", [])
        and service.read_bytes(COLD_REL) == cold_before
        and {record.get("id") for record in records}
        == {"history-one", "history-two"}
    )


def case_rederived_compaction_cannot_rewrite_projection(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    for identifier in ("history-one", "history-two"):
        if not apply_plan(
            service,
            service.plan_upsert(
                evidence_proposal(identifier, "cold", "historical", "historical")
            ),
        ).get("ok"):
            return False
    planned = service.plan_compact(
        {
            "record_ids": ["history-one", "history-two"],
            "summary": evidence_proposal(
                "history-summary",
                "cold",
                "historical",
                "historical",
                "Summary preserves both historical records.",
            ),
        }
    )
    if not planned.get("ok"):
        return False
    plan = deepcopy(planned["plan"])
    projection_before = service.read_bytes(PROJECTION_REL)
    if projection_before is None:
        return False
    projection_after = projection_before + b"\n## Non-canonical projection\n"
    plan["changes"].append(
        {
            "path": PROJECTION_REL,
            "before_sha256": sha256_bytes(projection_before),
            "after_sha256": sha256_bytes(projection_after),
            "before_base64": base64.b64encode(projection_before).decode("ascii"),
            "after_base64": base64.b64encode(projection_after).decode("ascii"),
        }
    )
    rederived = persist_rederived_plan(service, plan)
    cold_before = service.read_bytes(COLD_REL)
    result = service.apply(rederived["plan_id"], True)
    return bool(
        not result.get("ok")
        and "PLAN_NOT_FOUND_OR_TAMPERED" in result.get("reason_codes", [])
        and "CONTEXT_COMPACTION_TRANSITION_INVALID"
        in result.get("validation_errors", [])
        and service.read_bytes(PROJECTION_REL) == projection_before
        and service.read_bytes(COLD_REL) == cold_before
    )


def case_active_decision_not_compacted(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    decision = evidence_proposal("decision-one", "warm", "decision", "project-decision")
    if not apply_plan(service, service.plan_upsert(decision)).get("ok"):
        return False
    compact = {
        "record_ids": ["decision-one"],
        "summary": evidence_proposal("decision-summary", "cold", "historical", "historical"),
    }
    result = service.plan_compact(compact)
    return not result.get("ok") and "COMPACTION_ONLY_ACTIVE_COLD_HISTORY_OR_RESEARCH" in result.get("reason_codes", [])


def case_compaction_duplicate_ids_rejected_by_creator(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    if not apply_plan(
        service,
        service.plan_upsert(
            evidence_proposal("history-one", "cold", "historical", "historical")
        ),
    ).get("ok"):
        return False
    result = service.plan_compact(
        {
            "record_ids": ["history-one", "history-one"],
            "summary": evidence_proposal(
                "history-summary", "cold", "historical", "historical"
            ),
        }
    )
    return bool(
        not result.get("ok")
        and result.get("reason_codes") == ["COMPACTION_PROPOSAL_INVALID"]
    )


def case_compaction_summary_collision_rejected_by_creator(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    if not apply_plan(
        service,
        service.plan_upsert(
            evidence_proposal("history-one", "cold", "historical", "historical")
        ),
    ).get("ok"):
        return False
    result = service.plan_compact(
        {
            "record_ids": ["history-one"],
            "summary": evidence_proposal(
                "history-one", "cold", "historical", "historical"
            ),
        }
    )
    return bool(
        not result.get("ok")
        and result.get("reason_codes") == ["COMPACTION_SUMMARY_INVALID"]
    )


def case_projection_budget_and_no_cold(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    cold = evidence_proposal("notebook-research", "cold", "research", "research-only", "NotebookLM research is cold only.")
    hot = evidence_proposal("hot-guardrail", "hot", "guardrail", "user-confirmed", "Critical guardrail is loaded at boot.")
    if not apply_plan(service, service.plan_upsert(cold)).get("ok") or not apply_plan(service, service.plan_upsert(hot)).get("ok"):
        return False
    projection = service.path(PROJECTION_REL).read_bytes()
    maximum = service.document(MANIFEST_REL, {})["budgets"]["projection_max_bytes"]
    return len(projection) <= maximum and b"Hot Guardrail" in projection and b"Notebook Research" not in projection


def case_projection_tamper_degrades(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    projection = service.read_bytes(PROJECTION_REL)
    if projection is None:
        return False
    service.path(PROJECTION_REL).write_bytes(projection + b"\n## Non-canonical projection\n")
    health = service.doctor()
    return bool(
        health.get("state") == "DEGRADED"
        and "CONTEXT_PROJECTION_NON_CANONICAL" in health.get("reason_codes", [])
    )


def case_projection_refresh_repairs_tamper(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    canonical = service.read_bytes(PROJECTION_REL)
    if canonical is None:
        return False
    service.path(PROJECTION_REL).write_bytes(canonical + b"\n## Non-canonical projection\n")
    degraded = service.doctor()
    planned = service.plan_refresh()
    applied = apply_plan(service, planned)
    recovered = service.doctor()
    return bool(
        degraded.get("state") == "DEGRADED"
        and planned.get("ok")
        and planned["plan"].get("operation") == "repair-projection"
        and {change.get("path") for change in planned["plan"].get("changes", [])}
        == {PROJECTION_REL}
        and applied.get("ok")
        and service.read_bytes(PROJECTION_REL) == canonical
        and recovered.get("state") == "FRESH"
    )


def case_projection_only_repair_rejects_source_stale_state(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    canonical_projection = service.read_bytes(PROJECTION_REL)
    hot_content = service.read_bytes(HOT_REL)
    if canonical_projection is None or hot_content is None:
        return False
    service.path(HOT_REL).write_bytes(hot_content + b"\n")
    service.path(PROJECTION_REL).write_bytes(
        canonical_projection + b"\n## Non-canonical projection\n"
    )
    planned = service.plan_refresh()
    direct_repair = service.create_plan(
        "repair-projection",
        {PROJECTION_REL: canonical_projection},
        {"repair": "canonical-projection"},
    )
    rejected = apply_plan(service, direct_repair)
    return bool(
        planned.get("ok")
        and planned["plan"].get("operation") == "refresh"
        and direct_repair.get("ok")
        and not rejected.get("ok")
        and "CONTEXT_PROJECTION_REPAIR_INVALID"
        in rejected.get("validation_errors", [])
        and service.read_bytes(HOT_REL) == hot_content + b"\n"
        and service.read_bytes(PROJECTION_REL)
        == canonical_projection + b"\n## Non-canonical projection\n"
    )


CASES: list[tuple[str, Callable[[Path], bool]]] = [
    ("initialize-plan-is-read-only", case_initialize_read_only),
    ("fresh-agent-recovery", case_fresh_recovery),
    ("wrong-project-memory-blocked", case_project_contamination),
    ("wrong-repository-memory-blocked", case_repository_contamination),
    ("malformed-manifest-fails-closed", case_malformed_manifest_fails_closed),
    ("stale-memory-loses-authority", case_stale_source_loses_authority),
    ("ancestor-refresh-remains-fresh", case_ancestor_refresh_remains_fresh),
    ("refresh-requires-committed-evidence", case_refresh_rebinds_evidence),
    ("uncommitted-evidence-rejected", case_uncommitted_evidence_rejected),
    ("untracked-evidence-rejected", case_untracked_evidence_rejected),
    ("missing-evidence-commit-degrades", case_missing_evidence_commit_degrades),
    ("unreachable-evidence-commit-degrades", case_unreachable_evidence_commit_degrades),
    ("git-evidence-hash-mismatch-degrades", case_git_evidence_hash_mismatch_degrades),
    ("same-rank-authority-conflict", case_authority_conflict),
    ("notebooklm-is-cold-research-only", case_notebooklm_cold_only),
    ("raw-conversation-rejected", case_raw_conversation_rejected),
    ("evidence-path-traversal-rejected", case_path_traversal_rejected),
    ("two-phase-confirmation-and-apply", case_transaction_confirmation_and_apply),
    ("partial-write-rolls-back", case_failure_rolls_back),
    ("post-receipt-failure-removes-false-receipt", case_post_receipt_failure_removes_false_receipt),
    ("post-receipt-cleanup-failure-is-incomplete", case_post_receipt_cleanup_failure_is_incomplete),
    ("tampered-plan-rejected", case_tampered_plan_rejected),
    ("rederived-plan-path-escalation-rejected", case_rederived_plan_path_escalation_rejected),
    ("rederived-receipt-only-handoff-rejected", case_rederived_receipt_only_handoff_rejected),
    ("expired-plan-rejected", case_expired_plan_rejected),
    ("stale-head-rejected", case_stale_head_rejected),
    ("concurrent-apply-lock", case_concurrent_lock),
    ("overlapping-task-scope-blocked", case_task_overlap_blocked),
    ("task-ledger-schema-and-privacy-parity", case_task_ledger_schema_and_privacy_parity),
    ("task-claim-schema-and-privacy-gate", case_task_claim_schema_and_privacy_gate),
    ("concurrent-task-plan-invalidated", case_concurrent_task_plan_invalidated),
    ("stale-task-base-blocks-handoff", case_stale_task_blocks_handoff),
    ("same-owner-handoff-rejected", case_same_owner_handoff_rejected),
    ("task-continuation-rebases-and-unblocks-handoff", case_task_continuation_rebases_and_unblocks_handoff),
    ("task-continuation-wrong-owner-rejected", case_task_continuation_wrong_owner_rejected),
    ("task-continuation-diverged-base-rejected", case_task_continuation_diverged_base_rejected),
    ("task-continuation-uncommitted-evidence-rejected", case_task_continuation_uncommitted_evidence_rejected),
    ("handoff-is-hash-verifiable", case_handoff_receipt),
    ("foreign-project-handoff-fails-closed", case_foreign_project_handoff_fails_closed),
    ("malformed-handoff-fields-fail-closed", case_malformed_handoff_fields_fail_closed),
    ("handoff-transcript-marker-fails-closed", case_handoff_transcript_marker_fails_closed),
    ("handoff-filename-id-mismatch-fails-closed", case_handoff_filename_id_mismatch_fails_closed),
    ("legacy-handoff-limitation-disclosed", case_legacy_handoff_limitation_disclosed),
    ("legacy-handoff-reachable-history-recovers", case_legacy_handoff_reachable_history_recovers),
    ("v2-handoff-missing-commit-degrades", case_v2_handoff_missing_commit_degrades),
    ("compaction-preserves-originals", case_compaction_preserves_originals),
    ("rederived-compaction-cannot-delete-originals", case_rederived_compaction_cannot_delete_originals),
    ("rederived-compaction-cannot-rewrite-projection", case_rederived_compaction_cannot_rewrite_projection),
    ("active-decision-not-compacted", case_active_decision_not_compacted),
    ("compaction-duplicate-ids-rejected-by-creator", case_compaction_duplicate_ids_rejected_by_creator),
    ("compaction-summary-collision-rejected-by-creator", case_compaction_summary_collision_rejected_by_creator),
    ("projection-budget-and-cold-exclusion", case_projection_budget_and_no_cold),
    ("projection-tamper-degrades", case_projection_tamper_degrades),
    ("projection-refresh-repairs-tamper", case_projection_refresh_repairs_tamper),
    ("projection-only-repair-rejects-source-stale-state", case_projection_only_repair_rejects_source_stale_state),
]


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-context-memory-") as temporary:
        root = Path(temporary)
        for index, (identifier, check) in enumerate(CASES):
            case_root = root / f"{index:02d}-{identifier}"
            try:
                passed = bool(check(case_root))
                results.append({"id": identifier, "passed": passed})
            except Exception as exc:
                results.append({"id": identifier, "passed": False, "error": f"{exc.__class__.__name__}: {exc}"})
    passed = sum(1 for item in results if item["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
