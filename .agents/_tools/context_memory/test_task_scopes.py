#!/usr/bin/env python3
"""Focused Context Memory task-scope compatibility checks."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

from agent_os_context_memory import (
    ContextMemoryService,
    valid_task_scope,
)

FIXTURE_TASK_ID = "task-scope-compatibility-fixture"
FIXTURE_OWNER = "fixture-owner"


def add_result(
    results: list[dict[str, Any]], identifier: str, passed: bool, **details: Any
) -> None:
    results.append({"id": identifier, "passed": passed, **details})


def isolated_task_ledger(
    service: ContextMemoryService, ledger: dict[str, Any]
) -> dict[str, Any]:
    fixture = deepcopy(ledger)
    timestamp = "2026-08-07T00:00:00Z"
    fixture["tasks"] = [
        {
            "id": FIXTURE_TASK_ID,
            "title": "Task-scope compatibility fixture",
            "owner": FIXTURE_OWNER,
            "scope": ["docs/fixture.md"],
            "base_commit": service.head(),
            "status": "active",
            "claimed_at": timestamp,
            "updated_at": timestamp,
            "evidence": [],
        }
    ]
    return fixture


def main() -> None:
    service = ContextMemoryService(ROOT)
    ledger = service.document("project/context/active-tasks.json", {})
    project_id = str(service.binding().get("project_id", ""))
    results: list[dict[str, Any]] = []
    accepted = (".agents/_tools/agent_os_paths.py", ".agents/project/context/**")
    add_result(
        results,
        "repository-path-and-bounded-glob-accepted",
        all(valid_task_scope(item) for item in accepted),
    )
    unsafe = (
        "../escape",
        "/absolute",
        "~/home",
        "C:/drive",
        "\\\\server\\share",
        "docs//empty",
        "docs/control\x1f.md",
    )
    add_result(
        results,
        "unsafe-path-forms-rejected",
        all(not valid_task_scope(item) for item in unsafe),
    )
    unsupported = (
        "docs/**/nested",
        "docs/file?.py",
        "docs/[ab].py",
        "docs/foo**bar.py",
        "docs/file*.py",
    )
    add_result(
        results,
        "new-file-glob-or-ambiguous-glob-rejected",
        all(not valid_task_scope(item) for item in unsupported),
    )
    opaque = "NotebookLM notebook: Universal Agent OS — Architecture Evolution AOS-13"
    add_result(
        results,
        "opaque-and-file-glob-scopes-are-historical-only",
        (
            not valid_task_scope(opaque)
            and valid_task_scope(opaque, allow_legacy=True)
            and valid_task_scope(
                ".agents/_tools/test-continuity*.py", allow_legacy=True
            )
            and not valid_task_scope("Unknown opaque: scope", allow_legacy=True)
        ),
    )
    errors, stale, conflicts = service.validate_tasks(ledger, project_id)
    add_result(
        results,
        "current-ledger-historical-scopes-compatible",
        not errors and not stale and not conflicts,
        details={"errors": errors, "stale": stale, "conflicts": conflicts},
    )
    active_opaque = isolated_task_ledger(service, ledger)
    task = active_opaque["tasks"][0]
    task["scope"] = [opaque]
    errors, _stale, _conflicts = service.validate_tasks(active_opaque, project_id)
    add_result(
        results,
        "active-opaque-ledger-scope-rejected",
        any(
            item.get("code") == "TASK_SCOPE_UNSAFE" and item.get("id") == task.get("id")
            for item in errors
        ),
    )
    rejected = service.plan_claim_task(
        {
            "id": "opaque-scope-proposal",
            "title": "Reject opaque task scope proposal",
            "owner": "fixture-owner",
            "scope": [opaque],
            "evidence": [],
        }
    )
    add_result(
        results,
        "new-opaque-scope-proposal-rejected",
        (
            not rejected.get("ok")
            and rejected.get("reason_codes") == ["TASK_SCOPE_UNSAFE"]
        ),
    )
    continuation_task = isolated_task_ledger(service, ledger)["tasks"][0]
    continuation_ledger = {
        "schema_version": 1,
        "project_id": project_id,
        "tasks": [
            continuation_task,
            {
                **deepcopy(continuation_task),
                "id": "historical-task-scope-fixture",
                "title": "Historical task-scope compatibility fixture",
                "scope": [".agents/_tools/test-continuity*.py"],
                "status": "handed-off",
            },
        ],
    }
    original_document = service.document

    def fixture_document(relative: str, default: Any) -> Any:
        if relative == "project/context/active-tasks.json":
            return continuation_ledger
        return original_document(relative, default)

    with patch.object(service, "document", side_effect=fixture_document):
        continued = service.plan_continue_task(
            {
                "task_id": FIXTURE_TASK_ID,
                "owner": FIXTURE_OWNER,
                "evidence": [],
            }
        )
    add_result(
        results,
        "historical-globs-do-not-block-continuation",
        bool(
            continued.get("ok")
            and continued.get("plan", {}).get("operation") == "continue-task"
        ),
    )
    passed = sum(1 for item in results if item["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
