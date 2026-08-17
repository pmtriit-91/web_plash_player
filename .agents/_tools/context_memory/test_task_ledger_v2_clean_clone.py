#!/usr/bin/env python3
"""Bounded BR2d clean-clone integrity proof for task-ledger v2."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import task_ledger

PROJECT = "clean-clone-project"
COMMIT = "a" * 40


class CloneService:
    def __init__(self, root: Path):
        self.root = root
        self.reads: list[str] = []

    def binding(self):
        return {"project_id": PROJECT}

    def head(self):
        return COMMIT

    def read_bytes(self, relative: str):
        self.reads.append(relative)
        path = self.root / relative
        return path.read_bytes() if path.is_file() else None


def terminal(identifier: str, status: str = "complete") -> dict[str, object]:
    return {"id": identifier, "title": "Terminal task", "owner": "codex-maintainer", "scope": ["docs/example.md"], "base_commit": COMMIT, "status": status, "claimed_at": "2026-08-03T00:00:00Z", "updated_at": "2026-08-03T00:00:00Z", "evidence": []}


def materialize(base: Path) -> tuple[dict[str, object], CloneService]:
    segments = [[terminal("done-one"), terminal("cancelled-one", "cancelled")], [terminal("done-two")]]
    entries = []
    for sequence, records in enumerate(segments):
        segment_id = f"segment-{sequence:08d}"
        predecessor = f"segment-{sequence - 1:08d}" if sequence else None
        successor = f"segment-{sequence + 1:08d}" if sequence + 1 < len(segments) else None
        segment = {"schema_version": 2, "project_id": PROJECT, "segment_id": segment_id, "sequence": sequence, "records": records, "predecessor": predecessor, "successor": successor}
        content = facade.json_bytes(segment)
        relative = f"{task_ledger.V2_SEGMENTS_REL}/{segment_id}.json"
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append({"segment_id": segment_id, "sequence": sequence, "record_count": len(records), "byte_count": len(content), "sha256": facade.sha256_bytes(content), "project_id": PROJECT, "predecessor": predecessor, "successor": successor})
    index = {"schema_version": 2, "project_id": PROJECT, "active_facade": "active-tasks.json", "history_policy": "explicit-only", "segment_record_limit": 256, "segment_byte_limit": 65536, "entries": entries}
    index_bytes = facade.json_bytes(index)
    index_path = base / task_ledger.V2_INDEX_REL
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(index_bytes)
    ledger = {"schema_version": 2, "project_id": PROJECT, "tasks": [], "index": {"schema_version": 2, "path": "task-ledger/index.json", "sha256": facade.sha256_bytes(index_bytes)}}
    return ledger, CloneService(base)


def index_and_history(ledger: dict[str, object], service: CloneService):
    index, errors = task_ledger._v2_index(service, ledger, PROJECT)
    history, history_errors = task_ledger._v2_history(service, index or {}, PROJECT)
    return index, history, [*errors, *history_errors]


def case_clean_clone_recovers_history(base: Path) -> bool:
    ledger, service = materialize(base)
    index, history, errors = index_and_history(ledger, service)
    return not errors and index is not None and [item["id"] for item in history] == ["done-one", "cancelled-one", "done-two"]


def case_default_reader_skips_segments(base: Path) -> bool:
    ledger, service = materialize(base)
    errors, stale, conflicts = task_ledger.validate_tasks(service, ledger, PROJECT)
    return not errors and not stale and not conflicts and service.reads == [task_ledger.V2_INDEX_REL]


def case_explicit_filter_and_page(base: Path) -> bool:
    ledger, service = materialize(base)
    _, history, errors = index_and_history(ledger, service)
    filtered = [item for item in history if item["status"] == "complete"]
    offset, limit = 1, 1
    return not errors and [item["id"] for item in filtered[offset : offset + limit]] == ["done-two"] and len(filtered) == 2


def case_missing_segment_fails_closed(base: Path) -> bool:
    ledger, service = materialize(base)
    (base / f"{task_ledger.V2_SEGMENTS_REL}/segment-00000001.json").unlink()
    return any(item["code"] == "TASK_LEDGER_V2_SEGMENT_MISSING" for item in index_and_history(ledger, service)[2])


def case_hash_mismatch_fails_closed(base: Path) -> bool:
    ledger, service = materialize(base)
    ledger["index"]["sha256"] = "0" * 64
    return task_ledger._v2_index(service, ledger, PROJECT)[1][0]["code"] == "TASK_LEDGER_V2_INDEX_HASH_MISMATCH"


def case_duplicate_ids_fail_closed(base: Path) -> bool:
    ledger, service = materialize(base)
    path = base / f"{task_ledger.V2_SEGMENTS_REL}/segment-00000001.json"
    segment = json.loads(path.read_text())
    segment["records"][0]["id"] = "done-one"
    content = facade.json_bytes(segment)
    path.write_bytes(content)
    index = json.loads((base / task_ledger.V2_INDEX_REL).read_text())
    index["entries"][1].update(byte_count=len(content), sha256=facade.sha256_bytes(content))
    index_bytes = facade.json_bytes(index)
    (base / task_ledger.V2_INDEX_REL).write_bytes(index_bytes)
    ledger["index"]["sha256"] = facade.sha256_bytes(index_bytes)
    return any(item["code"] == "TASK_LEDGER_V2_HISTORY_DUPLICATE_OR_INVALID_ID" for item in index_and_history(ledger, service)[2])


def case_duplicate_sequence_fails_closed(base: Path) -> bool:
    ledger, service = materialize(base)
    index_path = base / task_ledger.V2_INDEX_REL
    index = json.loads(index_path.read_text())
    index["entries"][1]["sequence"] = 0
    content = facade.json_bytes(index)
    index_path.write_bytes(content)
    ledger["index"]["sha256"] = facade.sha256_bytes(content)
    return any(item["code"] == "TASK_LEDGER_V2_INDEX_ENTRY_INVALID" for item in task_ledger._v2_index(service, ledger, PROJECT)[1])


def case_project_and_rollover_fail_closed(base: Path) -> bool:
    ledger, service = materialize(base)
    index_path = base / task_ledger.V2_INDEX_REL
    original = json.loads(index_path.read_text())
    results = []
    for mutate, expected in ((lambda value: value.__setitem__("project_id", "foreign"), "TASK_LEDGER_V2_INDEX_FIELDS_INVALID"), (lambda value: value["entries"][0].__setitem__("successor", None), "TASK_LEDGER_V2_ROLLOVER_INVALID")):
        index = json.loads(json.dumps(original))
        mutate(index)
        content = facade.json_bytes(index)
        index_path.write_bytes(content)
        ledger["index"]["sha256"] = facade.sha256_bytes(content)
        results.append(any(item["code"] == expected for item in task_ledger._v2_index(service, ledger, PROJECT)[1]))
    return all(results)


CASES = [("clean-clone-history", case_clean_clone_recovers_history), ("default-reader-no-history", case_default_reader_skips_segments), ("explicit-filter-page", case_explicit_filter_and_page), ("missing-segment", case_missing_segment_fails_closed), ("hash-mismatch", case_hash_mismatch_fails_closed), ("duplicate-id", case_duplicate_ids_fail_closed), ("duplicate-sequence", case_duplicate_sequence_fails_closed), ("project-rollover", case_project_and_rollover_fail_closed)]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br2d-") as temporary:
        for index, (name, check) in enumerate(CASES):
            base = Path(temporary) / str(index)
            base.mkdir()
            try:
                passed, error = bool(check(base)), None
            except Exception as exc:  # noqa: BLE001 - bounded case diagnostics
                passed, error = False, str(exc)
            results.append({"id": name, "passed": passed, **({"error": error} if error else {})})
    output = {"ok": all(item["passed"] for item in results), "passed": sum(item["passed"] for item in results), "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
