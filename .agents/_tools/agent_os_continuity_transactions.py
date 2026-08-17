#!/usr/bin/env python3
"""Transactional AOS-15 continuity catalog initialization, migration, and recovery."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_context_memory import sha256_bytes
from agent_os_continuity import (
    MAX_JSON_BYTES,  # noqa: F401 - public facade re-export
    load_json,
)
from agent_os_paths import safe_join
from continuity_transactions.apply_engine import ApplyEngineMixin
from continuity_transactions.catalog_initialization import CatalogInitializationMixin
from continuity_transactions.catalog_inventory import CatalogInventoryMixin
from continuity_transactions.contracts import (
    BACKUP_DIR_REL,  # noqa: F401 - public facade re-export
    BACKUP_FILE_FIELDS,  # noqa: F401 - public facade re-export
    BACKUP_ID,  # noqa: F401 - public facade re-export
    BACKUP_INDEX_FIELDS,  # noqa: F401 - public facade re-export
    BACKUP_REFERENCE_FIELDS,  # noqa: F401 - public facade re-export
    BINDING_REL,
    CATALOG_REL,  # noqa: F401 - public facade re-export
    CHANGE_FIELDS,  # noqa: F401 - public facade re-export
    CORE_MANIFEST_REL,
    DEFAULT_ROOT,
    DEFAULT_SOURCE_PATHS,  # noqa: F401 - public facade re-export
    FINGERPRINT_REL,
    FULL_COMMIT,
    INVENTORY_FIELDS,  # noqa: F401 - public facade re-export
    MAX_PLAN_SECONDS,  # noqa: F401 - public facade re-export
    MIGRATION_FIELDS,  # noqa: F401 - public facade re-export
    MIGRATION_REGISTRY_FIELDS,  # noqa: F401 - public facade re-export
    MIGRATION_REGISTRY_REL,
    OPERATIONS,  # noqa: F401 - public facade re-export
    PLAN_FIELDS,  # noqa: F401 - public facade re-export
    PLAN_ID,  # noqa: F401 - public facade re-export
    PLAN_METADATA_OPTIONAL,  # noqa: F401 - public facade re-export
    PLAN_METADATA_REQUIRED,  # noqa: F401 - public facade re-export
    PROFILE_REL,
    PROJECTION_REL,  # noqa: F401 - public facade re-export
    REGISTRY_REL,
    SEMANTIC_FIELDS,  # noqa: F401 - public facade re-export
    SHA256,  # noqa: F401 - public facade re-export
    TARGETS,  # noqa: F401 - public facade re-export
    TRANSACTION_DIR_REL,  # noqa: F401 - public facade re-export
    TRANSACTION_ID,  # noqa: F401 - public facade re-export
    TRANSACTION_RECEIPT_FIELDS,  # noqa: F401 - public facade re-export
    strict_document,  # noqa: F401 - public facade re-export
)
from continuity_transactions.plan_validation import PlanValidationMixin
from continuity_transactions.receipt_validation import ReceiptValidationMixin
from continuity_transactions.recovery_planning import RecoveryPlanningMixin
from continuity_transactions.transition_planning import TransitionPlanningMixin


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


# fmt: off
class ContinuityTransactionService(
    ApplyEngineMixin,
    RecoveryPlanningMixin,
    TransitionPlanningMixin,
    CatalogInitializationMixin,
    CatalogInventoryMixin,
    ReceiptValidationMixin,
    PlanValidationMixin,
):
    def __init__(
        self,
        agent_root: Path = DEFAULT_ROOT,
        now: Callable[[], datetime] = now_utc,
    ):
        self.root = agent_root.resolve()
        self.project_root = self.root.parent
        self.runtime = self.root / "_runtime" / "continuity"
        self.plans = self.runtime / "plans"
        self.lock_path = self.runtime / "apply.lock"
        self.now = now

    def path(self, relative: str) -> Path:
        return safe_join(self.root, relative)

    def project_path(self, relative: str) -> Path:
        return safe_join(self.project_root, relative)

    def target_bytes(self, relative: str) -> bytes | None:
        return read_bytes(self.path(relative))

    def git(self, *arguments: str, text: bool = False) -> subprocess.CompletedProcess[Any] | None:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=self.project_root,
                capture_output=True,
                text=text,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def head(self) -> str | None:
        result = self.git("rev-parse", "HEAD", text=True)
        value = result.stdout.strip() if result is not None and result.returncode == 0 else ""
        return value if FULL_COMMIT.fullmatch(value) else None

    def git_blob(self, commit: str, relative: str) -> bytes | None:
        result = self.git("cat-file", "blob", f"{commit}:{relative}")
        return result.stdout if result is not None and result.returncode == 0 else None

    def git_path_clean(self, relative: str) -> bool:
        for arguments in (
            ("diff", "--quiet", "--no-ext-diff", "--", relative),
            ("diff", "--cached", "--quiet", "--no-ext-diff", "--", relative),
        ):
            result = self.git(*arguments)
            if result is None or result.returncode != 0:
                return False
        return True

    def contract_hashes(self) -> dict[str, str] | None:
        paths = {
            "binding_sha256": BINDING_REL,
            "adapter_fingerprint_sha256": FINGERPRINT_REL,
            "core_manifest_sha256": CORE_MANIFEST_REL,
            "record_type_registry_sha256": REGISTRY_REL,
            "recovery_profile_sha256": PROFILE_REL,
            "migration_registry_sha256": MIGRATION_REGISTRY_REL,
        }
        result: dict[str, str] = {}
        for field, relative in paths.items():
            content = self.target_bytes(relative)
            if content is None:
                return None
            result[field] = sha256_bytes(content)
        return result

    def binding(self) -> dict[str, Any]:
        try:
            document = load_json(self.path(BINDING_REL))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {}
        return document if isinstance(document, dict) else {}

def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS continuity transaction engine")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan-initialize")
    commands.add_parser("plan-refresh")
    commands.add_parser("plan-migrate")
    repair = commands.add_parser("plan-repair")
    repair.add_argument("--backup")
    rollback = commands.add_parser("plan-rollback")
    rollback.add_argument("--transaction", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm", action="store_true")
    commands.add_parser("transactions")
    args = parser.parse_args()
    service = ContinuityTransactionService()
    if args.command == "plan-initialize":
        result = service.plan_initialize()
    elif args.command == "plan-refresh":
        result = service.plan_refresh()
    elif args.command == "plan-migrate":
        result = service.plan_migrate()
    elif args.command == "plan-repair":
        result = service.plan_repair(args.backup)
    elif args.command == "plan-rollback":
        result = service.plan_rollback(args.transaction)
    elif args.command == "apply":
        result = service.apply(args.plan, args.confirm)
    else:
        result = service.list_transactions()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
