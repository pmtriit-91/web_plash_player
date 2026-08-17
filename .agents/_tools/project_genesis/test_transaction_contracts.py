#!/usr/bin/env python3
"""Focused AOS-14 W6 Genesis transaction and fresh-boot fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_genesis import (
    BINDING_REF,
    REQUIRED_SLOTS,
    TRUTH_SLOTS,
    content_hash,
    doctor,
    document_errors,
    sha256_project_file,
)
from agent_os_genesis_transactions import GenesisService
from agent_os_lifecycle import expected_adapter_digests

ROOT = TOOLS_ROOT.parent
STAMP = "2026-07-23T00:00:00Z"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(project: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr)
    return process.stdout.strip()


def write_verified_binding(root: Path, project_id: str) -> None:
    binding = {
        "schema_version": 1,
        "project_id": project_id,
        "repository": {"kind": "git", "root_markers": ["README.md"], "remote_aliases": []},
        "commands": [],
        "context_entrypoints": [],
        "created_at": STAMP,
        "last_verified_at": STAMP,
        "last_verified_commit": None,
    }
    fingerprint = {
        "schema_version": 1,
        "project_id": project_id,
        "binding_schema_version": 1,
        "algorithm": "sha256",
        "digests": expected_adapter_digests(binding),
        "verified_at": STAMP,
        "verified_commit": None,
    }
    write_json(root / "project/project-binding.json", binding)
    write_json(root / "project/adapter-fingerprint.json", fingerprint)


def unbound_fixture(base: Path, project_id: str = "w6-fixture") -> tuple[Path, Path]:
    project = base / project_id
    root = project / ".agents"
    root.joinpath("project").mkdir(parents=True)
    project.joinpath("README.md").write_text("# W6 fixture\n", encoding="utf-8")
    write_verified_binding(root, project_id)
    write_json(root / "_manifest/base-release-manifest.json", {"schema_version": 1, "entries": []})
    template = json.loads((ROOT / "project-template/genesis.json").read_text(encoding="utf-8"))
    write_json(root / "project-template/genesis.json", template)
    git(project, "init", "-q")
    git(project, "config", "core.autocrlf", "true")
    git(project, "config", "user.email", "fixture@example.invalid")
    git(project, "config", "user.name", "Genesis Fixture")
    git(project, "add", ".")
    git(project, "commit", "-qm", "fixture baseline")
    return project, root


def populate_candidate(root: Path) -> dict[str, Any]:
    document = json.loads((root / "project/genesis.json").read_text(encoding="utf-8"))
    timestamp = document["updated_at"]
    source_sha = sha256_project_file(root.parent, root.parent / "README.md")
    for slot in REQUIRED_SLOTS:
        if slot in {"identity", "assumptions", "unknowns"}:
            continue
        document["claims"][slot] = [
            {
                "claim_id": f"{slot.replace('_', '-')}-v1",
                "value": f"Owner-visible {slot}",
                "authority": "git-evidence",
                "confidence": "inferred",
                "evidence": [
                    {
                        "kind": "repository-file",
                        "ref": "README.md",
                        "sha256": source_sha,
                        "git_commit": None,
                    }
                ],
                "supersedes": [],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ]
    return document


def main() -> None:
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-genesis-w6-") as temporary:
        project, root = unbound_fixture(Path(temporary))
        service = GenesisService(root)
        migration_plan = service.plan_migration()
        plan = migration_plan.get("plan", {})
        template_document = json.loads((root / "project-template/genesis.json").read_text(encoding="utf-8"))
        cases.append(
            {
                "id": "initializer-plan",
                "passed": (
                    migration_plan.get("ok") is True
                    and "GENESIS_MIGRATION_REQUIRED" in migration_plan.get("reason_codes", [])
                    and plan.get("after_document", {}).get("project_id") == "w6-fixture"
                    and plan.get("template", {}).get("bytes_copied") is False
                    and plan.get("after_document") != template_document
                    and not document_errors(template_document)
                ),
            }
        )
        migration_apply = service.apply_migration(plan["plan_id"], True)
        projection_schema = json.loads(
            (root / "core/contracts/project-genesis-projection.schema.json").read_text(encoding="utf-8")
        ) if (root / "core/contracts/project-genesis-projection.schema.json").is_file() else json.loads(
            (ROOT / "core/contracts/project-genesis-projection.schema.json").read_text(encoding="utf-8")
        )
        projection_document = json.loads(
            (root / "project/genesis-projection.json").read_text(encoding="utf-8")
        )
        cases.append(
            {
                "id": "migration-remains-draft",
                "passed": (
                    migration_apply.get("ok") is True
                    and migration_apply.get("health", {}).get("state") == "draft"
                    and migration_apply.get("receipt", {}).get("semantic_confirmation_performed") is False
                    and not (root / "project/genesis-confirmations").exists()
                    and set(projection_document) == set(projection_schema["required"])
                ),
            }
        )
        candidate = populate_candidate(root)
        confirmation_plan = service.plan_confirmation(candidate)
        confirmation_apply = service.apply_confirmation(
            confirmation_plan.get("plan", {}).get("plan_id", ""),
            True,
        )
        cases.append(
            {
                "id": "separate-owner-confirmation",
                "error": json.dumps(
                    {
                        "plan_reason_codes": confirmation_plan.get("reason_codes", []),
                        "plan_errors": confirmation_plan.get("errors", []),
                        "apply_reason_codes": confirmation_apply.get("reason_codes", []),
                        "apply_error": confirmation_apply.get("receipt", {}).get("error"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "passed": (
                    confirmation_plan.get("ok") is True
                    and confirmation_plan.get("plan", {}).get("requires")
                    == ["explicit-owner-semantic-confirmation"]
                    and confirmation_apply.get("ok") is True
                    and confirmation_apply.get("health", {}).get("state") == "confirmed"
                    and confirmation_apply.get("projection", {}).get("ok") is True
                    and confirmation_apply.get("receipt", {}).get("semantic_confirmation_performed") is True
                ),
            }
        )
        git(project, "add", ".agents/project")
        git(project, "commit", "-qm", "persist confirmed application Genesis")
        clone = Path(temporary) / "fresh-clone"
        subprocess.run(
            ["git", "-c", "core.autocrlf=true", "clone", "-q", str(project), str(clone)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        git(clone, "config", "core.autocrlf", "true")
        fresh_root = clone / ".agents"
        fresh_doctor = doctor(fresh_root)
        fresh_projection = GenesisService(fresh_root).projection_status()
        cases.append(
            {
                "id": "fresh-session-recovery",
                "error": json.dumps(
                    {
                        "doctor_state": fresh_doctor.get("state"),
                        "doctor_reason_codes": fresh_doctor.get("reason_codes", []),
                        "doctor_stale": fresh_doctor.get("stale", []),
                        "projection_reason_codes": fresh_projection.get("reason_codes", []),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "passed": (
                    fresh_doctor.get("state") == "confirmed"
                    and fresh_projection.get("ok") is True
                    and b"\r\n" in (clone / "README.md").read_bytes()
                    and set(fresh_projection.get("claims", {})) == TRUTH_SLOTS
                    and fresh_projection["claims"]["identity"] == {"project_id": "w6-fixture"}
                ),
            }
        )
        identity = json.loads((fresh_root / "project/genesis.json").read_text(encoding="utf-8"))["claims"]["identity"][0]
        cases.append(
            {
                "id": "binding-evidence-retained",
                "passed": (
                    identity.get("authority") == "binding"
                    and identity.get("confidence") == "verified"
                    and identity.get("evidence", [{}])[0].get("ref") == BINDING_REF
                ),
            }
        )
        _recovery_project, recovery_root = unbound_fixture(Path(temporary), "recovery-fixture")
        recovery_service = GenesisService(recovery_root)
        recovery_plan = recovery_service.plan_migration()["plan"]
        interrupted = recovery_service.transactions / ("a" * 24)
        interrupted.mkdir(parents=True)
        before = {
            recovery_service.genesis: None,
            recovery_service.projection: None,
        }
        changes = [
            {
                "path": "project/genesis.json",
                "before_sha256": None,
                "after_sha256": recovery_plan["after_sha256"],
            }
        ]
        recovery_service._persist_backup(interrupted, before)
        recovery_service._write_transaction_receipt(
            interrupted,
            recovery_plan,
            "applying",
            changes,
        )
        write_json(recovery_service.genesis, recovery_plan["after_document"])
        recovery = recovery_service.recover(True)
        cases.append(
            {
                "id": "interrupted-transaction-recovery",
                "passed": (
                    recovery.get("ok") is True
                    and interrupted.name in recovery.get("recovered_transactions", [])
                    and not recovery_service.genesis.exists()
                    and not recovery_service.projection.exists()
                    and json.loads((interrupted / "receipt.json").read_text(encoding="utf-8")).get("status")
                    == "recovered-rolled-back"
                ),
            }
        )
        _tamper_project, tamper_root = unbound_fixture(Path(temporary), "tamper-fixture")
        tamper_service = GenesisService(tamper_root)
        tamper_plan = tamper_service.plan_migration()["plan"]
        tamper_path = tamper_service.plans / f"{tamper_plan['plan_id']}.json"
        tampered = json.loads(tamper_path.read_text(encoding="utf-8"))
        tampered["semantic_confirmation_performed"] = True
        tampered["content_sha256"] = content_hash(tampered)
        write_json(tamper_path, tampered)
        tamper_apply = tamper_service.apply_migration(tamper_plan["plan_id"], True)
        cases.append(
            {
                "id": "reviewed-plan-id-integrity",
                "passed": (
                    tamper_apply.get("ok") is False
                    and "GENESIS_PLAN_NOT_FOUND_OR_TAMPERED"
                    in tamper_apply.get("reason_codes", [])
                    and not tamper_service.genesis.exists()
                ),
            }
        )
    ok = all(case["passed"] for case in cases)
    print(json.dumps({"ok": ok, "cases": cases}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
