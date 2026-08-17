#!/usr/bin/env python3
"""Shared Project Genesis adversarial lifecycle fixtures and dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_os_genesis import (
    BINDING_REF,
    PRODUCT_SLOTS,
    REQUIRED_SLOTS,
    canonical_hash,
    confirmation_ref,
    content_hash,
    doctor,
    sha256_file,
)
from agent_os_genesis_transactions import GenesisService
from agent_os_lifecycle import collect_release_entries, expected_adapter_digests
from project_genesis.test_support import RECEIPT_ID, issue_confirmation
from project_genesis.test_support import fixture as w3_fixture

ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-07-23T00:00:00Z"

DOMAIN_PROFILES = {
    "confirmed-node-monorepo": {
        "project_id": "node-monorepo",
        "source": "package.json",
        "content": "{\"name\":\"fixture-node\",\"private\":true}\n",
        "values": {
            "problem": "Coordinate safe agent work across a Node monorepo.",
            "success": {"metrics": [{"id": "workspace-recovery", "target": "100%", "window": "clean-clone"}]},
            "constraints": [{"id": "package-boundary", "rule": "Never mix workspace ownership."}],
        },
    },
    "confirmed-python-service": {
        "project_id": "python-service",
        "source": "pyproject.toml",
        "content": "[project]\nname = \"fixture-python\"\nversion = \"0.1.0\"\n",
        "values": {
            "problem": "Maintain a Python service without losing operational constraints.",
            "success": {"metrics": [{"id": "recovery", "target": "deterministic", "window": "fresh-session"}]},
            "constraints": [{"id": "runtime", "rule": "Remain dependency-light and offline-capable."}],
        },
    },
    "confirmed-documentation-site": {
        "project_id": "documentation-site",
        "source": "mkdocs.yml",
        "content": "site_name: Fixture Documentation\n",
        "values": {
            "problem": "Keep documentation intent and publishing boundaries recoverable.",
            "success": {"metrics": [{"id": "navigation", "target": "complete", "window": "release"}]},
            "constraints": [{"id": "content", "rule": "Do not publish private project records."}],
        },
    },
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(project: Path, *arguments: str) -> None:
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


def install_verified_binding(root: Path, project_id: str) -> None:
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
    write_json(root / "project/project-binding.json", binding)
    write_json(
        root / "project/adapter-fingerprint.json",
        {
            "schema_version": 1,
            "project_id": project_id,
            "binding_schema_version": 1,
            "algorithm": "sha256",
            "digests": expected_adapter_digests(binding),
            "verified_at": STAMP,
            "verified_commit": None,
        },
    )


def transaction_fixture(base: Path, project_id: str) -> tuple[Path, GenesisService]:
    project = base / project_id
    root = project / ".agents"
    root.joinpath("project").mkdir(parents=True)
    project.joinpath("README.md").write_text("# Genesis transaction fixture\n", encoding="utf-8")
    install_verified_binding(root, project_id)
    write_json(root / "_manifest/base-release-manifest.json", {"schema_version": 1, "entries": []})
    template = json.loads((ROOT / "project-template/genesis.json").read_text(encoding="utf-8"))
    write_json(root / "project-template/genesis.json", template)
    git(project, "init", "-q")
    git(project, "config", "user.email", "fixture@example.invalid")
    git(project, "config", "user.name", "Genesis Fixture")
    git(project, "add", ".")
    git(project, "commit", "-qm", "fixture baseline")
    return root, GenesisService(root)


def run_transaction_case(case: dict[str, Any]) -> bool:
    with tempfile.TemporaryDirectory(prefix="agent-os-genesis-transaction-") as temporary:
        identifier = case["id"]
        migration_cases = {
            "migration-apply-is-not-confirmation",
            "migration-plan-stale",
            "migration-partial-write",
            "projection-nonconfirmed-disclosure",
            "initializer-materializes-binding",
        }
        if identifier in migration_cases:
            root, service = transaction_fixture(Path(temporary), "transaction-fixture")
            plan_result = service.plan_migration()
            if not plan_result.get("ok"):
                return False
            plan = plan_result["plan"]
            if identifier == "initializer-materializes-binding":
                template = json.loads((root / "project-template/genesis.json").read_text(encoding="utf-8"))
                after = plan["after_document"]
                return (
                    case["expected_reason"] in plan_result.get("reason_codes", [])
                    and after["project_id"] == "transaction-fixture"
                    and after["document_id"] == "genesis-transaction-fixture"
                    and after["claims"]["identity"][0]["evidence"][0]["ref"] == BINDING_REF
                    and after != template
                    and plan["template"]["bytes_copied"] is False
                )
            if identifier == "migration-plan-stale":
                binding = json.loads((root / "project/project-binding.json").read_text(encoding="utf-8"))
                binding["last_verified_at"] = "2026-07-23T00:00:01Z"
                write_json(root / "project/project-binding.json", binding)
                result = service.apply_migration(plan["plan_id"], True)
                return (
                    not result.get("ok")
                    and case["expected_reason"] in result.get("reason_codes", [])
                    and not (root / "project/genesis.json").exists()
                )
            if identifier == "migration-partial-write":
                previous = os.environ.get("AGENT_OS_TEST_MODE")
                os.environ["AGENT_OS_TEST_MODE"] = "1"
                try:
                    result = service.apply_migration(plan["plan_id"], True, test_fail_after_write=True)
                finally:
                    if previous is None:
                        os.environ.pop("AGENT_OS_TEST_MODE", None)
                    else:
                        os.environ["AGENT_OS_TEST_MODE"] = previous
                return (
                    not result.get("ok")
                    and case["expected_reason"] in result.get("reason_codes", [])
                    and result.get("receipt", {}).get("rollback_verified") is True
                    and not (root / "project/genesis.json").exists()
                    and not (root / "project/genesis-projection.json").exists()
                )
            result = service.apply_migration(plan["plan_id"], True)
            if not result.get("ok"):
                return False
            if identifier == "migration-apply-is-not-confirmation":
                document = json.loads((root / "project/genesis.json").read_text(encoding="utf-8"))
                authorities = {
                    claim["authority"]
                    for history in document["claims"].values()
                    for claim in history
                }
                return (
                    case["expected_reason"] in result.get("reason_codes", [])
                    and result.get("health", {}).get("state") == "draft"
                    and result.get("receipt", {}).get("semantic_confirmation_performed") is False
                    and "user-confirmed" not in authorities
                    and not (root / "project/genesis-confirmations").exists()
                )
            projection = json.loads((root / "project/genesis-projection.json").read_text(encoding="utf-8"))
            status = service.projection_status()
            return (
                case["expected_reason"] in status.get("reason_codes", [])
                and status.get("projection_valid") is True
                and status.get("nonconfirmed_claims_disclosed") is False
                and projection.get("claims") == {}
            )
        if identifier == "projection-source-drift":
            root, document = fixture(Path(temporary))
            install_verified_binding(root, document["project_id"])
            document["claims"]["identity"][0]["evidence"][0]["sha256"] = sha256_file(
                root / "project/project-binding.json"
            )
            reissue(root, document)
            write_json(root / "project/genesis.json", document)
            project = root.parent
            git(project, "init", "-q")
            git(project, "config", "core.autocrlf", "false")
            git(project, "config", "user.email", "fixture@example.invalid")
            git(project, "config", "user.name", "Genesis Fixture")
            git(project, "add", ".")
            git(project, "commit", "-qm", "confirmed Genesis baseline")
            service = GenesisService(root)
            projection_plan = service.plan_projection()
            if not projection_plan.get("ok"):
                return False
            projection_apply = service.apply_projection(projection_plan["plan"]["plan_id"], True)
            if not projection_apply.get("ok"):
                return False
            document["revision"] += 1
            reissue(root, document)
            write_json(root / "project/genesis.json", document)
            status = service.projection_status()
            return (
                not status.get("ok")
                and case["expected_reason"] in status.get("reason_codes", [])
                and status.get("claims") == {}
            )
        return False


def release_selection_cases() -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="agent-os-genesis-purity-") as temporary:
        root = Path(temporary) / ".agents"
        policy = json.loads((ROOT / "core/contracts/ownership-policy.json").read_text(encoding="utf-8"))
        write_json(root / "core/contracts/ownership-policy.json", policy)
        write_json(root / "project/genesis.json", {"project_id": "consumer-private-project", "private_marker": "consumer-only-genesis"})
        write_json(
            root / "project/genesis-confirmations/confirm-private.json",
            {"receipt_id": "confirm-private", "private_marker": "consumer-only-confirmation"},
        )
        write_json(root / "project-template/genesis.json", {"project_id": "unbound-consumer", "claims": {}})
        entries, unclassified = collect_release_entries(root)
        selected_content = b"".join(
            (root / relative).read_bytes()
            for relative, entry in entries.items()
            if entry.get("type") == "file"
        )
        return [
            {
                "id": "actual-genesis-excluded",
                "passed": "project/genesis.json" not in entries and not unclassified,
            },
            {
                "id": "actual-confirmation-ledger-excluded",
                "passed": "project/genesis-confirmations/confirm-private.json" not in entries and not unclassified,
            },
            {
                "id": "unbound-template-release-owned-without-private-bytes",
                "passed": (
                    "project-template/genesis.json" in entries
                    and entries["project-template/genesis.json"].get("type") == "file"
                    and b"consumer-only-genesis" not in selected_content
                    and b"consumer-only-confirmation" not in selected_content
                ),
            },
        ]


def fixture(base: Path) -> tuple[Path, dict[str, Any]]:
    return w3_fixture(base)


def reissue(root: Path, document: dict[str, Any]) -> None:
    issue_confirmation(root, document)


def second_claim(document: dict[str, Any], slot: str, claim_id: str, value: Any) -> dict[str, Any]:
    claim = deepcopy(document["claims"][slot][0])
    claim["claim_id"] = claim_id
    claim["value"] = value
    return claim


def apply_domain_profile(identifier: str, root: Path, document: dict[str, Any]) -> None:
    profile = DOMAIN_PROFILES[identifier]
    project = root.parent
    source = project / profile["source"]
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(profile["content"], encoding="utf-8")
    binding = {"schema_version": 1, "project_id": profile["project_id"]}
    write_json(root / "project/project-binding.json", binding)
    document["project_id"] = profile["project_id"]
    document["document_id"] = f"genesis-{profile['project_id']}"
    binding_digest = sha256_file(root / "project/project-binding.json")
    source_digest = sha256_file(source)
    identity = document["claims"]["identity"][0]
    identity["evidence"] = [{"kind": "binding", "ref": BINDING_REF, "sha256": binding_digest, "git_commit": None}]
    for slot in REQUIRED_SLOTS:
        if slot in {"identity", "assumptions", "unknowns"}:
            continue
        claim = document["claims"][slot][0]
        claim["evidence"] = [{"kind": "repository-file", "ref": profile["source"], "sha256": source_digest, "git_commit": None}]
        if slot in profile["values"]:
            claim["value"] = profile["values"][slot]
    reissue(root, document)


def mutate(identifier: str, root: Path, document: dict[str, Any]) -> bool:
    if identifier == "missing":
        return False
    if identifier in DOMAIN_PROFILES:
        apply_domain_profile(identifier, root, document)
    elif identifier == "schema-invalid":
        document["unexpected"] = True
    elif identifier == "duplicate-json-key":
        pass
    elif identifier == "non-finite-json-number":
        document["claims"]["success"][0]["value"] = float("nan")
    elif identifier == "secret-material":
        document["claims"]["problem"][0]["value"] = "api_key=fixture-secret"
    elif identifier == "secret-evidence-ref":
        document["claims"]["problem"][0]["evidence"][0]["ref"] = "token=fixture-secret"
    elif identifier == "absolute-evidence":
        document["claims"]["problem"][0]["evidence"][0]["ref"] = "/tmp/outside"
    elif identifier == "windows-drive-evidence":
        document["claims"]["problem"][0]["evidence"][0]["ref"] = "C:/outside.json"
    elif identifier == "wrong-project":
        document["project_id"] = "other-project"
    elif identifier == "unbound-placeholder-copied":
        document["project_id"] = "unbound-consumer"
        document["document_id"] = "genesis-unbound-consumer"
        document["claims"] = {slot: [] for slot in REQUIRED_SLOTS}
    elif identifier == "actual-genesis-in-manifest":
        write_json(
            root / "_manifest/base-release-manifest.json",
            {"schema_version": 1, "entries": [{"path": "project/genesis.json"}]},
        )
    elif identifier == "singleton-conflict":
        document["claims"]["problem"].append(second_claim(document, "problem", "problem-v2", "Incompatible problem"))
    elif identifier == "duplicate-compatible-singleton":
        document["claims"]["problem"].append(second_claim(document, "problem", "problem-v2", document["claims"]["problem"][0]["value"]))
    elif identifier == "supersession-cycle":
        successor = second_claim(document, "problem", "problem-v2", "Successor problem")
        document["claims"]["problem"][0]["supersedes"] = ["problem-v2"]
        successor["supersedes"] = ["problem-v1"]
        document["claims"]["problem"].append(successor)
    elif identifier == "cross-slot-supersession":
        document["claims"]["problem"][0]["supersedes"] = ["primary-user-v1"]
    elif identifier == "duplicate-claim-id":
        document["claims"]["primary_user"][0]["claim_id"] = "identity-v1"
    elif identifier == "supersedes-non-string":
        document["claims"]["problem"][0]["supersedes"] = [1]
    elif identifier == "confirmation-drift":
        document["claims"]["problem"][0]["confirmation"]["basis_sha256"] = "0" * 64
    elif identifier == "evidence-drift":
        document["claims"]["problem"][0]["evidence"][0]["sha256"] = "0" * 64
    elif identifier == "evidence-basis-swapped":
        alternate = root.parent / "ALTERNATE.md"
        alternate.write_text("different but valid evidence\n", encoding="utf-8")
        document["claims"]["problem"][0]["evidence"] = [
            {"kind": "repository-file", "ref": "ALTERNATE.md", "sha256": sha256_file(alternate), "git_commit": None}
        ]
    elif identifier == "fabricated-off-repo-evidence":
        for history in document["claims"].values():
            for claim in history:
                claim["evidence"] = [
                    {"kind": "research-artifact", "ref": "does-not-exist.json", "sha256": "0" * 64, "git_commit": None}
                ]
    elif identifier == "symlink-evidence-escape":
        outside = root.parent.parent / "outside-evidence"
        outside.mkdir()
        outside_file = outside / "evidence.txt"
        outside_file.write_text("outside project\n", encoding="utf-8")
        (root.parent / "linked-evidence").symlink_to(outside, target_is_directory=True)
        document["claims"]["problem"][0]["evidence"] = [
            {
                "kind": "repository-file",
                "ref": "linked-evidence/evidence.txt",
                "sha256": sha256_file(outside_file),
                "git_commit": None,
            }
        ]
    elif identifier == "confirmation-receipt-missing":
        (root.parent / confirmation_ref(RECEIPT_ID)).unlink()
    elif identifier == "confirmation-receipt-tampered":
        receipt_path = root.parent / confirmation_ref(RECEIPT_ID)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["confirmed_at"] = "2026-07-23T00:00:01Z"
        write_json(receipt_path, receipt)
    elif identifier == "confirmation-receipt-wrong-project":
        receipt_path = root.parent / confirmation_ref(RECEIPT_ID)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["project_id"] = "other-project"
        receipt["content_sha256"] = content_hash(receipt)
        write_json(receipt_path, receipt)
        digest = sha256_file(receipt_path)
        for history in document["claims"].values():
            for claim in history:
                if "confirmation" in claim:
                    claim["confirmation"]["receipt_sha256"] = digest
    elif identifier == "confirmation-ledger-symlink":
        receipt_path = root.parent / confirmation_ref(RECEIPT_ID)
        receipt_bytes = receipt_path.read_bytes()
        receipt_path.unlink()
        receipt_path.parent.rmdir()
        outside = root.parent.parent / "outside-confirmations"
        outside.mkdir()
        (outside / f"{RECEIPT_ID}.json").write_bytes(receipt_bytes)
        receipt_path.parent.symlink_to(outside, target_is_directory=True)
    elif identifier == "inline-confirmation-forgery":
        document["claims"]["problem"][0]["confirmation"] = {
            "event_id": "fabricated-inline",
            "confirmed_by": "owner",
            "confirmed_at": STAMP,
            "basis_sha256": canonical_hash(document["claims"]["problem"][0]["value"]),
        }
    elif identifier == "fake-binding-evidence":
        document["claims"]["identity"][0]["evidence"] = [
            {"kind": "binding", "ref": "missing-binding.json", "sha256": "0" * 64, "git_commit": None}
        ]
    elif identifier == "binding-evidence-drift":
        document["claims"]["identity"][0]["evidence"][0]["sha256"] = "0" * 64
    elif identifier == "impossible-date":
        document["updated_at"] = "2026-99-99T99:99:99Z"
    elif identifier == "git-inference-product-truth":
        claim = document["claims"]["problem"][0]
        claim.pop("confirmation")
        claim["authority"] = "git-evidence"
        claim["confidence"] = "inferred"
    elif identifier == "fabricated-project-decisions":
        decision_path = root.parent / "decisions/decision.json"
        write_json(decision_path, {"id": "local-untrusted-decision", "status": "recorded"})
        digest = sha256_file(decision_path)
        for slot in ("acceptance_evidence", "scope", "constraints"):
            claim = document["claims"][slot][0]
            claim.pop("confirmation")
            claim["authority"] = "project-decision"
            claim["confidence"] = "verified"
            claim["evidence"] = [
                {"kind": "decision-receipt", "ref": "decisions/decision.json", "sha256": digest, "git_commit": None}
            ]
    elif identifier == "identity-unknown-confidence":
        document["claims"]["identity"][0]["confidence"] = "unknown"
        reissue(root, document)
    elif identifier == "empty-product-truth":
        for slot in PRODUCT_SLOTS:
            document["claims"][slot][0]["value"] = ""
        reissue(root, document)
    elif identifier == "boot-budget-exceeded":
        for slot in PRODUCT_SLOTS:
            document["claims"][slot][0]["value"] = f"{slot}:" + ("x" * 7000)
        reissue(root, document)
    elif identifier == "constitutional-unknown":
        readme_digest = sha256_file(root.parent / "README.md")
        document["claims"]["unknowns"] = [
            {
                "claim_id": "unknown-user-v1",
                "value": [{"question": "Who is the primary user?", "impact": "constitutional"}],
                "authority": "research-only",
                "confidence": "unknown",
                "evidence": [{"kind": "repository-file", "ref": "README.md", "sha256": readme_digest, "git_commit": None}],
                "supersedes": [],
                "created_at": STAMP,
                "updated_at": STAMP,
            }
        ]
    elif identifier == "nonblocking-assumption":
        readme_digest = sha256_file(root.parent / "README.md")
        document["claims"]["assumptions"] = [
            {
                "claim_id": "assumption-runtime-v1",
                "value": [{"statement": "The runtime remains local.", "impact": "non-blocking"}],
                "authority": "research-only",
                "confidence": "inferred",
                "evidence": [{"kind": "repository-file", "ref": "README.md", "sha256": readme_digest, "git_commit": None}],
                "supersedes": [],
                "created_at": STAMP,
                "updated_at": STAMP,
            }
        ]
    elif identifier == "required-extension-unvalidated":
        document["extensions"]["com.example.required"] = {
            "schema_ref": "schemas/example-v1.json",
            "owner": "application",
            "required_for_confirmation": True,
            "value": {"enabled": True},
        }
    elif identifier == "nested-confirmed-values":
        document["claims"]["success"][0]["value"] = {
            "metrics": [{"id": "activation", "target": 0.8, "window": "30d"}]
        }
        document["claims"]["constraints"][0]["value"] = [
            {"id": "privacy", "rule": "No raw credentials"}
        ]
        reissue(root, document)
    elif identifier == "empty-uncertainty-history":
        document["claims"]["assumptions"] = []
        document["claims"]["unknowns"] = []
    else:
        raise ValueError(f"unknown executable fixture {identifier}")
    return True


def run_lifecycle_case(case: dict[str, Any]) -> bool:
    with tempfile.TemporaryDirectory(prefix="agent-os-genesis-adversarial-") as temporary:
        root, document = fixture(Path(temporary))
        should_write = mutate(case["id"], root, document)
        if should_write:
            write_json(root / "project/genesis.json", document)
            if case["id"] == "duplicate-json-key":
                path = root / "project/genesis.json"
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace("{\n", "{\n  \"schema_version\": 1,\n", 1), encoding="utf-8")
        result = doctor(root)
        state_matches = result.get("state") == case.get("expected_state")
        reason = case.get("expected_reason")
        return state_matches and (reason in result.get("reason_codes", []) if reason else not result.get("reason_codes"))
