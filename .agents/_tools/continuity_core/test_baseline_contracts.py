#!/usr/bin/env python3
"""Baseline, schema, template and read-only continuity acceptance contracts."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_continuity import (
    CATALOG_FIELDS,
    CORE_REGISTRY_REL,
    DEPENDENCY_FIELDS,
    PROFILE_REGISTRY_REL,
    REFERENCE_FIELDS,
    SOURCE_FIELDS,
    doctor,
    sha256_file,
)
from agent_os_continuity import ROOT as SOURCE_ROOT
from continuity_core.test_support import derive, file_snapshot, git_blob, make_fixture


def evaluate_baseline_contracts() -> tuple[dict[str, Any], list[tuple[str, bool]]]:
    cases: list[tuple[str, bool]] = []
    baseline = derive()
    cases.append(
        (
            "baseline-complete-with-state-aware-genesis-missing",
            baseline.get("topology_state") == "complete"
            and baseline.get("authority_state") == "partial"
            and baseline.get("ok") is True,
        )
    )
    schema = json.loads(
        (SOURCE_ROOT / "core/contracts/continuity-catalog.schema.json").read_text(
            encoding="utf-8"
        )
    )
    cases.append(
        (
            "schema-runtime-field-parity",
            set(schema["required"]) == CATALOG_FIELDS
            and set(schema["$defs"]["durableReference"]["required"]) == REFERENCE_FIELDS
            and set(schema["$defs"]["sourceReference"]["required"]) == SOURCE_FIELDS
            and set(schema["$defs"]["dependency"]["required"]) == DEPENDENCY_FIELDS,
        )
    )
    template = json.loads(
        (SOURCE_ROOT / "project-template/context/continuity.json").read_text(
            encoding="utf-8"
        )
    )
    cases.append(
        (
            "template-core-contract-hash-parity",
            template["record_type_registry"]["registry_sha256"]
            == sha256_file(SOURCE_ROOT / CORE_REGISTRY_REL)
            and template["recovery_profile"]["profile_sha256"]
            == sha256_file(SOURCE_ROOT / PROFILE_REGISTRY_REL),
        )
    )
    with tempfile.TemporaryDirectory(prefix="agent-os-continuity-read-only-") as temporary:
        read_only_root, _ = make_fixture(Path(temporary))
        before = file_snapshot(read_only_root.parent)
        read_only_result = doctor(read_only_root)
        after = file_snapshot(read_only_root.parent)
        cases.append(
            (
                "doctor-is-byte-preserving-read-only",
                read_only_result.get("ok") is True and before == after,
            )
        )
    with tempfile.TemporaryDirectory(prefix="agent-os-continuity-bytes-") as temporary:
        parity_root, parity_catalog = make_fixture(Path(temporary))
        parity_project = parity_root.parent
        parity_results = []
        for item in parity_catalog["references"]:
            source = item["source"]
            relative = source.get("path")
            commit = source.get("git_commit")
            expected_digest = source.get("sha256")
            if not all(
                isinstance(value, str) and value
                for value in (relative, commit, expected_digest)
            ):
                continue
            worktree_bytes = parity_project.joinpath(relative).read_bytes()
            committed_bytes = git_blob(parity_project, commit, relative)
            parity_results.append(
                worktree_bytes == committed_bytes
                and b"\r" not in worktree_bytes
                and worktree_bytes.endswith(b"\n")
                and hashlib.sha256(committed_bytes).hexdigest() == expected_digest
            )
        cases.append(
            (
                "fixture-sources-use-canonical-lf-and-match-committed-blobs",
                len(parity_results) == 6 and all(parity_results),
            )
        )
    return baseline, cases


def main() -> None:
    _baseline, cases = evaluate_baseline_contracts()
    results = [{"id": case_id, "passed": passed} for case_id, passed in cases]
    passed = sum(result["passed"] for result in results)
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "cases": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
