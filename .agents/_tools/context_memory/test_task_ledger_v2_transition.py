"""Bounded BR2b transition shard for task-ledger v1/v2 readers and writers."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import task_ledger

PROJECT = "universal-agent-os"
COMMIT = "a" * 40


class FakeService:
    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = files or {}
        self.reads: list[str] = []
        self.ledger: dict[str, object] | None = None
        self.captured: dict[str, object] = {}

    def binding(self):
        return {"project_id": PROJECT}

    def head(self):
        return COMMIT

    def read_bytes(self, relative: str):
        self.reads.append(relative)
        return self.files.get(relative)

    def doctor(self):
        return {"ok": True, "state": "FRESH"}

    def document(self, relative: str, default):
        if relative == facade.TASKS_REL and self.ledger is not None:
            return self.ledger
        return default

    def now(self):
        return datetime(2026, 8, 14, tzinfo=timezone.utc)

    def current_stores(self):
        return {"hot": {}, "warm": {}, "cold": {}}

    def desired_with_manifest(self, stores, tasks, manifest, extra=None):
        self.captured = {"stores": stores, "tasks": tasks, "manifest": manifest, "extra": extra}
        return {facade.TASKS_REL: b"fixture"}

    def create_plan(self, operation: str, desired, metadata):
        return {"ok": True, "plan": {"operation": operation, "metadata": metadata}}

    def commit_exists(self, commit: str):
        return isinstance(commit, str) and len(commit) == 40

    def commit_is_ancestor(self, commit: str):
        return self.commit_exists(commit)

    def committed_evidence_ref(self, relative: str):
        return ({"path": relative}, [])


def active_task(identifier: str = "task-one", status: str = "active") -> dict[str, object]:
    return {
        "id": identifier,
        "title": "Bounded task",
        "owner": "codex-maintainer",
        "scope": ["docs/example.md"],
        "base_commit": COMMIT,
        "status": status,
        "claimed_at": "2026-08-03T00:00:00Z",
        "updated_at": "2026-08-03T00:00:00Z",
        "evidence": [],
    }


def empty_v2() -> tuple[dict[str, object], FakeService]:
    index = {"schema_version": 2, "project_id": PROJECT, "active_facade": "active-tasks.json", "history_policy": "explicit-only", "segment_record_limit": 256, "segment_byte_limit": 65536, "entries": []}
    index_bytes = facade.json_bytes(index)
    ledger = {"schema_version": 2, "project_id": PROJECT, "tasks": [active_task()], "index": {"schema_version": 2, "path": "task-ledger/index.json", "sha256": facade.sha256_bytes(index_bytes)}}
    return ledger, FakeService({task_ledger.V2_INDEX_REL: index_bytes})


def install_history(
    ledger: dict[str, object], service: FakeService, identifier: str
) -> None:
    record = active_task(identifier, "handed-off")
    segment_id = "segment-00000000"
    segment = {
        "schema_version": 2,
        "project_id": PROJECT,
        "segment_id": segment_id,
        "sequence": 0,
        "records": [record],
        "predecessor": None,
        "successor": None,
    }
    segment_bytes = facade.json_bytes(segment)
    index = {
        "schema_version": 2,
        "project_id": PROJECT,
        "active_facade": "active-tasks.json",
        "history_policy": "explicit-only",
        "segment_record_limit": 256,
        "segment_byte_limit": 65536,
        "entries": [
            {
                "segment_id": segment_id,
                "sequence": 0,
                "record_count": 1,
                "byte_count": len(segment_bytes),
                "sha256": facade.sha256_bytes(segment_bytes),
                "project_id": PROJECT,
                "predecessor": None,
                "successor": None,
            }
        ],
    }
    index_bytes = facade.json_bytes(index)
    service.files[task_ledger.V2_INDEX_REL] = index_bytes
    service.files[f"{task_ledger.V2_SEGMENTS_REL}/{segment_id}.json"] = segment_bytes
    ledger["index"]["sha256"] = facade.sha256_bytes(index_bytes)


def case_v1_reader_remains_unchanged() -> bool:
    service = FakeService()
    ledger = {"schema_version": 1, "project_id": PROJECT, "tasks": [active_task()]}
    return task_ledger.validate_tasks(service, ledger, PROJECT) == ([], [], [])


def case_v2_reader_does_not_load_history() -> bool:
    ledger, service = empty_v2()
    errors, stale, conflicts = task_ledger.validate_tasks(service, ledger, PROJECT)
    return not errors and not stale and not conflicts and service.reads == [task_ledger.V2_INDEX_REL]


def case_v2_index_hash_mismatch_fails_closed() -> bool:
    ledger, service = empty_v2()
    ledger["index"]["sha256"] = "0" * 64
    errors, _, _ = task_ledger.validate_tasks(service, ledger, PROJECT)
    return any(item["code"] == "TASK_LEDGER_V2_INDEX_HASH_MISMATCH" for item in errors)


def case_v2_active_status_is_restricted() -> bool:
    ledger, service = empty_v2()
    ledger["tasks"] = [active_task(status="handed-off")]
    errors, _, _ = task_ledger.validate_tasks(service, ledger, PROJECT)
    return any(item["code"] == "TASK_LEDGER_V2_ACTIVE_STATUS_INVALID" for item in errors)


def case_first_terminal_append_is_bounded() -> bool:
    ledger, service = empty_v2()
    result = task_ledger.build_v2_terminal_append(service, ledger, active_task(status="handed-off"))
    segment = json.loads(result["segment_bytes"].decode("utf-8")) if result.get("ok") else {}
    return result.get("ok") is True and result["segment_id"] == "segment-00000000" and segment["records"][0]["status"] == "handed-off" and len(result["segment_bytes"]) <= task_ledger.V2_BYTE_LIMIT


def case_terminal_append_rejects_duplicate_id() -> bool:
    ledger, service = empty_v2()
    first = task_ledger.build_v2_terminal_append(service, ledger, active_task(status="handed-off"))
    index = json.loads(service.files[task_ledger.V2_INDEX_REL].decode("utf-8"))
    index["entries"].append({"segment_id": first["segment_id"], "sequence": 0, "record_count": 1, "byte_count": len(first["segment_bytes"]), "sha256": facade.sha256_bytes(first["segment_bytes"]), "project_id": PROJECT, "predecessor": None, "successor": None})
    service.files[task_ledger.V2_INDEX_REL] = facade.json_bytes(index)
    ledger["index"]["sha256"] = facade.sha256_bytes(service.files[task_ledger.V2_INDEX_REL])
    service.files[first["segment_path"]] = first["segment_bytes"]
    result = task_ledger.build_v2_terminal_append(service, ledger, active_task(status="handed-off"))
    return result.get("reason_codes") == ["TASK_LEDGER_V2_TERMINAL_DUPLICATE"]


def case_claim_rejects_terminal_id_reuse() -> bool:
    ledger, service = empty_v2()
    ledger["tasks"] = []
    install_history(ledger, service, "task-one")
    service.ledger = ledger
    result = task_ledger.plan_claim_task(
        service,
        {
            "id": "task-one",
            "title": "Do not reuse terminal ID",
            "owner": "codex-maintainer",
            "scope": ["docs/new.md"],
            "evidence": [],
        },
    )
    return result.get("reason_codes") == ["TASK_TERMINAL_ID_REUSE"]


def case_rekey_recovers_only_terminal_duplicate() -> bool:
    ledger, service = empty_v2()
    install_history(ledger, service, "task-one")
    service.ledger = ledger
    result = task_ledger.plan_rekey_task(
        service,
        {
            "task_id": "task-one",
            "replacement_id": "task-one-r1",
            "owner": "codex-maintainer",
            "replacement_owner": "recovery-owner",
        },
    )
    tasks = service.captured.get("tasks", {}).get("tasks", [])
    return (
        result.get("ok") is True
        and result.get("plan", {}).get("operation") == "rekey-task"
        and [item.get("id") for item in tasks] == ["task-one-r1"]
        and tasks[0].get("owner") == "recovery-owner"
        and tasks[0].get("base_commit") == COMMIT
    )


def case_rekey_rejects_nonduplicate_source() -> bool:
    ledger, service = empty_v2()
    service.ledger = ledger
    result = task_ledger.plan_rekey_task(
        service,
        {
            "task_id": "task-one",
            "replacement_id": "task-one-r1",
            "owner": "codex-maintainer",
            "replacement_owner": "recovery-owner",
        },
    )
    return result.get("reason_codes") == ["TASK_REKEY_SOURCE_NOT_TERMINAL_DUPLICATE"]


def case_rollover_links_predecessor() -> bool:
    ledger, service = empty_v2()
    records = [{"id": f"terminal-{index}", "status": "handed-off"} for index in range(256)]
    segment = {"schema_version": 2, "project_id": PROJECT, "segment_id": "segment-00000000", "sequence": 0, "records": records, "predecessor": None, "successor": None}
    segment_bytes = facade.json_bytes(segment)
    index = {"schema_version": 2, "project_id": PROJECT, "active_facade": "active-tasks.json", "history_policy": "explicit-only", "segment_record_limit": 256, "segment_byte_limit": 65536, "entries": [{"segment_id": "segment-00000000", "sequence": 0, "record_count": 256, "byte_count": len(segment_bytes), "sha256": facade.sha256_bytes(segment_bytes), "project_id": PROJECT, "predecessor": None, "successor": None}]}
    service.files[task_ledger.V2_INDEX_REL] = facade.json_bytes(index)
    ledger["index"]["sha256"] = facade.sha256_bytes(service.files[task_ledger.V2_INDEX_REL])
    service.files[f"{task_ledger.V2_SEGMENTS_REL}/segment-00000000.json"] = segment_bytes
    result = task_ledger.build_v2_terminal_append(service, ledger, active_task("next-terminal", "handed-off"))
    return result.get("ok") is True and result["segment_id"] == "segment-00000001" and json.loads(result["segment_bytes"])["predecessor"] == "segment-00000000"


def case_existing_segments_are_not_rewritten() -> bool:
    ledger, service = empty_v2()
    captured: dict[str, object] = {}
    service.document = lambda relative, default: ledger if relative == facade.TASKS_REL else {}
    service.now = lambda: datetime(2026, 8, 3, tzinfo=timezone.utc)
    service.evidence_refs = lambda paths: ([], [])
    service.current_stores = lambda: {"hot": {}, "warm": {}, "cold": {}}
    service.desired_with_manifest = lambda stores, tasks, manifest, extra: captured.update(tasks=tasks, extra=extra) or {facade.TASKS_REL: b"x"}
    service.create_plan = lambda operation, desired, metadata: {"ok": True, "metadata": metadata}
    result = task_ledger.plan_handoff(service, {"task_id": "task-one", "from_owner": "codex-maintainer", "to_owner": None, "verified_outcomes": ["done"], "unresolved_risks": [], "next_action": "next", "evidence": []})
    extra = captured.get("extra", {})
    return result.get("ok") is True and captured["tasks"]["tasks"] == [] and task_ledger.V2_INDEX_REL in extra and any(path.startswith(task_ledger.V2_SEGMENTS_REL) for path in extra)


def case_corrupt_history_fails_closed() -> bool:
    ledger, service = empty_v2()
    index = json.loads(service.files[task_ledger.V2_INDEX_REL].decode("utf-8"))
    index["entries"] = [{"segment_id": "segment-00000000", "sequence": 0, "record_count": 1, "byte_count": 2, "sha256": "0" * 64, "project_id": PROJECT, "predecessor": None, "successor": None}]
    service.files[task_ledger.V2_INDEX_REL] = facade.json_bytes(index)
    ledger["index"]["sha256"] = facade.sha256_bytes(service.files[task_ledger.V2_INDEX_REL])
    service.files[f"{task_ledger.V2_SEGMENTS_REL}/segment-00000000.json"] = b"{}"
    result = task_ledger.build_v2_terminal_append(service, ledger, active_task("next-terminal", "handed-off"))
    return result.get("reason_codes") == ["TASK_LEDGER_V2_SEGMENT_HASH_OR_SIZE_MISMATCH"]


def case_facade_reexports_transition_boundary() -> bool:
    return facade.task_ledger.build_v2_terminal_append is task_ledger.build_v2_terminal_append


def case_plan_metadata_accepts_v2_terminal_paths() -> bool:
    service = object.__new__(facade.ContextMemoryService)
    segment_id = "segment-00000000"
    handoff_id = "handoff-" + "a" * 24
    handoff_path = f"{facade.HANDOFF_DIR_REL}/{handoff_id}.json"
    paths = {facade.TASKS_REL, facade.MANIFEST_REL, facade.PROJECTION_REL, handoff_path, task_ledger.V2_INDEX_REL, f"{task_ledger.V2_SEGMENTS_REL}/{segment_id}.json"}
    metadata = {"task_id": "task-one", "handoff_id": handoff_id, "ledger_mode": "v2-terminal-segment", "segment_id": segment_id, "segment_path": f"{task_ledger.V2_SEGMENTS_REL}/{segment_id}.json", "index_path": task_ledger.V2_INDEX_REL}
    return service.validate_plan_metadata("handoff", metadata, paths) == []


def case_plan_metadata_accepts_rekey_paths() -> bool:
    service = object.__new__(facade.ContextMemoryService)
    metadata = {
        "task_id": "task-one",
        "replacement_id": "task-one-r1",
        "owner": "codex-maintainer",
        "replacement_owner": "recovery-owner",
        "previous_base_commit": "b" * 40,
        "continued_base_commit": COMMIT,
    }
    paths = {facade.TASKS_REL, facade.MANIFEST_REL, facade.PROJECTION_REL}
    return service.validate_plan_metadata("rekey-task", metadata, paths) == []


CASES = [
    ("v1-reader-unchanged", case_v1_reader_remains_unchanged),
    ("v2-reader-no-history-load", case_v2_reader_does_not_load_history),
    ("v2-index-hash-fail-closed", case_v2_index_hash_mismatch_fails_closed),
    ("v2-active-status-restricted", case_v2_active_status_is_restricted),
    ("first-terminal-append-bounded", case_first_terminal_append_is_bounded),
    ("terminal-duplicate-rejected", case_terminal_append_rejects_duplicate_id),
    ("claim-terminal-id-reuse-rejected", case_claim_rejects_terminal_id_reuse),
    ("rekey-terminal-duplicate-only", case_rekey_recovers_only_terminal_duplicate),
    ("rekey-nonduplicate-rejected", case_rekey_rejects_nonduplicate_source),
    ("rollover-links-predecessor", case_rollover_links_predecessor),
    ("immutable-segment-not-rewritten", case_existing_segments_are_not_rewritten),
    ("corrupt-history-fail-closed", case_corrupt_history_fails_closed),
    ("v2-plan-metadata-paths", case_plan_metadata_accepts_v2_terminal_paths),
    ("rekey-plan-metadata-paths", case_plan_metadata_accepts_rekey_paths),
]


def main() -> None:
    results = [{"id": name, "passed": bool(check())} for name, check in CASES]
    output = {"ok": all(item["passed"] for item in results), "passed": sum(item["passed"] for item in results), "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
