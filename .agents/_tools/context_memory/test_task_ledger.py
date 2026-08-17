"""BR2b0 parity shard for the v1 task-ledger extraction boundary."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import task_ledger


def case_topology_declares_one_way_facade() -> bool:
    topology = json.loads((ROOT / "_tools" / "context_memory" / "topology.json").read_text(encoding="utf-8"))
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    return (
        topology["schema_version"] == 1
        and entries["_tools/agent_os_context_memory.py"]["depends_on"] == ["_tools/context_memory/task_ledger.py"]
        and entries["_tools/context_memory/task_ledger.py"]["role"] == "v1-validation-and-plan-builder"
    )


def case_scope_validator_reexport_is_exact() -> bool:
    values = ["docs/example.md", "docs/**", "../escape", "NotebookLM notebook: demo"]
    return all(facade.valid_task_scope(value, allow_legacy=True) == task_ledger.valid_task_scope(value, allow_legacy=True) for value in values)


def case_scope_overlap_reexport_is_exact() -> bool:
    pairs = [(["docs/**"], ["docs/example.md"]), (["docs/a"], ["tools/b"]), (["."], ["docs/a"])]
    return all(facade.ContextMemoryService.scopes_overlap(left, right) == task_ledger.scopes_overlap(left, right) for left, right in pairs)


def case_validation_wrapper_preserves_v1_errors() -> bool:
    service = object.__new__(facade.ContextMemoryService)
    service.head = lambda: "a" * 40
    ledger = {"schema_version": 1, "project_id": "foreign", "tasks": [{"id": "bad id"}]}
    return service.validate_tasks(ledger, "fixture") == task_ledger.validate_tasks(service, ledger, "fixture")


def _delegation_case(method: str, module_name: str) -> bool:
    service = object.__new__(facade.ContextMemoryService)
    marker = {"method": method}
    original = getattr(task_ledger, module_name)
    setattr(task_ledger, module_name, lambda received, proposal=None: marker)
    try:
        result = getattr(service, method)({"probe": True})
    finally:
        setattr(task_ledger, module_name, original)
    return result is marker


def case_claim_api_delegates():
    return _delegation_case("plan_claim_task", "plan_claim_task")


def case_continue_api_delegates():
    return _delegation_case("plan_continue_task", "plan_continue_task")


def _continuation_service(sibling_owner: str, sibling_base: str = "a" * 40):
    service = object.__new__(facade.ContextMemoryService)
    head = "b" * 40

    def task(identifier: str, owner: str, scope: str, base: str) -> dict[str, object]:
        return {
            "id": identifier,
            "title": "Bounded continuation fixture",
            "owner": owner,
            "scope": [scope],
            "base_commit": base,
            "status": "active",
            "claimed_at": "2026-08-05T00:00:00Z",
            "updated_at": "2026-08-05T00:00:00Z",
            "evidence": [],
        }

    ledger = {
        "schema_version": 1,
        "project_id": "fixture",
        "tasks": [
            task("target-task", "codex", "docs/target.md", "a" * 40),
            task("sibling-task", sibling_owner, "docs/sibling.md", sibling_base),
        ],
    }
    service.binding = lambda: {"project_id": "fixture"}
    service.document = lambda path, default: ledger if str(path).endswith("active-tasks.json") else default
    service.head = lambda: head
    service.commit_exists = lambda commit: commit in {"a" * 40, head}
    service.commit_is_ancestor = lambda commit: commit == "a" * 40
    service.current_stores = dict
    service.desired_with_manifest = lambda stores, tasks, manifest: {"tasks": tasks}
    service.create_plan = lambda operation, desired, metadata: {"ok": True, "desired": desired, "metadata": metadata}
    service.now = lambda: datetime(2026, 8, 5, tzinfo=timezone.utc)
    return service


def case_same_owner_stale_sibling_allows_sequential_continue() -> bool:
    service = _continuation_service("codex")
    result = task_ledger.plan_continue_task(service, {"task_id": "target-task", "owner": "codex", "evidence": []})
    tasks = result.get("desired", {}).get("tasks", {}).get("tasks", [])
    by_id = {item["id"]: item for item in tasks}
    return result.get("ok") is True and by_id["target-task"]["base_commit"] == "b" * 40 and by_id["sibling-task"]["base_commit"] == "a" * 40


def case_foreign_or_diverged_stale_sibling_still_blocks() -> bool:
    proposal = {"task_id": "target-task", "owner": "codex", "evidence": []}
    foreign = task_ledger.plan_continue_task(_continuation_service("other"), proposal)
    diverged = task_ledger.plan_continue_task(_continuation_service("codex", "c" * 40), proposal)
    return foreign.get("reason_codes") == ["TASK_CONTINUATION_LEDGER_INVALID"] and diverged.get("reason_codes") == ["TASK_CONTINUATION_LEDGER_INVALID"]


def case_handoff_and_list_api_delegates() -> bool:
    handoff = _delegation_case("plan_handoff", "plan_handoff")
    service = object.__new__(facade.ContextMemoryService)
    marker = {"method": "list_tasks"}
    original = task_ledger.list_tasks
    task_ledger.list_tasks = lambda received: marker
    try:
        listed = service.list_tasks()
    finally:
        task_ledger.list_tasks = original
    return handoff and listed is marker


CASES = [
    ("topology-one-way-facade", case_topology_declares_one_way_facade),
    ("scope-validator-reexport", case_scope_validator_reexport_is_exact),
    ("scope-overlap-reexport", case_scope_overlap_reexport_is_exact),
    ("validation-v1-errors", case_validation_wrapper_preserves_v1_errors),
    ("claim-api-delegation", case_claim_api_delegates),
    ("continue-api-delegation", case_continue_api_delegates),
    ("same-owner-stale-sibling-continuation", case_same_owner_stale_sibling_allows_sequential_continue),
    ("foreign-or-diverged-stale-sibling-blocked", case_foreign_or_diverged_stale_sibling_still_blocks),
    ("handoff-list-delegation", case_handoff_and_list_api_delegates),
    ("facade-has-public-cli-methods", lambda: all(hasattr(facade.ContextMemoryService, name) for name in ("plan_claim_task", "plan_continue_task", "plan_handoff", "list_tasks"))),
]


def main() -> None:
    results = [{"id": name, "passed": bool(check())} for name, check in CASES]
    output = {"ok": all(item["passed"] for item in results), "passed": sum(item["passed"] for item in results), "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
