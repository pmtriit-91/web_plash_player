#!/usr/bin/env python3
"""Two-phase Project Genesis migration, confirmation, and projection transactions."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from agent_os_genesis import (
    BINDING_REF,
    MAX_PROJECTION_BYTES,
    REQUIRED_SLOTS,
    TRUTH_SLOTS,
    SAFE_ID,
    SHA256,
    canonical_hash,
    canonical_json,
    claim_basis_hash,
    confirmation_ref,
    content_hash,
    document_errors,
    doctor,
    evidence_health,
    graph_result,
    has_symlink_component,
    load_json,
    meaningful_value,
    projected_truth,
    sha256_file,
    sha256_project_file,
    uncertainty_is_non_blocking,
    valid_datetime,
)


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
PLAN_ID = __import__("re").compile(r"^[a-f0-9]{24}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return __import__("hashlib").sha256(value).hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def exact_diff(before: bytes | None, after: bytes, relative: str) -> str:
    return "".join(
        difflib.unified_diff(
            (before or b"").decode("utf-8", errors="replace").splitlines(keepends=True),
            after.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/.agents/{relative}",
            tofile=f"b/.agents/{relative}",
        )
    )


def normalized_binding_sections(binding: dict[str, Any]) -> dict[str, Any]:
    repository = binding.get("repository", {}) if isinstance(binding.get("repository"), dict) else {}
    workspaces = binding.get("workspaces", []) if isinstance(binding.get("workspaces"), list) else []
    commands = binding.get("commands", []) if isinstance(binding.get("commands"), list) else []
    entrypoints = binding.get("context_entrypoints", []) if isinstance(binding.get("context_entrypoints"), list) else []
    normalized_workspaces = []
    for workspace in workspaces:
        if not isinstance(workspace, dict):
            normalized_workspaces.append(workspace)
            continue
        normalized_workspaces.append(
            {
                "id": workspace.get("id"),
                "path": workspace.get("path"),
                "root_markers": sorted(workspace.get("root_markers", []), key=str),
            }
        )
    normalized_workspaces.sort(key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "")
    normalized_commands = sorted(
        commands,
        key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "",
    )
    return {
        "project_identity": {
            "project_id": binding.get("project_id"),
            "repository": {
                "kind": repository.get("kind"),
                "root_markers": sorted(repository.get("root_markers", []), key=str),
                "remote_aliases": sorted(repository.get("remote_aliases", []), key=str),
            },
            "workspaces": normalized_workspaces,
        },
        "commands": normalized_commands,
        "context_entrypoints": sorted(entrypoints, key=str),
    }


def expected_binding_digests(binding: dict[str, Any]) -> dict[str, str]:
    return {
        name: canonical_hash(value)
        for name, value in normalized_binding_sections(binding).items()
    }


class GenesisService:
    """Application-owned Genesis writes with stale-plan and rollback guards."""

    def __init__(self, root: Path = DEFAULT_ROOT, now: Callable[[], datetime] = utc_now):
        self.root = root.resolve()
        self.project_root = self.root.parent
        self.project = self.root / "project"
        self.genesis = self.project / "genesis.json"
        self.projection = self.project / "genesis-projection.json"
        self.binding_path = self.project / "project-binding.json"
        self.fingerprint_path = self.project / "adapter-fingerprint.json"
        self.confirmations = self.project / "genesis-confirmations"
        self.template = self.root / "project-template" / "genesis.json"
        self.runtime = self.root / "_runtime" / "genesis"
        self.plans = self.runtime / "plans"
        self.transactions = self.runtime / "transactions"
        self.lock_path = self.runtime / "apply.lock"
        self.now = now

    def git_head(self) -> str | None:
        try:
            process = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = process.stdout.strip()
        return value if process.returncode == 0 and len(value) == 40 else None

    def binding(self) -> tuple[dict[str, Any] | None, str | None, str | None]:
        try:
            if (
                not self.binding_path.is_file()
                or has_symlink_component(self.project_root, self.binding_path)
                or not self.fingerprint_path.is_file()
                or has_symlink_component(self.project_root, self.fingerprint_path)
            ):
                return None, None, None
            value = load_json(self.binding_path)
            fingerprint = load_json(self.fingerprint_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, None, None
        project_id = value.get("project_id") if isinstance(value, dict) else None
        repository = value.get("repository") if isinstance(value, dict) else None
        markers = repository.get("root_markers") if isinstance(repository, dict) else None
        allowed_binding = {
            "schema_version", "project_id", "repository", "workspaces", "commands",
            "context_entrypoints", "created_at", "last_verified_at",
            "last_verified_commit",
        }
        binding_valid = (
            isinstance(value, dict)
            and not (set(value) - allowed_binding)
            and value.get("schema_version") == 1
            and isinstance(project_id, str)
            and SAFE_ID.fullmatch(project_id) is not None
            and isinstance(repository, dict)
            and not (set(repository) - {"kind", "root_markers", "remote_aliases"})
            and repository.get("kind") in {"git", "directory"}
            and isinstance(markers, list)
            and bool(markers)
            and len(markers) == len(set(markers))
            and isinstance(value.get("commands"), list)
            and isinstance(value.get("workspaces", []), list)
            and isinstance(value.get("context_entrypoints", []), list)
            and valid_datetime(value.get("created_at"))
            and valid_datetime(value.get("last_verified_at"))
        )
        if not binding_valid:
            return None, None, None
        for marker in markers:
            marker_path = self.project_root.joinpath(*Path(str(marker)).parts)
            if (
                not isinstance(marker, str)
                or not marker
                or marker.startswith(("/", "\\"))
                or ".." in Path(marker).parts
                or has_symlink_component(self.project_root, marker_path)
                or not marker_path.exists()
            ):
                return None, None, None
        fingerprint_valid = (
            isinstance(fingerprint, dict)
            and fingerprint.get("schema_version") == 1
            and fingerprint.get("project_id") == project_id
            and fingerprint.get("binding_schema_version") == 1
            and fingerprint.get("algorithm") == "sha256"
            and fingerprint.get("digests") == expected_binding_digests(value)
            and fingerprint.get("verified_at") == value.get("last_verified_at")
            and fingerprint.get("verified_commit") == value.get("last_verified_commit")
        )
        if not fingerprint_valid:
            return None, None, None
        return (
            value,
            sha256_project_file(self.project_root, self.binding_path),
            sha256_project_file(self.project_root, self.fingerprint_path),
        )

    def source_guard(self) -> dict[str, Any]:
        if not self.genesis.is_file():
            return {"source_sha256": None, "source_revision": None}
        source_sha = sha256_project_file(self.project_root, self.genesis)
        try:
            source = load_json(self.genesis)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            source = {}
        revision = source.get("revision") if isinstance(source, dict) else None
        return {
            "source_sha256": source_sha,
            "source_revision": revision if isinstance(revision, int) and not isinstance(revision, bool) else None,
        }

    def template_health(self) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            template = load_json(self.template)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return None, [str(exc)]
        errors = document_errors(template)
        if (
            isinstance(template, dict)
            and (
                template.get("project_id") != "unbound-consumer"
                or template.get("document_id") != "genesis-unbound-consumer"
                or any(template.get("claims", {}).get(slot) for slot in REQUIRED_SLOTS)
            )
        ):
            errors.append("Genesis template is not the empty unbound placeholder")
        return template if not errors else None, errors

    def acquire_lock(self) -> int | None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        try:
            return os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None

    def release_lock(self, descriptor: int) -> None:
        os.close(descriptor)
        self.lock_path.unlink(missing_ok=True)

    def save_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        plan["plan_id"] = canonical_hash(
            {key: value for key, value in plan.items() if key not in {"plan_id", "content_sha256"}}
        )[:24]
        plan["content_sha256"] = content_hash(plan)
        atomic_bytes(self.plans / f"{plan['plan_id']}.json", json_bytes(plan))
        return {"ok": True, "plan": plan}

    def load_plan(self, plan_id: str, operation: str) -> tuple[dict[str, Any] | None, list[str]]:
        if PLAN_ID.fullmatch(plan_id or "") is None:
            return None, ["GENESIS_PLAN_INVALID"]
        try:
            plan = load_json(self.plans / f"{plan_id}.json")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, ["GENESIS_PLAN_NOT_FOUND_OR_TAMPERED"]
        if (
            not isinstance(plan, dict)
            or plan.get("plan_id") != plan_id
            or plan.get("operation") != operation
            or plan.get("content_sha256") != content_hash(plan)
            or canonical_hash(
                {
                    key: value
                    for key, value in plan.items()
                    if key not in {"plan_id", "content_sha256"}
                }
            )[:24]
            != plan_id
        ):
            return None, ["GENESIS_PLAN_NOT_FOUND_OR_TAMPERED"]
        if plan.get("status") != "pending-approval":
            return None, ["GENESIS_PLAN_NOT_PENDING"]
        try:
            expired = self.now() > parse_time(str(plan.get("expires_at")))
        except ValueError:
            expired = True
        if expired:
            return None, ["GENESIS_PLAN_EXPIRED"]
        return plan, []

    def guards_match(self, plan: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
        binding, binding_sha, fingerprint_sha = self.binding()
        current = self.source_guard()
        guards = plan.get("guards", {})
        checks = {
            "git_head": self.git_head() == guards.get("git_head"),
            "project_id": isinstance(binding, dict) and binding.get("project_id") == guards.get("project_id"),
            "binding_sha256": binding_sha == guards.get("binding_sha256"),
            "fingerprint_sha256": fingerprint_sha == guards.get("fingerprint_sha256"),
            "source_sha256": current["source_sha256"] == guards.get("source_sha256"),
            "source_revision": current["source_revision"] == guards.get("source_revision"),
        }
        return all(checks.values()), checks

    def projection_document(
        self,
        health: dict[str, Any],
        source: dict[str, Any] | None,
        source_sha256: str | None,
        generated_at: str,
    ) -> dict[str, Any]:
        state = str(health.get("state", "missing"))
        claims: dict[str, Any] = {}
        if state == "confirmed" and isinstance(source, dict):
            active, graph_errors = graph_result(source["claims"])
            if graph_errors:
                raise ValueError("confirmed Genesis has an invalid claim graph")
            claims = projected_truth(active)
        projection = {
            "schema_version": 1,
            "project_id": (
                source.get("project_id")
                if isinstance(source, dict)
                else (self.binding()[0] or {}).get("project_id")
            ),
            "genesis_revision": health.get("revision"),
            "genesis_state": state,
            "source_sha256": source_sha256,
            "generated_at": generated_at,
            "reason_codes": list(health.get("reason_codes", [])),
            "claims": claims,
        }
        if len(json_bytes(projection)) > MAX_PROJECTION_BYTES:
            raise ValueError("Genesis projection exceeds the 64 KiB budget")
        return projection

    def projection_status(self) -> dict[str, Any]:
        health = doctor(self.root)
        if not self.projection.is_file():
            code = (
                "GENESIS_PROJECTION_MISSING"
                if health.get("state") == "confirmed"
                else next(iter(health.get("reason_codes", [])), "GENESIS_PROJECTION_MISSING")
            )
            return {
                "ok": False,
                "state": health.get("state"),
                "reason_codes": [code],
                "claims": {},
            }
        try:
            if (
                has_symlink_component(self.project_root, self.projection)
                or self.projection.stat().st_size > MAX_PROJECTION_BYTES
            ):
                raise ValueError("projection path or budget is unsafe")
            projection = load_json(self.projection)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {
                "ok": False,
                "state": health.get("state"),
                "reason_codes": ["GENESIS_PROJECTION_STALE"],
                "claims": {},
            }
        expected_keys = {
            "schema_version", "project_id", "genesis_revision", "genesis_state",
            "source_sha256", "generated_at", "reason_codes", "claims",
        }
        structurally_valid = (
            isinstance(projection, dict)
            and set(projection) == expected_keys
            and projection.get("schema_version") == 1
            and SAFE_ID.fullmatch(str(projection.get("project_id", ""))) is not None
            and valid_datetime(projection.get("generated_at"))
            and isinstance(projection.get("reason_codes"), list)
            and isinstance(projection.get("claims"), dict)
        )
        if not structurally_valid:
            return {
                "ok": False,
                "state": health.get("state"),
                "reason_codes": ["GENESIS_PROJECTION_STALE"],
                "claims": {},
            }
        if health.get("state") != "confirmed":
            reasons = list(health.get("reason_codes", []))
            disclosed = bool(projection["claims"])
            binding = self.binding()[0] or {}
            matching = (
                projection.get("project_id") == binding.get("project_id")
                and
                projection.get("genesis_state") == health.get("state")
                and projection.get("source_sha256") == health.get("source_sha256")
                and projection.get("genesis_revision") == health.get("revision")
                and projection.get("reason_codes") == reasons
            )
            return {
                "ok": False,
                "state": health.get("state"),
                "reason_codes": reasons or ["GENESIS_CONFIRMATION_INCOMPLETE"],
                "claims": {},
                "projection_valid": matching and not disclosed,
                "nonconfirmed_claims_disclosed": disclosed,
            }
        try:
            source: dict[str, Any] = {}
            source = load_json(self.genesis)
            active, graph_errors = graph_result(source["claims"])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError):
            graph_errors = ["source unreadable"]
            active = {}
        expected_claims = projected_truth(active) if not graph_errors else {}
        matching = (
            projection.get("project_id") == source.get("project_id")
            and projection.get("genesis_revision") == health.get("revision")
            and projection.get("genesis_state") == "confirmed"
            and projection.get("source_sha256") == health.get("source_sha256")
            and projection.get("reason_codes") == []
            and projection.get("claims") == expected_claims
        )
        return {
            "ok": matching,
            "state": "confirmed",
            "reason_codes": [] if matching else ["GENESIS_PROJECTION_STALE"],
            "claims": expected_claims if matching else {},
        }

    def plan_migration(self, expiry_seconds: int = 900) -> dict[str, Any]:
        head = self.git_head()
        binding, binding_sha, fingerprint_sha = self.binding()
        template, template_errors = self.template_health()
        if not head or not binding or not binding_sha or not fingerprint_sha:
            return {"ok": False, "reason_codes": ["GENESIS_MIGRATION_BLOCKED"], "errors": ["verified Git HEAD and binding are required"]}
        if template is None:
            return {"ok": False, "reason_codes": ["GENESIS_MIGRATION_BLOCKED"], "errors": template_errors}
        if self.genesis.exists():
            health = doctor(self.root)
            reason = "GENESIS_MIGRATION_BLOCKED" if health.get("state") in {"contaminated", "conflicting", "stale"} else "GENESIS_MIGRATION_REQUIRED"
            return {
                "ok": False,
                "reason_codes": [reason],
                "errors": ["current schema has no migration to apply; use confirmation or projection flow"],
                "health": health,
            }
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["GENESIS_PLAN_EXPIRY_INVALID"]}
        created = self.now()
        timestamp = iso_time(created)
        project_id = str(binding["project_id"])
        identity = {
            "claim_id": "identity-v1",
            "value": {"project_id": project_id},
            "authority": "binding",
            "confidence": "verified",
            "evidence": [
                {
                    "kind": "binding",
                    "ref": BINDING_REF,
                    "sha256": binding_sha,
                    "git_commit": None,
                }
            ],
            "supersedes": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        document_id = f"genesis-{project_id}"
        if SAFE_ID.fullmatch(document_id) is None:
            document_id = f"genesis-{canonical_hash(project_id)[:24]}"
        document = {
            "schema_version": 1,
            "project_id": project_id,
            "document_id": document_id,
            "revision": 1,
            "claims": {slot: ([identity] if slot == "identity" else []) for slot in REQUIRED_SLOTS},
            "extensions": {},
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        after = json_bytes(document)
        guards = {
            "git_head": head,
            "project_id": project_id,
            "binding_sha256": binding_sha,
            "fingerprint_sha256": fingerprint_sha,
            "source_sha256": None,
            "source_revision": None,
        }
        plan = {
            "schema_version": 1,
            "plan_id": "",
            "content_sha256": "",
            "status": "pending-approval",
            "operation": "genesis-migration",
            "created_at": timestamp,
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "guards": guards,
            "template": {
                "path": ".agents/project-template/genesis.json",
                "state": "unbound",
                "reason_code": "GENESIS_TEMPLATE_UNBOUND",
                "sha256": sha256_project_file(self.project_root, self.template),
                "bytes_copied": False,
            },
            "target": "project/genesis.json",
            "before_sha256": None,
            "after_sha256": sha256_bytes(after),
            "after_document": document,
            "expected_state": "draft",
            "semantic_confirmation_performed": False,
            "exact_diff": exact_diff(None, after, "project/genesis.json"),
            "commit_created": False,
            "push_performed": False,
        }
        result = self.save_plan(plan)
        result["reason_codes"] = ["GENESIS_MIGRATION_REQUIRED"]
        return result

    def _write_transaction_receipt(
        self,
        transaction: Path,
        plan: dict[str, Any],
        status: str,
        changes: list[dict[str, Any]],
        error: str | None = None,
        rollback_verified: bool | None = None,
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": 1,
            "transaction_id": transaction.name,
            "plan_id": plan["plan_id"],
            "operation": plan["operation"],
            "status": status,
            "project_id": plan["guards"]["project_id"],
            "applied_at": iso_time(self.now()),
            "changes": changes,
            "semantic_confirmation_performed": plan["operation"] == "genesis-confirmation",
            "commit_created": False,
            "push_performed": False,
        }
        if error is not None:
            receipt["error"] = error
        if rollback_verified is not None:
            receipt["rollback_verified"] = rollback_verified
        backup_index = transaction / "backup-index.json"
        receipt["backup_index_sha256"] = sha256_file(backup_index) if backup_index.is_file() else None
        receipt["content_sha256"] = content_hash(receipt)
        atomic_bytes(transaction / "receipt.json", json_bytes(receipt))
        return receipt

    def _persist_backup(self, transaction: Path, before: dict[Path, bytes | None]) -> None:
        index: list[dict[str, Any]] = []
        for path, content in before.items():
            relative = path.relative_to(self.project_root).as_posix()
            index.append(
                {
                    "path": relative,
                    "existed": content is not None,
                    "sha256": sha256_bytes(content) if content is not None else None,
                }
            )
            if content is not None:
                atomic_bytes(transaction / "backup" / relative, content)
        atomic_bytes(transaction / "backup-index.json", json_bytes(index))

    def _restore(self, before: dict[Path, bytes | None]) -> bool:
        restored = True
        for path, content in reversed(list(before.items())):
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, content)
            except OSError:
                restored = False
        return restored and all(
            (path.read_bytes() if path.is_file() else None) == content
            for path, content in before.items()
        )

    def apply_migration(
        self,
        plan_id: str,
        confirm: bool,
        test_fail_after_write: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        plan, errors = self.load_plan(plan_id, "genesis-migration")
        if plan is None:
            return {"ok": False, "reason_codes": errors}
        guards_ok, guards = self.guards_match(plan)
        if not guards_ok:
            return {"ok": False, "reason_codes": ["GENESIS_MIGRATION_PLAN_STALE"], "guards": guards}
        after = json_bytes(plan.get("after_document"))
        if (
            sha256_bytes(after) != plan.get("after_sha256")
            or document_errors(plan.get("after_document"))
            or exact_diff(None, after, "project/genesis.json") != plan.get("exact_diff")
        ):
            return {"ok": False, "reason_codes": ["GENESIS_MIGRATION_BLOCKED"]}
        descriptor = self.acquire_lock()
        if descriptor is None:
            return {"ok": False, "reason_codes": ["GENESIS_TRANSACTION_BUSY"]}
        locked_guards_ok, locked_guards = self.guards_match(plan)
        if not locked_guards_ok:
            self.release_lock(descriptor)
            return {
                "ok": False,
                "reason_codes": ["GENESIS_MIGRATION_PLAN_STALE"],
                "guards": locked_guards,
            }
        transaction_id = canonical_hash(
            {"plan": plan_id, "at": iso_time(self.now()), "nonce": os.urandom(16).hex()}
        )[:24]
        transaction = self.transactions / transaction_id
        transaction.mkdir(parents=True, exist_ok=False)
        before = {
            self.genesis: self.genesis.read_bytes() if self.genesis.is_file() else None,
            self.projection: self.projection.read_bytes() if self.projection.is_file() else None,
        }
        changes = [
            {"path": "project/genesis.json", "before_sha256": None, "after_sha256": plan["after_sha256"]},
        ]
        try:
            self._persist_backup(transaction, before)
            self._write_transaction_receipt(transaction, plan, "applying", changes)
            atomic_bytes(self.genesis, after)
            if test_fail_after_write and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                raise RuntimeError("injected Genesis migration failure after source write")
            health = doctor(self.root)
            if health.get("state") != plan.get("expected_state"):
                raise RuntimeError(f"post-apply Genesis doctor returned {health.get('state')}")
            projection = self.projection_document(
                health,
                plan["after_document"],
                sha256_bytes(after),
                iso_time(self.now()),
            )
            projection_bytes = json_bytes(projection)
            atomic_bytes(self.projection, projection_bytes)
            changes.append(
                {
                    "path": "project/genesis-projection.json",
                    "before_sha256": sha256_bytes(before[self.projection]) if before[self.projection] is not None else None,
                    "after_sha256": sha256_bytes(projection_bytes),
                }
            )
            projection_health = self.projection_status()
            if projection_health.get("nonconfirmed_claims_disclosed") or not projection_health.get("projection_valid"):
                raise RuntimeError("non-confirmed projection verification failed")
            receipt = self._write_transaction_receipt(transaction, plan, "applied", changes)
            plan["status"] = "applied"
            plan["transaction_id"] = transaction_id
            plan["content_sha256"] = content_hash(plan)
            atomic_bytes(self.plans / f"{plan_id}.json", json_bytes(plan))
            return {
                "ok": True,
                "reason_codes": ["GENESIS_CONFIRMATION_INCOMPLETE"],
                "receipt": receipt,
                "health": health,
                "projection": projection_health,
            }
        except Exception as exc:
            rollback_verified = self._restore(before)
            receipt = self._write_transaction_receipt(
                transaction,
                plan,
                "rolled-back",
                changes,
                str(exc),
                rollback_verified,
            )
            plan["status"] = "failed"
            plan["transaction_id"] = transaction_id
            plan["content_sha256"] = content_hash(plan)
            atomic_bytes(self.plans / f"{plan_id}.json", json_bytes(plan))
            return {
                "ok": False,
                "reason_codes": ["GENESIS_MIGRATION_BLOCKED"],
                "receipt": receipt,
            }
        finally:
            self.release_lock(descriptor)

    def plan_confirmation(self, candidate: Any, expiry_seconds: int = 900) -> dict[str, Any]:
        head = self.git_head()
        binding, binding_sha, fingerprint_sha = self.binding()
        current_guard = self.source_guard()
        current_health = doctor(self.root)
        if (
            not head
            or not binding
            or not binding_sha
            or not fingerprint_sha
            or current_guard["source_sha256"] is None
            or not isinstance(candidate, dict)
            or current_health.get("state") not in {"draft", "confirmed"}
        ):
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"]}
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["GENESIS_PLAN_EXPIRY_INVALID"]}
        try:
            current = load_json(self.genesis)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"]}
        proposed = deepcopy(candidate)
        timestamp = iso_time(self.now())
        proposed["project_id"] = current.get("project_id")
        proposed["document_id"] = current.get("document_id")
        proposed["revision"] = int(current.get("revision", 0)) + 1
        proposed["created_at"] = current.get("created_at")
        proposed["updated_at"] = timestamp
        errors = document_errors(proposed)
        if proposed.get("project_id") != binding.get("project_id"):
            errors.append("candidate project_id does not match verified binding")
        if errors:
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"], "errors": errors}
        active, graph_errors = graph_result(proposed["claims"])
        errors.extend(graph_errors)
        for slot, claims in active.items():
            for claim in claims:
                contamination, stale = evidence_health(self.project_root, slot, claim)
                errors.extend(contamination)
                errors.extend(stale)
        for slot in REQUIRED_SLOTS:
            claims = active[slot]
            if slot in {"assumptions", "unknowns"}:
                if any(not uncertainty_is_non_blocking(claim["value"]) for claim in claims):
                    errors.append(f"blocking uncertainty remains in {slot}")
                continue
            if not claims:
                errors.append(f"required claim missing: {slot}")
                continue
            for claim in claims:
                if not meaningful_value(claim["value"]):
                    errors.append(f"required claim value is empty: {slot}/{claim['claim_id']}")
        if any(
            not any(
                item.get("kind") == "binding"
                and item.get("ref") == BINDING_REF
                and item.get("sha256") == binding_sha
                for item in claim.get("evidence", [])
            )
            for claim in active.get("identity", [])
        ):
            errors.append("identity claim is not bound to the verified Project Binding")
        required_extensions = [
            key
            for key, extension in proposed["extensions"].items()
            if extension.get("required_for_confirmation") is True
        ]
        if required_extensions:
            errors.append("required extension validators are unavailable")
        if errors:
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"], "errors": errors}
        for slot in TRUTH_SLOTS:
            for claim in active[slot]:
                claim.pop("confirmation", None)
                if slot == "identity":
                    claim["authority"] = "binding"
                    claim["confidence"] = "verified"
                else:
                    claim["authority"] = "user-confirmed"
                    claim["confidence"] = "confirmed"
                claim["updated_at"] = timestamp
        visible_delta = [
            {
                "slot": slot,
                "claim_id": claim["claim_id"],
                "value": claim["value"],
                "authority": claim["authority"],
                "confidence": claim["confidence"],
                "evidence": deepcopy(claim["evidence"]),
            }
            for slot in REQUIRED_SLOTS
            for claim in active[slot]
            if slot in TRUTH_SLOTS
        ]
        approval_sha = canonical_hash(
            {
                "schema_version": 1,
                "project_id": proposed["project_id"],
                "document_id": proposed["document_id"],
                "issued_for_revision": proposed["revision"],
                "visible_claim_delta": visible_delta,
            }
        )
        receipt_id = f"confirm-{approval_sha[:24]}"
        bindings = [
            {
                "slot": slot,
                "claim_id": claim["claim_id"],
                "basis_sha256": claim_basis_hash(proposed, slot, claim),
            }
            for slot in REQUIRED_SLOTS
            for claim in active[slot]
            if slot in TRUTH_SLOTS
        ]
        receipt = {
            "schema_version": 1,
            "receipt_id": receipt_id,
            "project_id": proposed["project_id"],
            "document_id": proposed["document_id"],
            "issued_for_revision": proposed["revision"],
            "confirmed_by_role": "owner",
            "confirmed_at": timestamp,
            "plan_sha256": approval_sha,
            "claim_bindings": bindings,
            "raw_conversation_stored": False,
            "content_sha256": "",
        }
        receipt["content_sha256"] = content_hash(receipt)
        receipt_bytes = json_bytes(receipt)
        receipt_sha = sha256_bytes(receipt_bytes)
        for slot in TRUTH_SLOTS:
            for claim in active[slot]:
                basis = claim_basis_hash(proposed, slot, claim)
                claim["confirmation"] = {
                    "event_id": receipt_id,
                    "receipt_ref": confirmation_ref(receipt_id),
                    "receipt_sha256": receipt_sha,
                    "basis_sha256": basis,
                }
        after = json_bytes(proposed)
        if document_errors(proposed):
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"]}
        guards = {
            "git_head": head,
            "project_id": binding["project_id"],
            "binding_sha256": binding_sha,
            "fingerprint_sha256": fingerprint_sha,
            **current_guard,
        }
        created = self.now()
        plan = {
            "schema_version": 1,
            "plan_id": "",
            "content_sha256": "",
            "status": "pending-approval",
            "operation": "genesis-confirmation",
            "created_at": iso_time(created),
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "guards": guards,
            "target": "project/genesis.json",
            "before_sha256": current_guard["source_sha256"],
            "after_sha256": sha256_bytes(after),
            "after_document": proposed,
            "confirmation_receipt": receipt,
            "confirmation_receipt_sha256": receipt_sha,
            "approval_sha256": approval_sha,
            "visible_claim_delta": visible_delta,
            "exact_diff": exact_diff(self.genesis.read_bytes(), after, "project/genesis.json"),
            "requires": ["explicit-owner-semantic-confirmation"],
            "commit_created": False,
            "push_performed": False,
        }
        return self.save_plan(plan)

    def apply_confirmation(
        self,
        plan_id: str,
        confirm: bool,
        test_fail_after_write: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["OWNER_SEMANTIC_CONFIRMATION_REQUIRED"]}
        plan, errors = self.load_plan(plan_id, "genesis-confirmation")
        if plan is None:
            return {"ok": False, "reason_codes": errors}
        guards_ok, guards = self.guards_match(plan)
        if not guards_ok:
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_STALE"], "guards": guards}
        after = json_bytes(plan.get("after_document"))
        receipt = plan.get("confirmation_receipt")
        if not isinstance(plan.get("after_document"), dict) or not isinstance(receipt, dict):
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"]}
        receipt_bytes = json_bytes(receipt)
        approval = canonical_hash(
            {
                "schema_version": 1,
                "project_id": plan["after_document"]["project_id"],
                "document_id": plan["after_document"]["document_id"],
                "issued_for_revision": plan["after_document"]["revision"],
                "visible_claim_delta": plan.get("visible_claim_delta"),
            }
        )
        receipt_path = self.project_root.joinpath(*Path(confirmation_ref(str(receipt.get("receipt_id", "")))).parts)
        if (
            sha256_bytes(after) != plan.get("after_sha256")
            or sha256_bytes(receipt_bytes) != plan.get("confirmation_receipt_sha256")
            or approval != plan.get("approval_sha256")
            or receipt.get("plan_sha256") != approval
            or receipt.get("content_sha256") != content_hash(receipt)
            or document_errors(plan.get("after_document"))
            or exact_diff(self.genesis.read_bytes(), after, "project/genesis.json") != plan.get("exact_diff")
            or receipt_path.exists()
        ):
            return {"ok": False, "reason_codes": ["GENESIS_CONFIRMATION_PLAN_BLOCKED"]}
        descriptor = self.acquire_lock()
        if descriptor is None:
            return {"ok": False, "reason_codes": ["GENESIS_TRANSACTION_BUSY"]}
        locked_guards_ok, locked_guards = self.guards_match(plan)
        if not locked_guards_ok:
            self.release_lock(descriptor)
            return {
                "ok": False,
                "reason_codes": ["GENESIS_CONFIRMATION_PLAN_STALE"],
                "guards": locked_guards,
            }
        transaction_id = canonical_hash(
            {"plan": plan_id, "at": iso_time(self.now()), "nonce": os.urandom(16).hex()}
        )[:24]
        transaction = self.transactions / transaction_id
        transaction.mkdir(parents=True, exist_ok=False)
        before = {
            receipt_path: receipt_path.read_bytes() if receipt_path.is_file() else None,
            self.genesis: self.genesis.read_bytes() if self.genesis.is_file() else None,
            self.projection: self.projection.read_bytes() if self.projection.is_file() else None,
        }
        changes = [
            {
                "path": confirmation_ref(receipt["receipt_id"]).removeprefix(".agents/"),
                "before_sha256": None,
                "after_sha256": sha256_bytes(receipt_bytes),
            },
            {
                "path": "project/genesis.json",
                "before_sha256": plan["before_sha256"],
                "after_sha256": plan["after_sha256"],
            },
        ]
        try:
            self._persist_backup(transaction, before)
            self._write_transaction_receipt(transaction, plan, "applying", changes)
            atomic_bytes(receipt_path, receipt_bytes)
            atomic_bytes(self.genesis, after)
            if test_fail_after_write and os.environ.get("AGENT_OS_TEST_MODE") == "1":
                raise RuntimeError("injected Genesis confirmation failure")
            health = doctor(self.root)
            if health.get("state") != "confirmed":
                raise RuntimeError(f"post-confirmation Genesis doctor returned {health.get('state')}")
            projection = self.projection_document(
                health,
                plan["after_document"],
                sha256_bytes(after),
                iso_time(self.now()),
            )
            projection_bytes = json_bytes(projection)
            atomic_bytes(self.projection, projection_bytes)
            changes.append(
                {
                    "path": "project/genesis-projection.json",
                    "before_sha256": sha256_bytes(before[self.projection]) if before[self.projection] is not None else None,
                    "after_sha256": sha256_bytes(projection_bytes),
                }
            )
            projection_health = self.projection_status()
            if not projection_health.get("ok"):
                raise RuntimeError("confirmed projection verification failed")
            transaction_receipt = self._write_transaction_receipt(transaction, plan, "applied", changes)
            plan["status"] = "applied"
            plan["transaction_id"] = transaction_id
            plan["content_sha256"] = content_hash(plan)
            atomic_bytes(self.plans / f"{plan_id}.json", json_bytes(plan))
            return {
                "ok": True,
                "receipt": transaction_receipt,
                "confirmation_receipt": receipt,
                "health": health,
                "projection": projection_health,
            }
        except Exception as exc:
            rollback_verified = self._restore(before)
            transaction_receipt = self._write_transaction_receipt(
                transaction,
                plan,
                "rolled-back",
                changes,
                str(exc),
                rollback_verified,
            )
            plan["status"] = "failed"
            plan["transaction_id"] = transaction_id
            plan["content_sha256"] = content_hash(plan)
            atomic_bytes(self.plans / f"{plan_id}.json", json_bytes(plan))
            return {
                "ok": False,
                "reason_codes": ["GENESIS_CONFIRMATION_APPLY_FAILED"],
                "receipt": transaction_receipt,
            }
        finally:
            self.release_lock(descriptor)

    def plan_projection(self, expiry_seconds: int = 900) -> dict[str, Any]:
        head = self.git_head()
        binding, binding_sha, fingerprint_sha = self.binding()
        health = doctor(self.root)
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["GENESIS_PLAN_EXPIRY_INVALID"]}
        if not head or not binding or not binding_sha or not fingerprint_sha or health.get("state") != "confirmed":
            return {
                "ok": False,
                "reason_codes": list(health.get("reason_codes", [])) or ["GENESIS_CONFIRMATION_INCOMPLETE"],
            }
        source = load_json(self.genesis)
        projection = self.projection_document(
            health,
            source,
            health["source_sha256"],
            iso_time(self.now()),
        )
        after = json_bytes(projection)
        before = self.projection.read_bytes() if self.projection.is_file() else None
        created = self.now()
        plan = {
            "schema_version": 1,
            "plan_id": "",
            "content_sha256": "",
            "status": "pending-approval",
            "operation": "genesis-projection",
            "created_at": iso_time(created),
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "guards": {
                "git_head": head,
                "project_id": binding["project_id"],
                "binding_sha256": binding_sha,
                "fingerprint_sha256": fingerprint_sha,
                **self.source_guard(),
            },
            "target": "project/genesis-projection.json",
            "before_sha256": sha256_bytes(before) if before is not None else None,
            "after_sha256": sha256_bytes(after),
            "after_projection": projection,
            "exact_diff": exact_diff(before, after, "project/genesis-projection.json"),
            "commit_created": False,
            "push_performed": False,
        }
        return self.save_plan(plan)

    def apply_projection(self, plan_id: str, confirm: bool) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        plan, errors = self.load_plan(plan_id, "genesis-projection")
        if plan is None:
            return {"ok": False, "reason_codes": errors}
        guards_ok, guards = self.guards_match(plan)
        current = self.projection.read_bytes() if self.projection.is_file() else None
        after = json_bytes(plan.get("after_projection"))
        current_sha256 = sha256_bytes(current) if current is not None else None
        if not guards_ok or current_sha256 != plan.get("before_sha256"):
            return {"ok": False, "reason_codes": ["GENESIS_PROJECTION_STALE"], "guards": guards}
        if (
            sha256_bytes(after) != plan.get("after_sha256")
            or exact_diff(current, after, "project/genesis-projection.json") != plan.get("exact_diff")
        ):
            return {"ok": False, "reason_codes": ["GENESIS_PROJECTION_STALE"]}
        descriptor = self.acquire_lock()
        if descriptor is None:
            return {"ok": False, "reason_codes": ["GENESIS_TRANSACTION_BUSY"]}
        transaction_id = canonical_hash(
            {"plan": plan_id, "at": iso_time(self.now()), "nonce": os.urandom(16).hex()}
        )[:24]
        transaction = self.transactions / transaction_id
        transaction.mkdir(parents=True, exist_ok=False)
        before = {self.projection: current}
        changes = [
            {
                "path": "project/genesis-projection.json",
                "before_sha256": current_sha256,
                "after_sha256": plan["after_sha256"],
            }
        ]
        try:
            locked_guards_ok, locked_guards = self.guards_match(plan)
            locked_current = self.projection.read_bytes() if self.projection.is_file() else None
            if (
                not locked_guards_ok
                or (sha256_bytes(locked_current) if locked_current is not None else None)
                != plan.get("before_sha256")
            ):
                raise RuntimeError(f"projection guards changed: {locked_guards}")
            self._persist_backup(transaction, before)
            self._write_transaction_receipt(transaction, plan, "applying", changes)
            atomic_bytes(self.projection, after)
            status = self.projection_status()
            if not status.get("ok"):
                raise RuntimeError("projection verification failed")
            receipt = self._write_transaction_receipt(transaction, plan, "applied", changes)
            plan["status"] = "applied"
            plan["transaction_id"] = transaction_id
            plan["content_sha256"] = content_hash(plan)
            atomic_bytes(self.plans / f"{plan_id}.json", json_bytes(plan))
            return {"ok": True, "projection": status, "receipt": receipt}
        except Exception as exc:
            rollback_verified = self._restore(before)
            receipt = self._write_transaction_receipt(
                transaction,
                plan,
                "rolled-back",
                changes,
                str(exc),
                rollback_verified,
            )
            plan["status"] = "failed"
            plan["transaction_id"] = transaction_id
            plan["content_sha256"] = content_hash(plan)
            atomic_bytes(self.plans / f"{plan_id}.json", json_bytes(plan))
            return {
                "ok": False,
                "reason_codes": ["GENESIS_PROJECTION_STALE"],
                "receipt": receipt,
            }
        finally:
            self.release_lock(descriptor)

    def recover(self, confirm: bool) -> dict[str, Any]:
        if not confirm:
            return {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
        descriptor = self.acquire_lock()
        if descriptor is None:
            return {"ok": False, "reason_codes": ["GENESIS_TRANSACTION_BUSY"]}
        recovered: list[str] = []
        blocked: list[str] = []
        try:
            directories = sorted(self.transactions.iterdir()) if self.transactions.is_dir() else []
            for transaction in directories:
                if not transaction.is_dir():
                    continue
                receipt_path = transaction / "receipt.json"
                try:
                    receipt = load_json(receipt_path)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    continue
                if (
                    not isinstance(receipt, dict)
                    or receipt.get("status") != "applying"
                    or receipt.get("content_sha256") != content_hash(receipt)
                ):
                    continue
                index_path = transaction / "backup-index.json"
                try:
                    index = load_json(index_path)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    blocked.append(transaction.name)
                    continue
                if (
                    not isinstance(index, list)
                    or receipt.get("backup_index_sha256") != sha256_file(index_path)
                ):
                    blocked.append(transaction.name)
                    continue
                restored = True
                for record in reversed(index):
                    relative = record.get("path") if isinstance(record, dict) else None
                    if (
                        not isinstance(relative, str)
                        or not relative.startswith(".agents/project/")
                        or Path(relative).is_absolute()
                        or ".." in Path(relative).parts
                    ):
                        restored = False
                        break
                    target = self.project_root.joinpath(*Path(relative).parts)
                    if has_symlink_component(self.project_root, target):
                        restored = False
                        break
                    if record.get("existed") is True:
                        backup = transaction.joinpath("backup", *Path(relative).parts)
                        if (
                            not backup.is_file()
                            or sha256_file(backup) != record.get("sha256")
                        ):
                            restored = False
                            break
                        atomic_bytes(target, backup.read_bytes())
                    else:
                        target.unlink(missing_ok=True)
                if restored:
                    restored = all(
                        (
                            self.project_root.joinpath(*Path(record["path"]).parts).is_file()
                            and sha256_file(
                                self.project_root.joinpath(*Path(record["path"]).parts)
                            )
                            == record.get("sha256")
                        )
                        if record.get("existed")
                        else not self.project_root.joinpath(*Path(record["path"]).parts).exists()
                        for record in index
                    )
                if not restored:
                    blocked.append(transaction.name)
                    continue
                receipt["status"] = "recovered-rolled-back"
                receipt["recovered_at"] = iso_time(self.now())
                receipt["rollback_verified"] = True
                receipt["content_sha256"] = content_hash(receipt)
                atomic_bytes(receipt_path, json_bytes(receipt))
                plan_id = str(receipt.get("plan_id", ""))
                if PLAN_ID.fullmatch(plan_id):
                    plan_path = self.plans / f"{plan_id}.json"
                    try:
                        plan = load_json(plan_path)
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                        plan = None
                    if isinstance(plan, dict) and plan.get("plan_id") == plan_id:
                        plan["status"] = "failed"
                        plan["recovered_transaction_id"] = transaction.name
                        plan["content_sha256"] = content_hash(plan)
                        atomic_bytes(plan_path, json_bytes(plan))
                recovered.append(transaction.name)
            return {
                "ok": not blocked,
                "recovered_transactions": recovered,
                "blocked_transactions": blocked,
                "reason_codes": [] if not blocked else ["GENESIS_RECOVERY_BLOCKED"],
            }
        finally:
            self.release_lock(descriptor)


def read_input(path: str) -> Any:
    return load_json(Path(path).expanduser().resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description="Project Genesis transaction engine")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan-migration")
    apply_migration = commands.add_parser("apply-migration")
    apply_migration.add_argument("--plan", required=True)
    apply_migration.add_argument("--confirm", action="store_true")
    plan_confirmation = commands.add_parser("plan-confirmation")
    plan_confirmation.add_argument("--input", required=True)
    apply_confirmation = commands.add_parser("apply-confirmation")
    apply_confirmation.add_argument("--plan", required=True)
    apply_confirmation.add_argument("--confirm", action="store_true")
    commands.add_parser("projection")
    commands.add_parser("plan-projection")
    apply_projection = commands.add_parser("apply-projection")
    apply_projection.add_argument("--plan", required=True)
    apply_projection.add_argument("--confirm", action="store_true")
    recover = commands.add_parser("recover")
    recover.add_argument("--confirm", action="store_true")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    service = GenesisService(args.root)
    try:
        if args.command == "plan-migration":
            result = service.plan_migration()
        elif args.command == "apply-migration":
            result = service.apply_migration(args.plan, args.confirm)
        elif args.command == "plan-confirmation":
            result = service.plan_confirmation(read_input(args.input))
        elif args.command == "apply-confirmation":
            result = service.apply_confirmation(args.plan, args.confirm)
        elif args.command == "projection":
            result = service.projection_status()
        elif args.command == "plan-projection":
            result = service.plan_projection()
        elif args.command == "apply-projection":
            result = service.apply_projection(args.plan, args.confirm)
        else:
            result = service.recover(args.confirm)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result = {"ok": False, "reason_codes": ["GENESIS_INPUT_OR_IO_INVALID"], "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
