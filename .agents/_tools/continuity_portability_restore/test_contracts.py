#!/usr/bin/env python3
"""Eight focused checks for shared restore contracts extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import agent_os_continuity_portability_restore as facade
from continuity_portability_restore import contracts


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    topology = json.loads(
        (TOOLS_ROOT / "continuity_portability_restore/topology.json").read_text(
            encoding="utf-8"
        )
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    contract_path = "_tools/continuity_portability_restore/contracts.py"
    check(
        "topology-routes-contracts-and-nested-shard",
        contract_path
        in entries["_tools/agent_os_continuity_portability_restore.py"]["depends_on"]
        and entries[contract_path]["focused_shard"]
        == "_tools/continuity_portability_restore/test_contracts.py",
    )

    source = (TOOLS_ROOT / "continuity_portability_restore/contracts.py").read_text(
        encoding="utf-8"
    )
    check(
        "contracts-module-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in source
        and "from agent_os_continuity_portability_restore" not in source,
    )

    names = (
        "BACKUP_ID",
        "RESTORE_RECEIPT_ID",
        "RESTORE_PLAN_FIELDS",
        "RESTORE_TARGET_FIELDS",
        "RESTORE_BACKUP_FIELDS",
        "RESTORE_BACKUP_FILE_FIELDS",
        "RESTORE_RECEIPT_FIELDS",
        "_PLAN_ID",
        "_RECEIPT_DIR_AGENT_REL",
        "_valid_hash",
        "_valid_time",
        "_has_portable_path_collision",
    )
    check(
        "facade-reexports-preserve-object-identity",
        all(getattr(facade, name) is getattr(contracts, name) for name in names),
    )
    check(
        "restore-identifiers-preserve-exact-patterns",
        contracts.BACKUP_ID.fullmatch("continuity-restore-backup-" + "a" * 24)
        is not None
        and contracts.RESTORE_RECEIPT_ID.fullmatch("continuity-restore-" + "b" * 24)
        is not None
        and contracts._PLAN_ID.fullmatch("c" * 24) is not None,
    )
    check(
        "hash-validation-preserves-nullability",
        contracts._valid_hash("a" * 64)
        and contracts._valid_hash(None, nullable=True)
        and not contracts._valid_hash(None)
        and not contracts._valid_hash("g" * 64),
    )
    check(
        "time-validation-requires-aware-values",
        contracts._valid_time("2026-08-05T03:00:00Z")
        and not contracts._valid_time("2026-08-05T03:00:00")
        and not contracts._valid_time("invalid"),
    )
    check(
        "portable-casefold-collision-is-preserved",
        contracts._has_portable_path_collision(
            [{"path": "Docs/Status.md"}, {"path": "docs/status.md"}]
        ),
    )
    check(
        "same-and-invalid-paths-do-not-invent-collisions",
        not contracts._has_portable_path_collision(
            [
                {"path": "docs/status.md"},
                {"path": "docs/status.md"},
                {"path": "../unsafe"},
                {"missing": "path"},
            ]
        ),
    )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases), "cases": cases}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
