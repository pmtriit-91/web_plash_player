#!/usr/bin/env python3
"""BR3c0 focused parity shard for extracted handoff validation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import handoff_validation

COMMIT = "a" * 40
DIGEST = "b" * 64


class FakeService:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.root = project_root / ".agents"
        self.git_issues: list[dict[str, Any]] = []
        self.legacy_commit: str | None = COMMIT

    def path(self, relative: str) -> Path:
        return self.root / relative

    def binding(self) -> dict[str, Any]:
        return {"project_id": "fixture-project"}

    def commit_exists(self, commit: str) -> bool:
        return commit == COMMIT

    def commit_is_ancestor(self, commit: str) -> bool:
        return commit == COMMIT

    def validate_git_evidence_ref(
        self, ref: dict[str, Any], *, require_current: bool
    ) -> list[dict[str, Any]]:
        del ref
        assert require_current is False
        return self.git_issues

    def find_reachable_evidence_commit(
        self, path: str, digest: str, preferred_commit: str
    ) -> str | None:
        assert (path, digest, preferred_commit) == ("docs/evidence.md", DIGEST, COMMIT)
        return self.legacy_commit


def receipt(receipt_id: str, *, schema_version: int = 2) -> dict[str, Any]:
    evidence: dict[str, Any] = {"path": "docs/evidence.md", "sha256": DIGEST}
    if schema_version == 2:
        evidence["git_commit"] = COMMIT
    value = {
        "schema_version": schema_version,
        "id": receipt_id,
        "project_id": "fixture-project",
        "task_id": "task-one",
        "from_owner": "owner-one",
        "to_owner": None,
        "base_commit": COMMIT,
        "created_at": "2026-08-03T00:00:00Z",
        "verified_outcomes": ["Outcome verified"],
        "unresolved_risks": [],
        "next_action": "Continue bounded work",
        "evidence": [evidence],
        "content_sha256": "",
    }
    value["content_sha256"] = facade.receipt_hash(value)
    return value


def persist(
    service: FakeService, value: dict[str, Any], filename_id: str | None = None
) -> None:
    directory = service.path(facade.HANDOFF_DIR_REL)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{filename_id or value['id']}.json"
    target.write_bytes(facade.json_bytes(value))


def case_facade_delegates(base: Path) -> bool:
    del base
    service = object.__new__(facade.ContextMemoryService)
    original = facade.context_handoffs.validate_handoffs
    facade.context_handoffs.validate_handoffs = lambda received: {
        "delegated": received is service
    }
    try:
        return service.validate_handoffs() == {"delegated": True}
    finally:
        facade.context_handoffs.validate_handoffs = original


def case_missing_directory(base: Path) -> bool:
    result = handoff_validation.validate_handoffs(FakeService(base))
    return result == {
        "errors": [],
        "warnings": [],
        "summary": {
            "receipts": 0,
            "legacy_receipts": 0,
            "git_durable_receipts": 0,
            "evidence_references": 0,
            "recoverable_references": 0,
            "legacy_recoverable_references": 0,
            "unrecoverable_references": 0,
        },
        "valid_receipts": [],
    }


def case_invalid_directory(base: Path) -> bool:
    service = FakeService(base)
    directory = service.path(facade.HANDOFF_DIR_REL)
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.write_text("not-a-directory\n", encoding="utf-8")
    result = handoff_validation.validate_handoffs(service)
    return result["errors"] == [
        {"code": "HANDOFF_DIRECTORY_INVALID", "path": facade.HANDOFF_DIR_REL}
    ]


def case_v2_valid_and_sorted(base: Path) -> bool:
    service = FakeService(base)
    second = receipt("handoff-" + "2" * 24)
    first = receipt("handoff-" + "1" * 24)
    persist(service, second)
    persist(service, first)
    result = handoff_validation.validate_handoffs(service)
    return (
        result["errors"] == []
        and [item["id"] for item in result["valid_receipts"]]
        == [first["id"], second["id"]]
        and result["summary"]
        == {
            "receipts": 2,
            "legacy_receipts": 0,
            "git_durable_receipts": 2,
            "evidence_references": 2,
            "recoverable_references": 2,
            "legacy_recoverable_references": 0,
            "unrecoverable_references": 0,
        }
    )


def case_v2_durability_failure(base: Path) -> bool:
    service = FakeService(base)
    value = receipt("handoff-" + "3" * 24)
    persist(service, value)
    service.git_issues = [{"code": "CONTEXT_EVIDENCE_COMMIT_MISSING"}]
    result = handoff_validation.validate_handoffs(service)
    return (
        result["errors"]
        == [
            {
                "code": "HANDOFF_EVIDENCE_NOT_GIT_DURABLE",
                "id": value["id"],
                "path": "docs/evidence.md",
                "cause": "CONTEXT_EVIDENCE_COMMIT_MISSING",
            }
        ]
        and result["valid_receipts"] == []
        and result["summary"]["unrecoverable_references"] == 1
    )


def case_legacy_disclosure_stays_valid(base: Path) -> bool:
    service = FakeService(base)
    service.legacy_commit = None
    value = receipt("handoff-" + "4" * 24, schema_version=1)
    persist(service, value)
    result = handoff_validation.validate_handoffs(service)
    return (
        result["errors"] == []
        and result["warnings"]
        == [
            {
                "code": "HISTORICAL_HANDOFF_EVIDENCE_UNRECOVERABLE",
                "id": value["id"],
                "path": "docs/evidence.md",
                "cause": "CONTEXT_EVIDENCE_NOT_REACHABLE",
            }
        ]
        and result["valid_receipts"] == [value]
        and result["summary"]["legacy_receipts"] == 1
    )


def case_filename_and_id_mismatch(base: Path) -> bool:
    service = FakeService(base)
    value = receipt("handoff-" + "5" * 24)
    persist(service, value, "handoff-" + "6" * 24)
    result = handoff_validation.validate_handoffs(service)
    return result["errors"] == [
        {"code": "HANDOFF_FILENAME_ID_MISMATCH", "id": "handoff-" + "6" * 24}
    ]


def case_tamper_and_forbidden_fail_closed(base: Path) -> bool:
    service = FakeService(base)
    tampered = receipt("handoff-" + "7" * 24)
    tampered["next_action"] = "Tampered after hashing"
    forbidden = receipt("handoff-" + "8" * 24)
    forbidden["next_action"] = "chain of thought: private"
    forbidden["content_sha256"] = facade.receipt_hash(forbidden)
    persist(service, tampered)
    persist(service, forbidden)
    codes = [
        item["code"] for item in handoff_validation.validate_handoffs(service)["errors"]
    ]
    return codes == ["HANDOFF_RECEIPT_INVALID_OR_TAMPERED", "HANDOFF_FORBIDDEN_PAYLOAD"]


CASES = [
    ("facade-delegation", case_facade_delegates),
    ("missing-directory", case_missing_directory),
    ("invalid-directory", case_invalid_directory),
    ("v2-valid-sorted", case_v2_valid_and_sorted),
    ("v2-durability-failure", case_v2_durability_failure),
    ("legacy-disclosure", case_legacy_disclosure_stays_valid),
    ("filename-id-mismatch", case_filename_and_id_mismatch),
    ("tamper-forbidden", case_tamper_and_forbidden_fail_closed),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br3c0-") as temporary:
        for index, (name, check) in enumerate(CASES):
            try:
                passed, error = bool(check(Path(temporary) / str(index))), None
            except Exception as exc:  # noqa: BLE001 - bounded case diagnostics
                passed, error = False, str(exc)
            results.append(
                {"id": name, "passed": passed, **({"error": error} if error else {})}
            )
    output = {
        "ok": all(item["passed"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
