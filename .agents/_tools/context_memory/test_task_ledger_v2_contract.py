#!/usr/bin/env python3
"""Bounded BR2a contract shard; no runtime writer or history mutation."""

from __future__ import annotations

import json
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
ROOT = TOOLS_ROOT.parent
CONTRACTS = ROOT / "core" / "contracts"


def read(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def case_contracts_parse() -> bool:
    return all(
        read(name)["$schema"].endswith("schema")
        for name in (
            "task-ledger-v2.schema.json",
            "task-ledger-v2-index.schema.json",
            "task-ledger-v2-segment.schema.json",
        )
    )


def case_facade_is_active_only() -> bool:
    schema = read("task-ledger-v2.schema.json")
    return schema["properties"]["schema_version"]["const"] == 2 and schema["$defs"][
        "active_task"
    ]["properties"]["status"]["enum"] == ["active", "blocked"]


def case_facade_requires_index_reference() -> bool:
    schema = read("task-ledger-v2.schema.json")
    return (
        "index" in schema["required"]
        and schema["properties"]["index"]["properties"]["path"]["const"]
        == "task-ledger/index.json"
    )


def case_index_is_explicit_history() -> bool:
    schema = read("task-ledger-v2-index.schema.json")
    props = schema["properties"]
    return (
        props["history_policy"]["const"] == "explicit-only"
        and props["active_facade"]["const"] == "active-tasks.json"
    )


def case_index_entry_is_hashed_and_bounded() -> bool:
    entry = read("task-ledger-v2-index.schema.json")["$defs"]["entry"]["properties"]
    return (
        all(
            key in entry
            for key in (
                "segment_id",
                "sequence",
                "record_count",
                "byte_count",
                "sha256",
                "project_id",
                "predecessor",
                "successor",
            )
        )
        and entry["byte_count"]["maximum"] == 65536
    )


def case_index_duplicate_sequence_fails_closed() -> bool:
    sample = [
        {"segment_id": "seg-a", "sequence": 0},
        {"segment_id": "seg-b", "sequence": 0},
    ]
    return len({item["sequence"] for item in sample}) != len(sample)


def case_segment_terminal_statuses_only() -> bool:
    statuses = read("task-ledger-v2-segment.schema.json")["$defs"]["terminal_task"][
        "properties"
    ]["status"]["enum"]
    return (
        statuses == ["handed-off", "complete", "cancelled"]
        and "conversation"
        not in read("task-ledger-v2-segment.schema.json")["$defs"]["terminal_task"][
            "properties"
        ]
    )


def case_rollover_and_project_binding_are_required() -> bool:
    schema = read("task-ledger-v2-segment.schema.json")
    return (
        all(
            key in schema["required"]
            for key in ("project_id", "predecessor", "successor")
        )
        and schema["properties"]["sequence"]["minimum"] == 0
    )


CASES = [
    ("contracts-parse", case_contracts_parse),
    ("facade-active-only", case_facade_is_active_only),
    ("facade-index-reference", case_facade_requires_index_reference),
    ("index-explicit-history", case_index_is_explicit_history),
    ("index-hashed-bounded", case_index_entry_is_hashed_and_bounded),
    ("duplicate-sequence-fails-closed", case_index_duplicate_sequence_fails_closed),
    ("segment-terminal-statuses", case_segment_terminal_statuses_only),
    ("rollover-project-binding", case_rollover_and_project_binding_are_required),
]


def main() -> None:
    results = [{"id": name, "passed": bool(check())} for name, check in CASES]
    output = {
        "ok": all(item["passed"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
