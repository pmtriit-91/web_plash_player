#!/usr/bin/env python3
"""Two-phase local transactions for Control Center mutations."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from agent_os_domain import load_json, validate_project_settings

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PLAN_ID = __import__("re").compile(r"^[0-9a-f]{24}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


class TransactionService:
    def __init__(self, agent_root: Path = DEFAULT_ROOT, now: Callable[[], datetime] = utc_now):
        self.root = agent_root.resolve()
        self.project_root = self.root.parent
        self.runtime = self.root / "_runtime" / "control-center"
        self.plans = self.runtime / "plans"
        self.receipts = self.runtime / "receipts"
        self.target = self.root / "project" / "skill-config.json"
        self.now = now

    def git(self, *arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def protected_digest(self) -> str:
        records: list[dict[str, Any]] = []
        scopes = [self.root / "project", self.root / "skills" / "project-memory", self.root / "skills" / "project-local"]
        for scope in scopes:
            if not scope.exists():
                continue
            for path in sorted(scope.rglob("*"), key=lambda item: item.as_posix()):
                if path == self.target or path.is_dir():
                    continue
                relative = path.relative_to(self.root).as_posix()
                if path.is_symlink():
                    records.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
                elif path.is_file():
                    records.append({"path": relative, "type": "file", "sha256": sha256_bytes(path.read_bytes())})
        return canonical_hash(records)

    def project_id(self) -> str:
        binding = load_json(self.root / "project" / "project-binding.json", {})
        if isinstance(binding, dict) and binding.get("project_id"):
            return str(binding["project_id"])
        current = load_json(self.target, {})
        return str(current.get("project_id", ""))

    def plan_settings(self, desired: Any, expiry_seconds: int | None = None) -> dict[str, Any]:
        head = self.git("rev-parse", "HEAD")
        if not head:
            return {"ok": False, "reason_codes": ["GIT_HEAD_UNAVAILABLE"]}
        dirty = self.git("status", "--porcelain")
        if dirty:
            return {"ok": False, "reason_codes": ["DIRTY_GIT"], "dirty": dirty.splitlines()}
        current = load_json(self.target, None)
        errors = validate_project_settings(desired, self.project_id())
        if errors:
            return {"ok": False, "reason_codes": ["SETTINGS_VALIDATION_FAILED"], "errors": errors}
        before_bytes = self.target.read_bytes() if self.target.is_file() else b""
        after_text = json.dumps(desired, ensure_ascii=False, indent=2) + "\n"
        after_bytes = after_text.encode("utf-8")
        if before_bytes == after_bytes:
            return {"ok": False, "reason_codes": ["NO_CHANGES"]}
        now = self.now()
        configured = int(desired.get("budgets", {}).get("plan_expiry_seconds", 900))
        lifetime = expiry_seconds if expiry_seconds is not None else configured
        if not 60 <= lifetime <= 3600:
            return {"ok": False, "reason_codes": ["PLAN_EXPIRY_INVALID"]}
        plan_input = {
            "operation": "project-settings-update",
            "git_head": head,
            "target": "project/skill-config.json",
            "before_sha256": sha256_bytes(before_bytes),
            "after_sha256": sha256_bytes(after_bytes),
            "desired": desired,
            "protected_digest": self.protected_digest(),
            "created_at": iso_time(now),
            "expires_at": iso_time(now + timedelta(seconds=lifetime)),
        }
        plan_id = canonical_hash(plan_input)[:24]
        diff = "".join(
            difflib.unified_diff(
                before_bytes.decode("utf-8", errors="replace").splitlines(keepends=True),
                after_text.splitlines(keepends=True),
                fromfile="a/.agents/project/skill-config.json",
                tofile="b/.agents/project/skill-config.json",
            )
        )
        plan = {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "pending-approval",
            "risk": "application-owned-settings",
            "requires": ["explicit-apply-confirmation"],
            "input": plan_input,
            "before": current,
            "exact_diff": diff,
        }
        atomic_json(self.plans / f"{plan_id}.json", plan)
        return {"ok": True, "plan": plan}

    def acquire_lock(self) -> int | None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        try:
            return os.open(self.runtime / "apply.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None

    def release_lock(self, descriptor: int) -> None:
        os.close(descriptor)
        try:
            (self.runtime / "apply.lock").unlink()
        except FileNotFoundError:
            pass

    def apply_settings(self, plan_id: str, confirm: bool, test_fail_after_write: bool = False) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        if not PLAN_ID.fullmatch(plan_id or ""):
            return {"ok": False, "reason_codes": ["PLAN_ID_INVALID"]}
        descriptor = self.acquire_lock()
        if descriptor is None:
            return {"ok": False, "reason_codes": ["TRANSACTION_BUSY"]}
        try:
            plan_path = self.plans / f"{plan_id}.json"
            plan = load_json(plan_path, None)
            if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
                return {"ok": False, "reason_codes": ["PLAN_NOT_FOUND"]}
            if plan.get("status") != "pending-approval":
                return {"ok": False, "reason_codes": ["PLAN_NOT_PENDING"], "status": plan.get("status")}
            inputs = plan.get("input", {})
            if canonical_hash(inputs)[:24] != plan_id:
                return {"ok": False, "reason_codes": ["PLAN_INTEGRITY_FAILED"]}
            if self.now() > parse_time(str(inputs.get("expires_at"))):
                return {"ok": False, "reason_codes": ["PLAN_EXPIRED"]}
            current_head = self.git("rev-parse", "HEAD")
            if current_head != inputs.get("git_head"):
                return {"ok": False, "reason_codes": ["STALE_GIT_HEAD"], "expected": inputs.get("git_head"), "actual": current_head}
            before_bytes = self.target.read_bytes() if self.target.is_file() else b""
            if sha256_bytes(before_bytes) != inputs.get("before_sha256"):
                return {"ok": False, "reason_codes": ["STALE_TARGET_HASH"]}
            if self.protected_digest() != inputs.get("protected_digest"):
                return {"ok": False, "reason_codes": ["PROTECTED_SCOPE_CHANGED"]}
            desired = inputs.get("desired")
            errors = validate_project_settings(desired, self.project_id())
            if errors:
                return {"ok": False, "reason_codes": ["SETTINGS_VALIDATION_FAILED"], "errors": errors}
            after_bytes = (json.dumps(desired, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if sha256_bytes(after_bytes) != inputs.get("after_sha256"):
                return {"ok": False, "reason_codes": ["PLAN_CONTENT_HASH_INVALID"]}
            expected_diff = "".join(
                difflib.unified_diff(
                    before_bytes.decode("utf-8", errors="replace").splitlines(keepends=True),
                    after_bytes.decode("utf-8").splitlines(keepends=True),
                    fromfile="a/.agents/project/skill-config.json",
                    tofile="b/.agents/project/skill-config.json",
                )
            )
            if plan.get("exact_diff") != expected_diff:
                return {"ok": False, "reason_codes": ["PLAN_DISPLAY_DIFF_INVALID"]}

            receipt = {
                "schema_version": 1,
                "transaction_id": canonical_hash({"plan_id": plan_id, "applied_at": iso_time(self.now()), "nonce": os.urandom(16).hex()})[:24],
                "plan_id": plan_id,
                "operation": "project-settings-update",
                "status": "applying",
                "git_head": current_head,
                "before_sha256": inputs.get("before_sha256"),
                "after_sha256": inputs.get("after_sha256"),
                "protected_digest": inputs.get("protected_digest"),
                "applied_at": iso_time(self.now()),
                "commit_created": False,
                "push_performed": False,
            }
            try:
                self.target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="wb", dir=self.target.parent, prefix=f".{self.target.name}.", suffix=".tmp", delete=False) as handle:
                    handle.write(after_bytes)
                    temporary = Path(handle.name)
                temporary.replace(self.target)
                if test_fail_after_write and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                    raise RuntimeError("injected post-write failure")
                if sha256_bytes(self.target.read_bytes()) != inputs.get("after_sha256") or self.protected_digest() != inputs.get("protected_digest"):
                    raise RuntimeError("post-apply verification failed")
                receipt["status"] = "applied"
                receipt["verification"] = "passed"
                receipt["content_sha256"] = canonical_hash(receipt)
                plan["status"] = "applied"
                plan["transaction_id"] = receipt["transaction_id"]
                atomic_json(self.receipts / f"{receipt['transaction_id']}.json", receipt)
                atomic_json(plan_path, plan)
                return {"ok": True, "receipt": receipt}
            except Exception as exc:
                with tempfile.NamedTemporaryFile(mode="wb", dir=self.target.parent, prefix=f".{self.target.name}.", suffix=".rollback.tmp", delete=False) as handle:
                    handle.write(before_bytes)
                    rollback = Path(handle.name)
                rollback.replace(self.target)
                receipt["status"] = "rolled-back"
                receipt["verification"] = "failed"
                receipt["error"] = str(exc)
                receipt["rollback_verified"] = sha256_bytes(self.target.read_bytes()) == inputs.get("before_sha256")
                receipt["content_sha256"] = canonical_hash(receipt)
                plan["status"] = "failed"
                plan["transaction_id"] = receipt["transaction_id"]
                atomic_json(self.receipts / f"{receipt['transaction_id']}.json", receipt)
                atomic_json(plan_path, plan)
                return {"ok": False, "reason_codes": ["APPLY_FAILED_ROLLED_BACK"], "receipt": receipt}
        finally:
            self.release_lock(descriptor)

    def queue(self) -> dict[str, Any]:
        plans = [load_json(path, {}) for path in sorted(self.plans.glob("*.json"))] if self.plans.is_dir() else []
        receipts = [load_json(path, {}) for path in sorted(self.receipts.glob("*.json"))] if self.receipts.is_dir() else []
        return {"ok": True, "plans": plans, "receipts": receipts}


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent OS two-phase transaction engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("queue")
    plan = sub.add_parser("plan-settings")
    plan.add_argument("--input", required=True)
    apply = sub.add_parser("apply-settings")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    service = TransactionService()
    if args.command == "queue":
        result = service.queue()
    elif args.command == "plan-settings":
        result = service.plan_settings(load_json(Path(args.input).expanduser().resolve(), None))
    elif args.command == "apply-settings":
        result = service.apply_settings(args.plan, args.confirm)
    else:
        result = {"ok": False, "reason_codes": ["COMMAND_NOT_IMPLEMENTED"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
