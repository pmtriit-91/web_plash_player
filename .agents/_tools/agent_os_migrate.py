#!/usr/bin/env python3
"""Transactional V8/V9-baseline migration into a verified Agent OS release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_os_lifecycle import manifest_entries, verify_release_tree
from agent_os_paths import portable_relative, safe_join


PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
PROTECTED = ("project", "skills/project-memory", "skills/project-local")
RUNTIME_PREFIXES = ("_runtime",)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        handle.write(json_bytes(value))
        temporary = Path(handle.name)
    temporary.replace(path)


def git(root: Path, *arguments: str) -> str | None:
    try:
        process = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return process.stdout.strip() if process.returncode == 0 else None


def is_prefix(relative: str, prefixes: tuple[str, ...]) -> bool:
    return any(relative == prefix or relative.startswith(prefix + "/") for prefix in prefixes)


def file_record(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        target = os.readlink(path)
        return {"path": relative, "type": "symlink", "target": target, "sha256": sha256_bytes(target.encode("utf-8"))}
    return {"path": relative, "type": "file", "sha256": sha256_bytes(path.read_bytes())}


def runtime_path(relative: str) -> bool:
    parts = relative.split("/")
    return (
        is_prefix(relative, RUNTIME_PREFIXES)
        or (relative.startswith("_telemetry/") and relative.endswith(".jsonl"))
        or "__pycache__" in parts
        or relative.endswith(".pyc")
        or relative.endswith("/.DS_Store")
        or relative == ".DS_Store"
    )


def inventory(root: Path, prefixes: tuple[str, ...] | None = None, excluded: tuple[str, ...] = (), skip_runtime: bool = False) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return records
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(root).as_posix()
        if prefixes is not None and not is_prefix(relative, prefixes):
            continue
        if excluded and is_prefix(relative, excluded):
            continue
        if skip_runtime and runtime_path(relative):
            continue
        records[relative] = file_record(path, root)
    return records


def inventory_hash(records: dict[str, dict[str, Any]]) -> str:
    return canonical_hash([records[key] for key in sorted(records)])


def detect_family(target: Path) -> dict[str, Any]:
    agent = target / ".agents"
    if not agent.is_dir():
        return {"family": "uninstalled", "version": None, "provenance": None}
    manifest = load_json(agent / "_manifest" / "base-release-manifest.json", {})
    if isinstance(manifest, dict) and manifest.get("agent_os_version"):
        version = str(manifest.get("agent_os_version"))
        provenance = manifest.get("provenance", {}).get("status") if isinstance(manifest.get("provenance"), dict) else None
        family = "v9-working-baseline" if version.startswith("9.") and provenance == "working-baseline" else "v9-verified" if version.startswith("9.") and provenance == "verified-release" else "manifest-release"
        return {"family": family, "version": version, "provenance": provenance, "release_id": manifest.get("release_id")}
    snapshots = [
        agent / "_manifest" / "private-release-snapshot.json",
        agent / "_manifest" / "legacy" / "v8-private-release-snapshot.json",
    ]
    for snapshot_path in snapshots:
        snapshot = load_json(snapshot_path, {})
        version = str(snapshot.get("version", "")) if isinstance(snapshot, dict) else ""
        if version.startswith("8."):
            return {"family": "v8-legacy", "version": version, "provenance": "legacy-snapshot", "marker": str(snapshot_path.relative_to(target))}
    return {"family": "unknown", "version": None, "provenance": None}


def inspect(target: Path) -> dict[str, Any]:
    root = target.expanduser().resolve()
    agent = root / ".agents"
    family = detect_family(root)
    protected = inventory(agent, prefixes=PROTECTED)
    bridge = root / "AGENTS.md"
    bridge_ok = bridge.is_file() and not bridge.is_symlink() and ".agents/AGENTS.md" in bridge.read_text(encoding="utf-8", errors="replace")
    dirty = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    dirty_lines = [line for line in (dirty or "").splitlines() if ".agents/_runtime/" not in line.replace("\\", "/")]
    return {
        "ok": family["family"] != "unknown",
        "target": str(root),
        **family,
        "git_head": git(root, "rev-parse", "HEAD"),
        "git_clean": not dirty_lines,
        "dirty_paths": dirty_lines,
        "root_bridge_compatible": bridge_ok,
        "protected_entries": len(protected),
        "protected_inventory_sha256": inventory_hash(protected),
        "writes_performed": False,
    }


def target_release_inventory(target: Path, family: str) -> dict[str, dict[str, Any]]:
    agent = target / ".agents"
    if family.startswith("v9") or family == "manifest-release":
        manifest = load_json(agent / "_manifest" / "base-release-manifest.json", {})
        entries, errors = manifest_entries(manifest if isinstance(manifest, dict) else {})
        if errors:
            raise ValueError("target manifest entries are invalid")
        return entries
    return inventory(agent, excluded=PROTECTED, skip_runtime=True)


def create_plan(source: Path, target: Path) -> dict[str, Any]:
    source_root = source.expanduser().resolve()
    target_root = target.expanduser().resolve()
    source_check = verify_release_tree(source_root)
    source_entries = source_check.pop("manifest_entries", {})
    target_check = inspect(target_root)
    blockers: list[str] = []
    if not source_check.get("ok") or not source_check.get("trusted_for_apply"):
        blockers.append("MIGRATION_SOURCE_NOT_VERIFIED")
    if target_check.get("family") not in {"v8-legacy", "v9-working-baseline"}:
        blockers.append("MIGRATION_TARGET_FAMILY_UNSUPPORTED")
    if not target_check.get("git_head"):
        blockers.append("MIGRATION_TARGET_GIT_REQUIRED")
    if not target_check.get("git_clean"):
        blockers.append("MIGRATION_TARGET_DIRTY")
    if not target_check.get("root_bridge_compatible"):
        blockers.append("MIGRATION_ROOT_BRIDGE_MANUAL_MERGE_REQUIRED")
    try:
        current_entries = target_release_inventory(target_root, str(target_check.get("family")))
    except ValueError:
        current_entries = {}
        blockers.append("MIGRATION_TARGET_MANIFEST_INVALID")
    source_manifest = source_root / "_manifest" / "base-release-manifest.json"
    mutable_paths = sorted(set(current_entries) | set(source_entries) | {"_manifest/base-release-manifest.json"})
    current_bytes = inventory(target_root / ".agents", skip_runtime=True)
    inputs = {
        "source_manifest_sha256": sha256_bytes(source_manifest.read_bytes()) if source_manifest.is_file() else None,
        "target_git_head": target_check.get("git_head"),
        "target_family": target_check.get("family"),
        "target_release_inventory_sha256": inventory_hash({path: current_bytes[path] for path in mutable_paths if path in current_bytes}),
        "protected_inventory_sha256": target_check.get("protected_inventory_sha256"),
        "mutable_paths": mutable_paths,
    }
    created = now()
    plan = {
        "schema_version": 1,
        "plan_id": "",
        "status": "pending-approval",
        "operation": "migrate-agent-os",
        "created_at": iso(created),
        "expires_at": iso(created + timedelta(minutes=20)),
        "source": str(source_root),
        "target": str(target_root),
        "source_release_id": source_check.get("release_id"),
        "source_version": source_check.get("agent_os_version"),
        "target_family": target_check.get("family"),
        "inputs": inputs,
        "release_diff": {
            "added": sorted(set(source_entries) - set(current_entries)),
            "modified": sorted(path for path in set(source_entries) & set(current_entries) if source_entries[path] != current_entries[path]),
            "removed": sorted(set(current_entries) - set(source_entries)),
        },
        "protected_application": {
            "entries": target_check.get("protected_entries"),
            "inventory_sha256": target_check.get("protected_inventory_sha256"),
        },
        "reason_codes": blockers,
        "ready_to_apply": not blockers,
        "writes_performed": False,
    }
    plan["plan_id"] = canonical_hash({key: value for key, value in plan.items() if key not in {"plan_id", "content_sha256"}})[:24]
    plan["content_sha256"] = canonical_hash({key: value for key, value in plan.items() if key != "content_sha256"})
    runtime = target_root / ".agents" / "_runtime" / "migrations" / "plans"
    atomic_json(runtime / f"{plan['plan_id']}.json", plan)
    return {"ok": True, "plan": plan}


def copy_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() or destination.is_symlink():
        destination.unlink()
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise ValueError(f"source file missing: {source}")


def backup_paths(agent: Path, transaction: Path, paths: list[str]) -> list[dict[str, Any]]:
    backup_root = transaction / "backup"
    index: list[dict[str, Any]] = []
    for relative in paths:
        current = safe_join(agent, relative, canonical=True)
        existed = current.is_file() or current.is_symlink()
        record: dict[str, Any] = {"path": relative, "existed": existed}
        if existed:
            copy_path(current, safe_join(backup_root, relative, canonical=True))
            record.update(file_record(current, agent))
        index.append(record)
    atomic_json(transaction / "backup-index.json", index)
    return index


def restore(agent: Path, transaction: Path, index: list[dict[str, Any]]) -> None:
    for record in reversed(index):
        relative = portable_relative(str(record["path"]), canonical=True)
        current = safe_join(agent, relative, canonical=True)
        if current.is_file() or current.is_symlink():
            current.unlink()
        if record.get("existed"):
            copy_path(safe_join(transaction / "backup", relative, canonical=True), current)


def apply(target: Path, plan_id: str, confirm: bool) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"], "writes_performed": False}
    if not PLAN_ID.fullmatch(plan_id):
        return {"ok": False, "reason_codes": ["MIGRATION_PLAN_ID_INVALID"], "writes_performed": False}
    target_root = target.expanduser().resolve()
    agent = target_root / ".agents"
    runtime = agent / "_runtime" / "migrations"
    plan_path = runtime / "plans" / f"{plan_id}.json"
    plan = load_json(plan_path, {})
    valid_hash = isinstance(plan, dict) and plan.get("content_sha256") == canonical_hash({key: value for key, value in plan.items() if key != "content_sha256"})
    if not valid_hash or plan.get("plan_id") != plan_id or plan.get("target") != str(target_root):
        return {"ok": False, "reason_codes": ["MIGRATION_PLAN_INVALID_OR_TAMPERED"], "writes_performed": False}
    try:
        expires = datetime.fromisoformat(str(plan["expires_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        expires = datetime.fromtimestamp(0, timezone.utc)
    if now() > expires or not plan.get("ready_to_apply"):
        return {"ok": False, "reason_codes": ["MIGRATION_PLAN_EXPIRED_OR_BLOCKED"], "writes_performed": False}
    source = Path(plan["source"]).resolve()
    source_manifest = source / "_manifest" / "base-release-manifest.json"
    current = inspect(target_root)
    inputs = plan["inputs"]
    current_entries = target_release_inventory(target_root, str(plan["target_family"]))
    agent_inventory = inventory(agent, skip_runtime=True)
    current_mutable_hash = inventory_hash({path: agent_inventory[path] for path in inputs["mutable_paths"] if path in agent_inventory})
    guards = {
        "head": current.get("git_head") == inputs.get("target_git_head"),
        "family": current.get("family") == plan.get("target_family"),
        "clean": current.get("git_clean") is True,
        "source": source_manifest.is_file() and sha256_bytes(source_manifest.read_bytes()) == inputs.get("source_manifest_sha256"),
        "protected": current.get("protected_inventory_sha256") == inputs.get("protected_inventory_sha256"),
        "mutable": current_mutable_hash == inputs.get("target_release_inventory_sha256"),
    }
    if not all(guards.values()):
        return {"ok": False, "reason_codes": ["MIGRATION_PLAN_STALE"], "guards": guards, "writes_performed": False}
    source_check = verify_release_tree(source)
    source_entries = source_check.pop("manifest_entries", {})
    if not source_check.get("ok") or not source_check.get("trusted_for_apply"):
        return {"ok": False, "reason_codes": ["MIGRATION_SOURCE_NOT_VERIFIED"], "writes_performed": False}
    transaction_id = canonical_hash({"plan": plan_id, "started": iso(now())})[:24]
    transaction = runtime / "transactions" / transaction_id
    transaction.mkdir(parents=True, exist_ok=False)
    paths = list(inputs["mutable_paths"])
    index = backup_paths(agent, transaction, paths)
    receipt = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "plan_id": plan_id,
        "status": "applying",
        "target_family": plan.get("target_family"),
        "source_release_id": plan.get("source_release_id"),
        "protected_inventory_before": inputs.get("protected_inventory_sha256"),
        "started_at": iso(now()),
    }
    atomic_json(transaction / "receipt.json", receipt)
    try:
        for relative in sorted(set(current_entries) - set(source_entries), reverse=True):
            destination = safe_join(agent, relative, canonical=True)
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
        for relative in sorted(source_entries):
            copy_path(safe_join(source, relative, canonical=True), safe_join(agent, relative, canonical=True))
        copy_path(source_manifest, agent / "_manifest" / "base-release-manifest.json")
        verification = verify_release_tree(agent)
        protected_after = inventory_hash(inventory(agent, prefixes=PROTECTED))
        if not verification.get("ok") or protected_after != inputs.get("protected_inventory_sha256"):
            raise RuntimeError("post-migration integrity or protected inventory check failed")
    except Exception as exc:
        restore(agent, transaction, index)
        receipt.update({"status": "rolled-back-after-failure", "error": str(exc), "finished_at": iso(now())})
        atomic_json(transaction / "receipt.json", receipt)
        return {"ok": False, "reason_codes": ["MIGRATION_ROLLED_BACK"], "error": str(exc), "transaction_id": transaction_id, "writes_performed": True}
    receipt.update({"status": "applied", "finished_at": iso(now()), "protected_inventory_after": protected_after})
    receipt["content_sha256"] = canonical_hash(receipt)
    atomic_json(transaction / "receipt.json", receipt)
    return {"ok": True, "transaction_id": transaction_id, "receipt": receipt, "verification": verification, "writes_performed": True}


def rollback(target: Path, transaction_id: str, confirm: bool) -> dict[str, Any]:
    if not confirm:
        return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"], "writes_performed": False}
    target_root = target.expanduser().resolve()
    agent = target_root / ".agents"
    transaction = agent / "_runtime" / "migrations" / "transactions" / transaction_id
    index = load_json(transaction / "backup-index.json", None)
    receipt = load_json(transaction / "receipt.json", {})
    if not isinstance(index, list) or receipt.get("transaction_id") != transaction_id or receipt.get("status") != "applied":
        return {"ok": False, "reason_codes": ["MIGRATION_TRANSACTION_NOT_ROLLBACKABLE"], "writes_performed": False}
    restore(agent, transaction, index)
    receipt.update({"status": "rolled-back", "rolled_back_at": iso(now())})
    receipt.pop("content_sha256", None)
    receipt["content_sha256"] = canonical_hash(receipt)
    atomic_json(transaction / "receipt.json", receipt)
    return {"ok": True, "transaction_id": transaction_id, "writes_performed": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS migration transaction")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--target", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--source", required=True)
    plan_parser.add_argument("--target", required=True)
    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("--target", required=True)
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--confirm", action="store_true")
    rollback_parser = commands.add_parser("rollback")
    rollback_parser.add_argument("--target", required=True)
    rollback_parser.add_argument("--transaction", required=True)
    rollback_parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect(Path(args.target))
        elif args.command == "plan":
            result = create_plan(Path(args.source), Path(args.target))
        elif args.command == "apply":
            result = apply(Path(args.target), args.plan, args.confirm)
        else:
            result = rollback(Path(args.target), args.transaction, args.confirm)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"ok": False, "reason_codes": ["MIGRATION_INPUT_OR_IO_INVALID"], "error": str(exc), "writes_performed": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
