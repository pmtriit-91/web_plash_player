#!/usr/bin/env python3
"""Focused contract for the migration fixture Git command envelopes."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

TARGET = Path(__file__).with_name("test_agent_os_migrations.py")


def load_target() -> Any:
    spec = importlib.util.spec_from_file_location("migration_fixture_target", TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration fixture target cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    target = load_target()
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> None:
        calls.append({"command": command, "timeout": kwargs.get("timeout")})

    fixture = Path("fixture-root")
    with patch.object(target.subprocess, "run", side_effect=fake_run):
        target.initialize_git(fixture)
        target.git(fixture, "status", "--short")

    expected = [
        {"command": ["git", "init", "-q"], "timeout": 30},
        {
            "command": ["git", "config", "user.name", "Agent OS Migration Fixture"],
            "timeout": 30,
        },
        {
            "command": [
                "git",
                "config",
                "user.email",
                "migration-fixture@agent-os.invalid",
            ],
            "timeout": 30,
        },
        {"command": ["git", "add", "."], "timeout": 90},
        {
            "command": ["git", "commit", "-qm", "fixture baseline"],
            "timeout": 30,
        },
        {"command": ["git", "status", "--short"], "timeout": 30},
    ]
    results = [
        {
            "id": "exact-git-add-gets-windows-safe-envelope",
            "passed": calls[3] == expected[3],
        },
        {
            "id": "all-other-fixture-git-commands-keep-default-envelope",
            "passed": calls[:3] + calls[4:] == expected[:3] + expected[4:],
        },
        {
            "id": "command-order-and-bytes-remain-exact",
            "passed": calls == expected,
        },
    ]
    passed = sum(bool(item["passed"]) for item in results)
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
