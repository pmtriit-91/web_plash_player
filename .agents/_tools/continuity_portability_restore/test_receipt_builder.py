#!/usr/bin/env python3
"""Eight focused RS4b checks for restore receipt-builder extraction."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_context_memory import json_bytes
from agent_os_continuity_portability_restore import ContinuityRestoreMixin
from continuity_portability_restore.receipt_builder import RestoreReceiptBuilderMixin

BASELINE_METHOD_AST_SHA256 = (
    "81b84595f988f28eadb45fffe14a5372f036f5b5da38db6b7e83716be5c8c514"
)
HASH = "a" * 64
BOUNDS = {"max_entries": 4, "max_file_bytes": 1024}
BOUNDS |= {"max_manifest_bytes": 8192, "max_total_bytes": 4096}


def method_node(source: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "build_restore_receipt"
    )


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": bool(passed), **details})

    module = "_tools/continuity_portability_restore/receipt_builder.py"
    shard = "_tools/continuity_portability_restore/test_receipt_builder.py"
    topology_path = TOOLS_ROOT / "continuity_portability_restore/topology.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    check(
        "topology-routes-receipt-builder-and-focused-shard",
        module in entries[topology["public_facade"]]["depends_on"]
        and entries[module]["focused_shard"] == shard
        and entries[module]["depends_on"]
        == [
            "_tools/agent_os_context_memory.py",
            "_tools/agent_os_continuity_portability_foundation.py",
        ],
    )

    source_path = TOOLS_ROOT / "continuity_portability_restore/receipt_builder.py"
    source = source_path.read_text(encoding="utf-8")
    facade_path = TOOLS_ROOT / "agent_os_continuity_portability_restore.py"
    facade_source = facade_path.read_text(encoding="utf-8")
    check(
        "receipt-builder-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in source
        and "from agent_os_continuity_portability_restore" not in source,
    )
    check(
        "public-method-identity-and-mro-are-preserved",
        ContinuityRestoreMixin.build_restore_receipt
        is RestoreReceiptBuilderMixin.build_restore_receipt
        and RestoreReceiptBuilderMixin in ContinuityRestoreMixin.__mro__,
    )

    method_hash = hashlib.sha256(
        ast.dump(method_node(source), include_attributes=False).encode()
    ).hexdigest()
    check(
        "method-ast-matches-pre-extraction-baseline",
        method_hash == BASELINE_METHOD_AST_SHA256,
    )

    class Probe(ContinuityRestoreMixin):
        def __init__(self, root: Path) -> None:
            self.root = root

        def now(self) -> datetime:
            return datetime(2026, 8, 5, tzinfo=UTC)

        def policy(self) -> tuple[dict[str, Any], list[str]]:
            return {"bounds": BOUNDS}, []

        def validate_git_contract_provenance(self, *_: Any) -> bool:
            return True

        def derived_owner_mode(self, _: str) -> tuple[str, str]:
            return ("application", "replace")

        def project_path(self, relative: str) -> Path:
            return self.root / relative

        def verified_restore_backup_root(self, **_: Any) -> Path:
            return self.root / ".agents/project/context/continuity-restore-backups"

        def _safe_directory_stat(self, path: Path) -> Any:
            return path.stat()

        def validate_restore_backup_index(self, *_: Any) -> list[str]:
            return []

    entry_id = "continuity-entry-" + "3" * 24
    target = {
        "entry_id": entry_id,
        "path": "docs/status.md",
        "action": "create",
        "before_sha256": None,
        "after_sha256": HASH,
        "bytes": 7,
    }
    plan = {
        "plan_id": "1" * 24,
        "project_id": "universal-agent-os",
        "git_head": "b" * 40,
        "binding_sha256": HASH,
        "adapter_fingerprint_sha256": HASH,
        "core_manifest_sha256": HASH,
        "record_type_registry_sha256": HASH,
        "recovery_profile_sha256": HASH,
        "retention_policy_sha256": HASH,
        "bundle": {"manifest_sha256": HASH},
        "backup_id": "continuity-restore-backup-" + "2" * 24,
        "target_execution_order": [entry_id],
        "targets": [{**target, "backup_required": True}],
    }
    manifest = {"bundle_id": "continuity-export-" + "4" * 24, "inventory_sha256": HASH}
    backup_file = {"entry_id": entry_id, "present": False, "sha256": None}
    backup_index = {"files": [backup_file]}
    with tempfile.TemporaryDirectory(prefix="aos15-w6-rs4b-") as temporary:
        service = Probe(Path(temporary))
        backup_root = service.verified_restore_backup_root()
        backup_path = backup_root / plan["backup_id"]
        backup_path.mkdir(parents=True)
        (backup_path / "index.json").write_bytes(json_bytes(backup_index))
        receipt = service.build_restore_receipt(
            plan,
            manifest,
            backup_index,
            {"state": "FRESH"},
            {"topology_state": "complete", "authority_state": "available"},
        )
        validation = service.validate_restore_receipt(receipt)
    check(
        "field-id-hash-time-order-and-privacy-contracts-remain-exact",
        receipt["applied_at"] == "2026-08-05T00:00:00Z"
        and receipt["target_execution_order"] == plan["target_execution_order"]
        and receipt["targets"] == [target]
        and receipt["receipt_id"].startswith("continuity-restore-")
        and not any(
            value
            for key, value in receipt.items()
            if key.endswith(
                ("_stored", "_performed", "_created", "_overwritten", "_deleted")
            )
        ),
    )

    with patch.object(service, "build_restore_receipt", return_value={"patched": True}):
        patched = service.build_restore_receipt({}, {}, {}, {}, {})
    check(
        "instance-monkeypatch-contract-remains-compatible", patched == {"patched": True}
    )
    check("builder-output-is-accepted-by-receipt-validator", validation == [])
    check(
        "module-shard-facade-and-topology-ratchets-hold",
        len(source.splitlines()) <= 120
        and len(Path(__file__).read_text().splitlines()) <= 190
        and len(facade_source.splitlines()) < 440
        and len(topology_path.read_text().splitlines()) <= 112,
    )
    failed = [item for item in cases if not item["passed"]]
    payload = {"ok": not failed, "passed": 8 - len(failed), "total": 8, "cases": cases}
    print(json.dumps(payload, indent=2))
    raise SystemExit(2 if failed else 0)


if __name__ == "__main__":
    main()
