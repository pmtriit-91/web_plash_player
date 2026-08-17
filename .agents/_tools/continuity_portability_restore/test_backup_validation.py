#!/usr/bin/env python3
"""Eight focused RS3a checks for restore backup-index validation extraction."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import agent_os_continuity_portability_restore as facade_module
from agent_os_continuity_portability_restore import ContinuityRestoreMixin
from continuity_portability_restore import contracts
from continuity_portability_restore.backup_validation import (
    RestoreBackupValidationMixin,
)

BASELINE_METHOD_AST_SHA256 = (
    "71be79f8298b07f3bf1f488fbbdf51350542c00aa54d05eaf6066ecbe48ef6a8"
)
EXPECTED_REASONS = [
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_PATH_COLLISION",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
    "PORTABILITY_RESTORE_BACKUP_INVALID",
]


def method_node(source: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef)
        and node.name == "validate_restore_backup_index"
    )


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    topology = json.loads(
        (TOOLS_ROOT / "continuity_portability_restore/topology.json").read_text()
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    module = "_tools/continuity_portability_restore/backup_validation.py"
    shard = "_tools/continuity_portability_restore/test_backup_validation.py"
    check(
        "topology-routes-backup-validation-and-nested-shard",
        module in entries[topology["public_facade"]]["depends_on"]
        and entries[module]["focused_shard"] == shard,
    )

    source = (
        TOOLS_ROOT / "continuity_portability_restore/backup_validation.py"
    ).read_text()
    check(
        "backup-validation-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in source,
    )
    check(
        "public-method-identity-and-mro-are-preserved",
        ContinuityRestoreMixin.validate_restore_backup_index
        is RestoreBackupValidationMixin.validate_restore_backup_index
        and RestoreBackupValidationMixin in ContinuityRestoreMixin.__mro__
        and facade_module.RESTORE_BACKUP_FIELDS is contracts.RESTORE_BACKUP_FIELDS
        and facade_module.RESTORE_BACKUP_FILE_FIELDS
        is contracts.RESTORE_BACKUP_FILE_FIELDS,
    )

    service = ContinuityRestoreMixin()
    with patch.object(
        service,
        "validate_restore_backup_index",
        return_value=["PATCHED"],
    ):
        patched = service.validate_restore_backup_index({}, {}, Path("unused"))
    caller_sources: dict[str, str] = {}
    for method in (
        ContinuityRestoreMixin.create_restore_backup,
        ContinuityRestoreMixin.restore_backup,
        ContinuityRestoreMixin.validate_restore_receipt,
    ):
        owner_path = inspect.getsourcefile(method)
        if owner_path is not None:
            owner = Path(owner_path).resolve()
            caller_sources[str(owner)] = owner.read_text(encoding="utf-8")
    caller_token = "self.validate_restore_backup_index("
    facade_source = (
        TOOLS_ROOT / "agent_os_continuity_portability_restore.py"
    ).read_text(encoding="utf-8")
    simulated_split_sources = {
        "facade.py": caller_token,
        "backup_lifecycle.py": f"{caller_token}\n{caller_token}",
    }
    check(
        "monkeypatch-and-three-self-callers-remain-compatible",
        patched == ["PATCHED"]
        and sum(source.count(caller_token) for source in caller_sources.values()) == 3
        and sum(
            source.count(caller_token) for source in simulated_split_sources.values()
        )
        == 3,
    )

    method = method_node(source)
    method_hash = hashlib.sha256(
        ast.dump(method, include_attributes=False).encode()
    ).hexdigest()
    check(
        "method-ast-matches-pre-extraction-baseline",
        method_hash == BASELINE_METHOD_AST_SHA256,
    )

    reasons = [
        node.value.elts[0].value
        for node in ast.walk(method)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.List)
        and len(node.value.elts) == 1
        and isinstance(node.value.elts[0], ast.Constant)
    ]
    check("reason-code-order-remains-exact", reasons == EXPECTED_REASONS)

    semantic_calls = {
        node.func.id
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    check(
        "file-set-hash-byte-and-collision-guards-remain-present",
        {
            "_has_portable_path_collision",
            "read_regular_bounded",
            "receipt_hash",
            "safe_join",
            "scan_tree_bounded",
            "sha256_bytes",
            "_valid_hash",
        }
        <= semantic_calls
        and all(
            token in source
            for token in (
                "max_entries",
                "max_file_bytes",
                "max_total_bytes",
                "actual_files",
            )
        ),
    )
    shard_source = Path(__file__).read_text()
    check(
        "module-shard-and-facade-line-ratchets-hold",
        len(source.splitlines()) <= 160
        and len(shard_source.splitlines()) <= 200
        and len(facade_source.splitlines()) < 1005,
    )

    failed = [item for item in cases if not item["passed"]]
    print(
        json.dumps(
            {"ok": not failed, "passed": 8 - len(failed), "total": 8, "cases": cases},
            indent=2,
        )
    )
    raise SystemExit(2 if failed else 0)


if __name__ == "__main__":
    main()
