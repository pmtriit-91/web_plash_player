"""Focused P2a3c3b0 proof for exact claim-only task freshness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as engine
from context_memory import task_ledger

BASE = "a" * 40
HEAD = "b" * 40

def task() -> dict[str, object]:
    return {
        "id": "claim-edge-task", "title": "Exact claim edge fixture", "owner": "codex",
        "scope": ["docs/example.md"],
        "base_commit": BASE, "status": "active",
        "claimed_at": "2026-08-11T00:00:00Z",
        "updated_at": "2026-08-11T00:00:00Z",
        "evidence": [],
    }


class Service:
    def __init__(self) -> None:
        self.parent_tasks: list[dict[str, object]] = []
        self.ledger = {"schema_version": 1, "project_id": "fixture", "tasks": [task()]}
        self.parents = f"{HEAD} {BASE}"
        self.changed = "\n".join(sorted(task_ledger.CLAIM_CHECKPOINT_PATHS))
        self.clean = True
        self.projection = b"projection\n"
        self.expected_projection = self.projection
        self.index_bytes: bytes | None = None
        self.manifest = {
            "refreshed_commit": BASE,
            "active_task_ledger_sha256": engine.sha256_bytes(engine.json_bytes(self.ledger)),
            "budgets": {"projection_max_bytes": 16384},
        }

    def enable_v2(self) -> None:
        index = {
            "schema_version": 2, "project_id": "fixture",
            "active_facade": "active-tasks.json", "history_policy": "explicit-only",
            "segment_record_limit": task_ledger.V2_RECORD_LIMIT,
            "segment_byte_limit": task_ledger.V2_BYTE_LIMIT,
            "entries": [],
        }
        self.index_bytes = engine.json_bytes(index)
        self.ledger = {
            "schema_version": 2, "project_id": "fixture", "tasks": [task()],
            "index": {
                "schema_version": 2, "path": "task-ledger/index.json",
                "sha256": engine.sha256_bytes(self.index_bytes),
            },
        }
        self.manifest["active_task_ledger_sha256"] = engine.sha256_bytes(engine.json_bytes(self.ledger))

    def head(self) -> str:
        return HEAD

    def git(self, *arguments: str) -> str | None:
        return self.parents if arguments[0] == "rev-list" else self.changed

    def git_path_is_clean(self, relative: str) -> bool:
        return self.clean and relative in task_ledger.CLAIM_CHECKPOINT_PATHS

    def git_blob_bytes(self, commit: str, relative: str) -> bytes | None:
        if relative.endswith("active-tasks.json"):
            document = self.ledger if commit == HEAD else {**self.ledger, "tasks": self.parent_tasks}
            return engine.json_bytes(document)
        if relative.endswith("context-manifest.json"):
            return engine.json_bytes(self.manifest)
        if relative.endswith("SKILL.md"):
            return self.projection
        return None

    def read_bytes(self, relative: str) -> bytes | None:
        return self.index_bytes if relative == task_ledger.V2_INDEX_REL else None

    def current_stores(self) -> dict[str, dict[str, object]]:
        return {"hot": {"records": []}, "warm": {"records": []}, "cold": {"records": []}}

    def render_projection(self, project_id, stores, ledger, maximum):
        return self.expected_projection


def admitted(service: Service) -> bool:
    return task_ledger.claim_checkpoint_is_current(service, service.ledger, service.ledger["tasks"][-1], HEAD)

def main() -> None:
    cases = []

    exact = Service()
    cases.append(("exact-single-parent-claim-edge", admitted(exact)))

    ancestor = Service()
    ancestor.parents = f"{HEAD} {'c' * 40}"
    cases.append(("arbitrary-ancestor-rejected", not admitted(ancestor)))

    merge = Service()
    merge.parents = f"{HEAD} {BASE} {'c' * 40}"
    cases.append(("merge-commit-rejected", not admitted(merge)))

    unrelated = Service()
    unrelated.changed += "\ndocs/unrelated.md"
    cases.append(("unrelated-path-rejected", not admitted(unrelated)))

    dirty = Service()
    dirty.clean = False
    cases.append(("dirty-generated-path-rejected", not admitted(dirty)))

    sibling = Service()
    sibling.parent_tasks = [task()]
    cases.append(("non-new-task-ledger-delta-rejected", not admitted(sibling)))

    timestamp = Service()
    timestamp.ledger["tasks"][-1]["updated_at"] = "2026-08-11T00:00:01Z"
    cases.append(("post-claim-task-mutation-rejected", not admitted(timestamp)))

    manifest = Service()
    manifest.manifest["refreshed_commit"] = "c" * 40
    cases.append(("manifest-binding-tamper-rejected", not admitted(manifest)))

    projection = Service()
    projection.projection = b"tampered\n"
    cases.append(("projection-tamper-rejected", not admitted(projection)))

    validation = Service()
    validation.enable_v2()
    errors, stale, conflicts = task_ledger.validate_tasks(validation, validation.ledger, "fixture")
    cases.append(("v2-validator-admits-exact-edge", not errors and not stale and not conflicts))

    failed = [case_id for case_id, passed in cases if not passed]
    print(json.dumps({"ok": not failed, "passed": len(cases) - len(failed), "total": len(cases), "cases": [{"id": case_id, "passed": passed} for case_id, passed in cases], "failed": failed}, indent=2))
    raise SystemExit(0 if not failed else 2)


if __name__ == "__main__":
    main()
