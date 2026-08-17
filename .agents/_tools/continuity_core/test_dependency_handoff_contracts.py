#!/usr/bin/env python3
"""Dependency, supersession, handoff and completion continuity contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from continuity_core.test_baseline_contracts import evaluate_baseline_contracts
from continuity_core.test_support import derive, git, has_code, reference, source


def evaluate_dependency_handoff_contracts(baseline: dict[str, Any]) -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    def dangling_dependency(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "roadmap")["dependencies"].append(
            {"relation": "requires", "target_reference_id": "missing-reference"}
        )

    cases.append(("C11-dangling-dependency", derive(dangling_dependency).get("topology_state") == "incomplete"))

    def dependency_cycle(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "roadmap")["dependencies"].append(
            {"relation": "requires", "target_reference_id": "current-status"}
        )
        reference(catalog, "current-status")["dependencies"].append(
            {"relation": "requires", "target_reference_id": "roadmap"}
        )

    cases.append(("C12-dependency-cycle", has_code(derive(dependency_cycle), "CONTINUITY_DEPENDENCY_CYCLE")))

    def cross_type_supersession(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "roadmap")["supersedes"].append("current-status")

    cases.append(("C13-cross-type-supersession", has_code(derive(cross_type_supersession), "CONTINUITY_SUPERSESSION_CROSS_TYPE")))

    def duplicate_successor(root: Path, catalog: dict[str, Any]) -> None:
        predecessor = deepcopy(reference(catalog, "roadmap"))
        predecessor["reference_id"] = "roadmap-old"
        predecessor["record_id"] = "roadmap-old"
        predecessor["lifecycle"] = "superseded"
        predecessor["requirement"] = "advisory"
        predecessor["retention_class"] = "critical-history"
        first = reference(catalog, "roadmap")
        first["supersedes"] = ["roadmap-old"]
        second = deepcopy(first)
        second["reference_id"] = "roadmap-successor-two"
        second["record_id"] = "roadmap-successor-two"
        catalog["references"].extend([predecessor, second])

    duplicate_successor_result = derive(duplicate_successor)
    cases.append(
        (
            "C14-duplicate-active-successor",
            has_code(duplicate_successor_result, "CONTINUITY_ACTIVE_SUCCESSOR_CONFLICT")
            and any(
                item.get("readiness") == "conflicting"
                for item in duplicate_successor_result.get("references", [])
                if item.get("reference_id") in {"roadmap", "roadmap-successor-two"}
            ),
        )
    )

    def archived_required(root: Path, catalog: dict[str, Any]) -> None:
        reference(catalog, "roadmap")["lifecycle"] = "archived"

    cases.append(("C15-required-reference-archived", derive(archived_required).get("topology_state") == "incomplete"))

    def invalid_handoff(root: Path, catalog: dict[str, Any]) -> None:
        project = root.parent
        commit = git(project, "rev-parse", "HEAD")
        path = "evidence/not-a-handoff.json"
        catalog["references"].append(
            source(
                "handoff",
                "handoff-receipt",
                "current-handoff",
                "handoff-fixture",
                path,
                hashlib.sha256(project.joinpath(path).read_bytes()).hexdigest(),
                commit,
                "handoff-receipt",
                2,
                revision=2,
                requirement="required",
                load_policy="just-in-time",
                provider="handoff-receipt-validator",
            )
        )

    invalid_handoff_result = derive(invalid_handoff)
    cases.append(("C16-invalid-handoff", has_code(invalid_handoff_result, "CONTINUITY_HANDOFF_INVALID_OR_TAMPERED")))
    cases.append(("C17-completion-verification-missing", has_code(invalid_handoff_result, "CONTINUITY_COMPLETION_VERIFICATION_MISSING")))
    return cases


def main() -> None:
    baseline, prerequisite_cases = evaluate_baseline_contracts()
    cases = evaluate_dependency_handoff_contracts(baseline)
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
