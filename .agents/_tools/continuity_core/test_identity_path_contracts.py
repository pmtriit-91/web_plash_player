#!/usr/bin/env python3
"""Identity, project, path, required and state-aware continuity contracts."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from continuity_core.test_baseline_contracts import evaluate_baseline_contracts
from continuity_core.test_support import derive, has_code, reference


def evaluate_identity_path_contracts(baseline: dict[str, Any]) -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    def duplicate_reference_id(root: Path, catalog: dict[str, Any]) -> None:
        duplicate = deepcopy(reference(catalog, "roadmap"))
        duplicate["record_id"] = "other-roadmap"
        catalog["references"].append(duplicate)

    cases.append(("C01-duplicate-reference-id", has_code(derive(duplicate_reference_id), "CONTINUITY_REFERENCE_ID_DUPLICATE")))

    def wrong_project(root: Path, catalog: dict[str, Any]) -> None:
        catalog["project_id"] = "other-project"

    cases.append(("C02-wrong-project", derive(wrong_project).get("topology_state") == "contaminated"))

    unsafe_paths = (
        "/absolute/roadmap.md",
        "../roadmap.md",
        "C:\\roadmap.md",
        "\\\\server\\share\\roadmap.md",
    )
    for index, unsafe in enumerate(unsafe_paths, start=1):
        def unsafe_path(root: Path, catalog: dict[str, Any], value: str = unsafe) -> None:
            reference(catalog, "roadmap")["source"]["path"] = value

        cases.append((f"C03-unsafe-path-{index}", derive(unsafe_path).get("topology_state") == "contaminated"))

    def symlink_escape(root: Path, catalog: dict[str, Any]) -> None:
        outside = root.parent.parent / "outside-continuity"
        outside.mkdir()
        outside.joinpath("roadmap.md").write_text("# Outside\n", encoding="utf-8")
        link = root.parent / "docs/escape.md"
        link.unlink(missing_ok=True)
        link.symlink_to(outside / "roadmap.md")
        reference(catalog, "roadmap")["source"]["path"] = "docs/escape.md"

    cases.append(("C03-symlink-path", derive(symlink_escape).get("topology_state") == "contaminated"))

    def missing_required(root: Path, catalog: dict[str, Any]) -> None:
        (root.parent / "docs/roadmap.md").unlink()

    cases.append(("C04-missing-required", derive(missing_required).get("topology_state") == "incomplete"))
    cases.append(("C05-state-aware-missing", baseline.get("authority_state") == "partial"))
    return cases


def main() -> None:
    baseline, prerequisite_cases = evaluate_baseline_contracts()
    cases = evaluate_identity_path_contracts(baseline)
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
