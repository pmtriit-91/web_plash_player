from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_os_genesis import (
    BINDING_REF,
    REQUIRED_SLOTS,
    TRUTH_SLOTS,
    canonical_hash,
    claim_basis_hash,
    confirmation_ref,
    content_hash,
    doctor,
    sha256_file,
)

STAMP = "2026-07-23T00:00:00Z"
RECEIPT_ID = "confirm-genesis-v1"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def issue_confirmation(root: Path, document: dict[str, Any]) -> None:
    bindings = [
        {
            "slot": slot,
            "claim_id": claim["claim_id"],
            "basis_sha256": claim_basis_hash(document, slot, claim),
        }
        for slot in REQUIRED_SLOTS
        for claim in document["claims"][slot]
        if slot in TRUTH_SLOTS
    ]
    receipt = {
        "schema_version": 1,
        "receipt_id": RECEIPT_ID,
        "project_id": document["project_id"],
        "document_id": document["document_id"],
        "issued_for_revision": document["revision"],
        "confirmed_by_role": "owner",
        "confirmed_at": STAMP,
        "plan_sha256": canonical_hash({"fixture": "owner-visible-confirmation-plan"}),
        "claim_bindings": bindings,
        "raw_conversation_stored": False,
        "content_sha256": "",
    }
    receipt["content_sha256"] = content_hash(receipt)
    receipt_path = root.parent / confirmation_ref(RECEIPT_ID)
    write_json(receipt_path, receipt)
    receipt_sha256 = sha256_file(receipt_path)
    for slot in TRUTH_SLOTS:
        for claim in document["claims"][slot]:
            claim["confirmation"] = {
                "event_id": RECEIPT_ID,
                "receipt_ref": confirmation_ref(RECEIPT_ID),
                "receipt_sha256": receipt_sha256,
                "basis_sha256": claim_basis_hash(document, slot, claim),
            }


def fixture(base: Path) -> tuple[Path, dict[str, Any]]:
    project = base / "fixture"
    root = project / ".agents"
    root.joinpath("project").mkdir(parents=True)
    project.joinpath("README.md").write_text("# Fixture\n", encoding="utf-8")
    binding = {"schema_version": 1, "project_id": "fixture-project"}
    write_json(root / "project/project-binding.json", binding)
    write_json(
        root / "_manifest/base-release-manifest.json",
        {"schema_version": 1, "entries": []},
    )
    source_digest = hashlib.sha256(
        project.joinpath("README.md").read_bytes()
    ).hexdigest()
    binding_digest = sha256_file(root / "project/project-binding.json")
    claims: dict[str, list[dict[str, Any]]] = {}
    for slot in REQUIRED_SLOTS:
        if slot in {"assumptions", "unknowns"}:
            claims[slot] = []
            continue
        authority = "binding" if slot == "identity" else "user-confirmed"
        evidence = (
            [
                {
                    "kind": "binding",
                    "ref": BINDING_REF,
                    "sha256": binding_digest,
                    "git_commit": None,
                }
            ]
            if slot == "identity"
            else [
                {
                    "kind": "repository-file",
                    "ref": "README.md",
                    "sha256": source_digest,
                    "git_commit": None,
                }
            ]
        )
        claims[slot] = [
            {
                "claim_id": f"{slot.replace('_', '-')}-v1",
                "value": f"Confirmed {slot}",
                "authority": authority,
                "confidence": "verified" if authority == "binding" else "confirmed",
                "evidence": evidence,
                "supersedes": [],
                "created_at": STAMP,
                "updated_at": STAMP,
            }
        ]
    document = {
        "schema_version": 1,
        "project_id": "fixture-project",
        "document_id": "genesis-fixture-project",
        "revision": 1,
        "claims": claims,
        "extensions": {},
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    issue_confirmation(root, document)
    return root, document


def derive(
    mutator: Callable[[Path, dict[str, Any]], None] | None = None, write: bool = True
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="agent-os-genesis-") as temporary:
        root, document = fixture(Path(temporary))
        if mutator:
            mutator(root, document)
        if write:
            write_json(root / "project/genesis.json", document)
        return doctor(root)
