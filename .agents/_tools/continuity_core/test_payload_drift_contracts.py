#!/usr/bin/env python3
"""Payload, source drift, type and future-generation continuity contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from continuity_core.test_baseline_contracts import evaluate_baseline_contracts
from continuity_core.test_support import (
    PROJECT_ID,
    derive,
    has_code,
    reference,
    write_json,
)


def extension(fields: dict[str, Any], *, digest: str | None = None) -> dict[str, Any]:
    content = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "source_generation": 1,
        "migration_id": "continuity-catalog-v1-v2",
        "unknown_fields_sha256": digest or hashlib.sha256(content).hexdigest(),
        "fields": fields,
    }


def evaluate_payload_drift_contracts(baseline: dict[str, Any]) -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    def payload_in_catalog(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "genesis")["value"] = {"problem": "forbidden"}

    cases.append(("C06-state-aware-payload", has_code(derive(payload_in_catalog), "CONTINUITY_CATALOG_FORBIDDEN_PAYLOAD")))

    def state_aware_source_appeared(root: Path, catalog: dict[str, Any]) -> None:
        write_json(root / "project/genesis.json", {"schema_version": 1, "project_id": PROJECT_ID})

    cases.append(("C07-null-hash-source-appeared", has_code(derive(state_aware_source_appeared), "CONTINUITY_STATE_AWARE_SOURCE_APPEARED")))

    def source_drift(root: Path, catalog: dict[str, Any]) -> None:
        (root.parent / "docs/roadmap.md").write_text("# Drifted roadmap\n", encoding="utf-8")

    cases.append(("C08-source-drift", has_code(derive(source_drift), "CONTINUITY_SOURCE_DRIFT")))

    def revision_drift(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "release")["record_revision"] = "9.2.0"

    cases.append(
        (
            "C08-record-revision-drift",
            has_code(derive(revision_drift), "CONTINUITY_RECORD_REVISION_MISMATCH"),
        )
    )

    def unknown_type(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "roadmap")["record_type"] = "unknown-record"

    cases.append(("C09-unknown-record-type", has_code(derive(unknown_type), "CONTINUITY_RECORD_TYPE_UNSUPPORTED")))

    generation_one_hash: dict[str, str] = {}

    def generation_one(root: Path, catalog: dict[str, Any]) -> None:
        catalog["schema_version"] = 1
        catalog.pop("migration_extensions", None)
        serialized = (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        generation_one_hash["value"] = hashlib.sha256(serialized).hexdigest()

    generation_one_result = derive(generation_one)
    cases.append(
        (
            "known-generation-one-requires-migration",
            generation_one_result.get("state") == "MIGRATION_REQUIRED"
            and generation_one_result.get("authority_state") == "unavailable"
            and has_code(generation_one_result, "CONTINUITY_MIGRATION_REQUIRED")
            and generation_one_result.get("preserved_catalog_sha256")
            == generation_one_hash["value"],
        )
    )

    def matching_extension(root: Path, catalog: dict[str, Any]) -> None:
        catalog["migration_extensions"] = [
            extension({"zeta.flag": False, "legacy.flag": True})
        ]

    cases.append(
        (
            "generation-two-extension-hash-matches",
            derive(matching_extension).get("topology_state") == "complete",
        )
    )

    def mismatched_extension(root: Path, catalog: dict[str, Any]) -> None:
        catalog["migration_extensions"] = [
            extension({"legacy.flag": True}, digest="0" * 64)
        ]

    cases.append(
        (
            "generation-two-extension-hash-mismatch",
            has_code(
                derive(mismatched_extension),
                "CONTINUITY_MIGRATION_EXTENSION_HASH_MISMATCH",
            ),
        )
    )

    def forbidden_extension(root: Path, catalog: dict[str, Any]) -> None:
        catalog["migration_extensions"] = [
            extension({"legacy.metadata": {"secret": "password=do-not-store"}})
        ]

    cases.append(
        (
            "generation-two-extension-forbidden-payload",
            has_code(
                derive(forbidden_extension),
                "CONTINUITY_CATALOG_FORBIDDEN_PAYLOAD",
            ),
        )
    )

    def future_generation(root: Path, catalog: dict[str, Any]) -> None:
        catalog["schema_version"] = 99
        catalog["future_field"] = {"preserve": True}

    future = derive(future_generation)
    cases.append(
        (
            "C10-future-generation-preserved",
            future.get("state") == "UNSUPPORTED"
            and isinstance(future.get("preserved_catalog_sha256"), str),
        )
    )
    return cases


def main() -> None:
    baseline, prerequisite_cases = evaluate_baseline_contracts()
    cases = evaluate_payload_drift_contracts(baseline)
    results = [{"id": case_id, "passed": passed} for case_id, passed in cases]
    passed = sum(result["passed"] for result in results)
    prerequisite_ok = all(result for _case_id, result in prerequisite_cases)
    output = {
        "ok": passed == len(results) and prerequisite_ok,
        "passed": passed,
        "total": len(results),
        "prerequisite_ok": prerequisite_ok,
        "cases": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
