#!/usr/bin/env python3
"""Focused Project Genesis lifecycle derivation contracts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_genesis import confirmation_ref
from project_genesis.test_support import RECEIPT_ID, derive, issue_confirmation


def git(root: Path, *arguments: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=root.parent, input=input_text, text=True,
        capture_output=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def git_bytes(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root.parent,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def repository_evidence(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        evidence
        for claims in document["claims"].values()
        for claim in claims
        for evidence in claim["evidence"]
        if evidence["kind"] != "binding"
    ]


def pin_repository_evidence(root: Path, document: dict[str, Any]) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Genesis Fixture")
    git(root, "config", "user.email", "genesis-fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture evidence")
    commit = git(root, "rev-parse", "HEAD")
    for evidence in repository_evidence(document):
        evidence["git_commit"] = commit
        evidence["sha256"] = hashlib.sha256(
            git_bytes(root, "show", f"{commit}:{evidence['ref']}")
        ).hexdigest()
    for claims in document["claims"].values():
        for claim in claims:
            for evidence in claim["evidence"]:
                if evidence["kind"] == "binding":
                    evidence["sha256"] = hashlib.sha256(
                        git_bytes(root, "show", f"{commit}:{evidence['ref']}")
                    ).hexdigest()
    issue_confirmation(root, document)
    return commit


def stale_has(result: dict[str, Any], fragment: str) -> bool:
    return result.get("state") == "stale" and any(
        fragment in item for item in result.get("stale", [])
    )


def main() -> None:
    cases: list[tuple[str, bool]] = []
    cases.append(("missing", derive(write=False).get("state") == "missing"))

    def invalid(root: Path, document: dict[str, Any]) -> None:
        document["unexpected"] = True

    invalid_result = derive(invalid)
    cases.append(
        (
            "invalid-is-draft",
            invalid_result.get("state") == "draft"
            and "GENESIS_DOCUMENT_INVALID" in invalid_result.get("reason_codes", []),
        )
    )

    def contaminated(root: Path, document: dict[str, Any]) -> None:
        document["project_id"] = "other-project"

    cases.append(("contaminated", derive(contaminated).get("state") == "contaminated"))

    def conflicting(root: Path, document: dict[str, Any]) -> None:
        competing = deepcopy(document["claims"]["problem"][0])
        competing["claim_id"] = "problem-v2"
        competing["value"] = "Incompatible problem"
        document["claims"]["problem"].append(competing)

    cases.append(("conflicting", derive(conflicting).get("state") == "conflicting"))

    def stale(root: Path, document: dict[str, Any]) -> None:
        document["claims"]["problem"][0]["confirmation"]["basis_sha256"] = "0" * 64

    cases.append(("stale", derive(stale).get("state") == "stale"))

    def missing_receipt(root: Path, document: dict[str, Any]) -> None:
        (root.parent / confirmation_ref(RECEIPT_ID)).unlink()

    cases.append(("missing-receipt-is-stale", derive(missing_receipt).get("state") == "stale"))

    def draft(root: Path, document: dict[str, Any]) -> None:
        document["claims"]["problem"][0].pop("confirmation")
        document["claims"]["problem"][0]["authority"] = "git-evidence"
        document["claims"]["problem"][0]["confidence"] = "inferred"

    cases.append(("draft", derive(draft).get("state") == "draft"))

    def pinned_current_drift(root: Path, document: dict[str, Any]) -> None:
        pin_repository_evidence(root, document)
        root.parent.joinpath("README.md").write_text("# Current drift\r\n", encoding="utf-8")

    pinned_result = derive(pinned_current_drift)
    cases.append(("reachable-pinned-evidence-survives-current-drift", pinned_result.get("state") == "confirmed"))

    normalization_observed: list[bool] = []

    def pinned_crlf_normalization(root: Path, document: dict[str, Any]) -> None:
        source = root.parent / "README.md"
        source.write_bytes(b"# Fixture\r\n")
        checkout_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        for evidence in repository_evidence(document):
            evidence["sha256"] = checkout_digest
        binding = root.parent / ".agents/project/project-binding.json"
        binding.write_bytes(binding.read_bytes().replace(b"\n", b"\r\n"))
        document["claims"]["identity"][0]["evidence"][0]["sha256"] = hashlib.sha256(
            binding.read_bytes()
        ).hexdigest()
        git(root, "init", "-q")
        git(root, "config", "core.autocrlf", "true")
        commit = pin_repository_evidence(root, document)
        blob = subprocess.run(
            ["git", "show", f"{commit}:README.md"],
            cwd=root.parent,
            capture_output=True,
            timeout=10,
            check=True,
        ).stdout
        pinned_digest = hashlib.sha256(blob).hexdigest()
        binding_blob = git_bytes(
            root, "show", f"{commit}:.agents/project/project-binding.json"
        )
        normalization_observed.append(
            checkout_digest != pinned_digest
            and all(
                evidence["sha256"] == pinned_digest
                for evidence in repository_evidence(document)
            )
            and document["claims"]["identity"][0]["evidence"][0]["sha256"]
            == hashlib.sha256(binding_blob).hexdigest()
        )

    normalized_result = derive(pinned_crlf_normalization)
    cases.append(
        (
            "pinned-evidence-uses-canonical-git-blob-after-crlf-normalization",
            normalization_observed == [True]
            and normalized_result.get("state") == "confirmed",
        )
    )

    def missing_commit(root: Path, document: dict[str, Any]) -> None:
        pin_repository_evidence(root, document)
        for evidence in repository_evidence(document):
            evidence["git_commit"] = "f" * 40
        issue_confirmation(root, document)

    cases.append(("missing-pinned-commit-is-stale", stale_has(derive(missing_commit), "commit missing")))

    def unreachable_commit(root: Path, document: dict[str, Any]) -> None:
        pin_repository_evidence(root, document)
        orphan = git(root, "commit-tree", git(root, "write-tree"), input_text="orphan\n")
        for evidence in repository_evidence(document):
            evidence["git_commit"] = orphan
        issue_confirmation(root, document)

    cases.append(("unreachable-pinned-commit-is-stale", stale_has(derive(unreachable_commit), "commit unreachable")))

    def missing_pinned_path(root: Path, document: dict[str, Any]) -> None:
        pin_repository_evidence(root, document)
        git(root, "rm", "-q", "README.md")
        git(root, "commit", "-qm", "remove evidence")
        for evidence in repository_evidence(document):
            evidence["git_commit"] = git(root, "rev-parse", "HEAD")
        issue_confirmation(root, document)

    cases.append(("path-absent-at-pinned-commit-is-stale", stale_has(derive(missing_pinned_path), "path absent")))

    def pinned_symlink(root: Path, document: dict[str, Any]) -> None:
        pin_repository_evidence(root, document)
        source = root.parent / "README.md"
        source.unlink()
        target_blob = git(root, "hash-object", "-w", "--stdin", input_text="linked-evidence")
        git(root, "update-index", "--add", "--cacheinfo", f"120000,{target_blob},README.md")
        git(root, "commit", "-qm", "replace evidence with symlink")
        for evidence in repository_evidence(document):
            evidence["git_commit"] = git(root, "rev-parse", "HEAD")
        issue_confirmation(root, document)

    cases.append(("symlink-at-pinned-commit-is-stale", stale_has(derive(pinned_symlink), "symlink at commit")))

    def pinned_hash_mismatch(root: Path, document: dict[str, Any]) -> None:
        pin_repository_evidence(root, document)
        for evidence in repository_evidence(document):
            evidence["sha256"] = "0" * 64
        issue_confirmation(root, document)

    cases.append(("pinned-hash-mismatch-is-stale", stale_has(derive(pinned_hash_mismatch), "Git hash drift")))

    def unpinned_current_drift(root: Path, document: dict[str, Any]) -> None:
        root.parent.joinpath("README.md").write_text("# Unpinned drift\n", encoding="utf-8")

    cases.append(("unpinned-current-drift-is-stale", stale_has(derive(unpinned_current_drift), "evidence drift")))

    def pinned_binding(root: Path, document: dict[str, Any]) -> None:
        document["claims"]["identity"][0]["evidence"][0]["git_commit"] = "a" * 40

    binding_result = derive(pinned_binding)
    cases.append(("binding-cannot-be-historically-pinned", binding_result.get("state") == "draft"))

    confirmed = derive()
    cases.append(("confirmed", confirmed.get("state") == "confirmed" and confirmed.get("ok") is True))

    def empty_uncertainty(root: Path, document: dict[str, Any]) -> None:
        document["claims"]["assumptions"] = []
        document["claims"]["unknowns"] = []

    empty_uncertainty_result = derive(empty_uncertainty)
    cases.append(
        (
            "empty-uncertainty-is-confirmed",
            empty_uncertainty_result.get("state") == "confirmed"
            and empty_uncertainty_result.get("ok") is True,
        )
    )

    ok = all(passed for _, passed in cases)
    print(json.dumps({"ok": ok, "cases": [{"id": name, "passed": passed} for name, passed in cases]}, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
