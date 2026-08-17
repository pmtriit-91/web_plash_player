"""Backup, apply, rollback, and recovery contracts for lifecycle updates."""
# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_os_paths import safe_join

# fmt: off
from lifecycle.shared import canonical_sha256, load_json, sha256_bytes, sha256_file, utc_now
from lifecycle.update_planning import MANIFEST_PATH, ROOT, collect_application_entries, plan_update
# fmt: on

UPDATE_RUNTIME_ROOT = ROOT / "_runtime" / "updates"
_core_verifier: Callable[[], dict[str, Any]] | None = None


def bind_core_verifier(callback: Callable[[], dict[str, Any]]) -> None:
    global _core_verifier
    _core_verifier = callback


def verify_core() -> dict[str, Any]:
    if _core_verifier is None:
        raise RuntimeError("lifecycle core verifier is not bound")
    return _core_verifier()


# fmt: off
def update_relative_path(root: Path, relative: str) -> Path:
    return safe_join(root, relative, canonical=True)


def remove_update_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def copy_update_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    remove_update_path(destination)
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise ValueError(f"source update entry is missing: {source}")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def backup_update_paths(transaction_root: Path, paths: list[str]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    payload_root = transaction_root / "backup"
    for relative in paths:
        current = update_relative_path(ROOT, relative)
        existed = current.is_file() or current.is_symlink()
        record: dict[str, Any] = {"path": relative, "existed": existed}
        if existed:
            record["type"] = "symlink" if current.is_symlink() else "file"
            backup = update_relative_path(payload_root, relative)
            copy_update_path(current, backup)
            if current.is_symlink():
                record["sha256"] = sha256_bytes(os.readlink(current).encode("utf-8"))
                record["target"] = os.readlink(current)
            else:
                record["sha256"] = sha256_file(current)
        index.append(record)
    atomic_json(transaction_root / "backup-index.json", {"entries": index})
    return index


def restore_update_backup(transaction_root: Path, index: list[dict[str, Any]]) -> None:
    payload_root = transaction_root / "backup"
    for record in reversed(index):
        relative = str(record["path"])
        current = update_relative_path(ROOT, relative)
        remove_update_path(current)
        if record.get("existed"):
            backup = update_relative_path(payload_root, relative)
            copy_update_path(backup, current)


def current_entry_digest(relative: str) -> dict[str, Any] | None:
    path = update_relative_path(ROOT, relative)
    if path.is_symlink():
        target = os.readlink(path)
        return {
            "type": "symlink",
            "sha256": sha256_bytes(target.encode("utf-8")),
            "target": target,
        }
    if path.is_file():
        return {"type": "file", "sha256": sha256_file(path)}
    return None


def apply_update(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm:
        return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"], "writes_performed": False}
    plan = plan_update(args)
    if not plan.get("ok") or not plan.get("ready_to_apply"):
        return {
            "ok": False,
            "reason_codes": ["UPDATE_PLAN_BLOCKED", *plan.get("reason_codes", [])],
            "plan": plan,
            "writes_performed": False,
        }
    if args.plan_id != plan.get("plan_id"):
        return {
            "ok": False,
            "reason_codes": ["UPDATE_PLAN_STALE"],
            "expected_plan_id": plan.get("plan_id"),
            "writes_performed": False,
        }

    source_root = Path(plan["source"]["root"])
    diff = plan["release_diff"]
    touched = sorted(
        set(diff["added"] + diff["modified"] + diff["removed"])
        | {"_manifest/base-release-manifest.json"}
    )
    transaction_id = sha256_bytes(os.urandom(32) + args.plan_id.encode("utf-8"))[:24]
    transaction_root = UPDATE_RUNTIME_ROOT / transaction_id
    try:
        transaction_root.mkdir(parents=True, exist_ok=False)
        backup_index = backup_update_paths(transaction_root, touched)
    except Exception as exc:
        return {
            "ok": False,
            "transaction_id": transaction_id,
            "reason_codes": ["UPDATE_BACKUP_FAILED"],
            "error": str(exc),
            "writes_performed": False,
        }
    protected_before = plan["protected_application"]["inventory_sha256"]
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "plan_id": args.plan_id,
        "status": "applying",
        "started_at": utc_now(),
        "source": {
            "root": str(source_root),
            "release_id": plan["source"].get("release_id"),
            "manifest_sha256": plan["plan_inputs"]["source_manifest_sha256"],
        },
        "target_before": plan["target"],
        "release_diff": diff,
        "protected_inventory_before": protected_before,
        "touched_paths": touched,
    }
    atomic_json(transaction_root / "receipt.json", receipt)

    operation_count = 0
    try:
        for relative in diff["removed"]:
            remove_update_path(update_relative_path(ROOT, relative))
            operation_count += 1
            if args.test_fail_after and os.environ.get("AGENT_OS_TEST_MODE") == "1" and operation_count >= args.test_fail_after:
                raise RuntimeError("injected update failure")
        for relative in diff["added"] + diff["modified"]:
            source_path = update_relative_path(source_root, relative)
            target_path = update_relative_path(ROOT, relative)
            copy_update_path(source_path, target_path)
            operation_count += 1
            if args.test_fail_after and os.environ.get("AGENT_OS_TEST_MODE") == "1" and operation_count >= args.test_fail_after:
                raise RuntimeError("injected update failure")

        copy_update_path(
            source_root / "_manifest" / "base-release-manifest.json",
            MANIFEST_PATH,
        )
        post_core = verify_core()
        application_after = collect_application_entries()
        protected_after = canonical_sha256(
            [application_after[path] for path in sorted(application_after)]
        )
        if not post_core.get("ok"):
            raise RuntimeError("post-apply Core verification failed")
        if protected_after != protected_before:
            raise RuntimeError("protected application inventory changed")

        expected_after = {
            relative: current_entry_digest(relative)
            for relative in touched
        }
        receipt.update(
            {
                "status": "applied",
                "completed_at": utc_now(),
                "protected_inventory_after": protected_after,
                "expected_after": expected_after,
                "post_verify_core": post_core,
            }
        )
        atomic_json(transaction_root / "receipt.json", receipt)
        return {
            "ok": True,
            "transaction_id": transaction_id,
            "plan_id": args.plan_id,
            "release_diff": diff,
            "protected_inventory_preserved": True,
            "post_verify_core": post_core,
            "writes_performed": True,
        }
    except Exception as exc:
        rollback_error: str | None = None
        try:
            restore_update_backup(transaction_root, backup_index)
        except Exception as restore_error:
            rollback_error = str(restore_error)
        rollback_core = verify_core()
        application_after = collect_application_entries()
        protected_after = canonical_sha256(
            [application_after[path] for path in sorted(application_after)]
        )
        receipt.update(
            {
                "status": "rollback_failed" if rollback_error else "rolled_back_after_failure",
                "completed_at": utc_now(),
                "error": str(exc),
                "rollback_error": rollback_error,
                "rollback_core": rollback_core,
                "protected_inventory_after": protected_after,
            }
        )
        atomic_json(transaction_root / "receipt.json", receipt)
        return {
            "ok": False,
            "transaction_id": transaction_id,
            "reason_codes": [
                "UPDATE_APPLY_FAILED",
                "UPDATE_ROLLBACK_FAILED" if rollback_error else "UPDATE_ROLLED_BACK",
            ],
            "error": str(exc),
            "rollback_error": rollback_error,
            "rollback_core_ok": rollback_core.get("ok") is True,
            "protected_inventory_preserved": protected_after == protected_before,
            "writes_performed": True,
        }


def rollback_update(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm:
        return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"], "writes_performed": False}
    if not re.fullmatch(r"[a-f0-9]{24}", args.transaction_id or ""):
        return {"ok": False, "reason_codes": ["TRANSACTION_ID_INVALID"], "writes_performed": False}
    transaction_root = UPDATE_RUNTIME_ROOT / args.transaction_id
    receipt = load_json(transaction_root / "receipt.json", None)
    backup = load_json(transaction_root / "backup-index.json", None)
    if not isinstance(receipt, dict) or not isinstance(backup, dict):
        return {"ok": False, "reason_codes": ["TRANSACTION_NOT_FOUND"], "writes_performed": False}
    if receipt.get("status") != "applied":
        return {"ok": False, "reason_codes": ["TRANSACTION_NOT_APPLIED"], "writes_performed": False}
    expected_after = receipt.get("expected_after")
    if not isinstance(expected_after, dict) or any(
        current_entry_digest(relative) != expected
        for relative, expected in expected_after.items()
    ):
        return {"ok": False, "reason_codes": ["ROLLBACK_TARGET_CHANGED"], "writes_performed": False}
    index = backup.get("entries")
    if not isinstance(index, list):
        return {"ok": False, "reason_codes": ["TRANSACTION_BACKUP_INVALID"], "writes_performed": False}

    try:
        restore_update_backup(transaction_root, index)
    except Exception as exc:
        receipt.update({"status": "rollback_failed", "rollback_error": str(exc), "rolled_back_at": utc_now()})
        atomic_json(transaction_root / "receipt.json", receipt)
        return {
            "ok": False,
            "reason_codes": ["ROLLBACK_APPLY_FAILED"],
            "error": str(exc),
            "writes_performed": True,
        }
    post_core = verify_core()
    application_after = collect_application_entries()
    protected_after = canonical_sha256(
        [application_after[path] for path in sorted(application_after)]
    )
    protected_ok = protected_after == receipt.get("protected_inventory_before")
    if not post_core.get("ok") or not protected_ok:
        return {
            "ok": False,
            "reason_codes": ["ROLLBACK_VERIFICATION_FAILED"],
            "post_verify_core": post_core,
            "protected_inventory_preserved": protected_ok,
            "writes_performed": True,
        }
    receipt.update({"status": "rolled_back", "rolled_back_at": utc_now()})
    atomic_json(transaction_root / "receipt.json", receipt)
    return {
        "ok": True,
        "transaction_id": args.transaction_id,
        "post_verify_core": post_core,
        "protected_inventory_preserved": True,
        "writes_performed": True,
    }
# fmt: on
