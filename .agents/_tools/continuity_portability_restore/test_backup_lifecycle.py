#!/usr/bin/env python3
"""Eight focused RS3b1 checks for restore backup lifecycle extraction."""

from __future__ import annotations

import ast
import hashlib
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
from continuity_portability_restore.backup_lifecycle import (
    RestoreBackupLifecycleMixin,
)
from continuity_portability_restore.backup_validation import (
    RestoreBackupValidationMixin,
)

METHOD_HASHES = {
    "create_restore_backup": (
        "422efceeaf8b7dcbd435b671478a7ff3cd39c6f83d2b6431c6ffece63cbacb3f"
    ),
    "restore_backup": (
        "30f1da4d666e1ba034bb7d81c3a98e4839c970aebd5b2ffc1cc84653e50febf3"
    ),
}


def method_nodes(source: str) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name in METHOD_HASHES
    }


def semantic_calls(node: ast.FunctionDef) -> set[str]:
    return {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    topology = json.loads(
        (TOOLS_ROOT / "continuity_portability_restore/topology.json").read_text()
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    facade = topology["public_facade"]
    module = "_tools/continuity_portability_restore/backup_lifecycle.py"
    validator = "_tools/continuity_portability_restore/backup_validation.py"
    shard = "_tools/continuity_portability_restore/test_backup_lifecycle.py"
    check(
        "topology-routes-lifecycle-validator-and-nested-shard",
        module in entries[facade]["depends_on"]
        and entries[module]["depends_on"] == [validator]
        and entries[module]["focused_shard"] == shard,
    )
    source = (
        TOOLS_ROOT / "continuity_portability_restore/backup_lifecycle.py"
    ).read_text()
    check(
        "lifecycle-module-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in source,
    )
    check(
        "public-method-identities-and-mro-are-preserved",
        ContinuityRestoreMixin.create_restore_backup
        is RestoreBackupLifecycleMixin.create_restore_backup
        and ContinuityRestoreMixin.restore_backup
        is RestoreBackupLifecycleMixin.restore_backup
        and RestoreBackupLifecycleMixin in ContinuityRestoreMixin.__mro__
        and RestoreBackupValidationMixin in ContinuityRestoreMixin.__mro__
        and facade_module.RestoreBackupValidationMixin is RestoreBackupValidationMixin,
    )

    methods = method_nodes(source)
    actual_hashes = {
        name: hashlib.sha256(
            ast.dump(node, include_attributes=False).encode()
        ).hexdigest()
        for name, node in methods.items()
    }
    check("method-asts-match-pre-extraction-baselines", actual_hashes == METHOD_HASHES)

    create_calls = semantic_calls(methods["create_restore_backup"])
    check(
        "create-preserves-backup-before-write-privacy-and-cleanup",
        {
            "_create_scoped_directory",
            "read_regular_bounded",
            "sha256_bytes",
            "privacy_error",
            "_atomic_scoped_bytes",
            "receipt_hash",
            "json_bytes",
            "validate_restore_backup_index",
            "_remove_scoped_tree",
        }
        <= create_calls
        and all(
            token in source
            for token in (
                "raw_conversation_stored",
                "chain_of_thought_stored",
                "secret_stored",
            )
        ),
    )

    restore_calls = semantic_calls(methods["restore_backup"])
    check(
        "rollback-preserves-reverse-order-and-byte-exact-writes",
        {
            "reversed",
            "validate_restore_backup_index",
            "_read_scoped_regular",
            "read_regular_bounded",
            "safe_join",
            "sha256_bytes",
            "_atomic_scoped_bytes",
            "_unlink_scoped_file",
        }
        <= restore_calls
        and 'reversed(plan["target_execution_order"])' in source
        and source.count("expected_before_sha256=target") == 2,
    )

    service = ContinuityRestoreMixin()
    with patch.object(
        service,
        "validate_restore_backup_index",
        return_value=["PATCHED"],
    ):
        patched = service.validate_restore_backup_index({}, {}, Path("unused"))
    check(
        "validator-self-dispatch-remains-monkeypatchable",
        patched == ["PATCHED"]
        and source.count("self.validate_restore_backup_index(") == 2,
    )

    facade_source = (
        TOOLS_ROOT / "agent_os_continuity_portability_restore.py"
    ).read_text()
    shard_source = Path(__file__).read_text()
    check(
        "module-shard-topology-and-facade-ratchets-hold",
        len(source.splitlines()) <= 240
        and len(shard_source.splitlines()) <= 210
        and len(topology["entries"]) == 11
        and len(facade_source.splitlines()) < 849,
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
