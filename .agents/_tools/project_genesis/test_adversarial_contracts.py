#!/usr/bin/env python3
"""Aggregate Project Genesis adversarial and release-selection acceptance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from project_genesis.adversarial_support import (
    release_selection_cases,
    run_lifecycle_case,
    run_transaction_case,
)

ROOT = TOOLS_ROOT.parent
CORPUS = ROOT / "evals" / "project-genesis-adversarial.json"


def main() -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases = corpus.get("cases", []) if isinstance(corpus, dict) else []
    identifiers = [case.get("id") for case in cases if isinstance(case, dict)]
    corpus_ok = bool(corpus.get("schema_version") == 1 and cases and len(identifiers) == len(set(identifiers)))
    results: list[dict[str, Any]] = []
    for case in cases:
        if case.get("executable"):
            passed = (
                run_lifecycle_case(case)
                if case.get("kind") == "lifecycle"
                else run_transaction_case(case)
            )
            results.append({"id": case.get("id"), "kind": case.get("kind"), "executable": True, "passed": passed})
        else:
            specified = bool(
                case.get("kind") in {"migration-contract", "projection-contract"}
                and case.get("expected_reason")
                and case.get("acceptance")
            )
            results.append(
                {
                    "id": case.get("id"),
                    "kind": case.get("kind"),
                    "executable": False,
                    "non_executable_specified": specified,
                }
            )
    results.extend({**item, "kind": "release-selection", "executable": True} for item in release_selection_cases())
    executable = [item for item in results if item["executable"]]
    specifications = [item for item in results if not item["executable"]]
    ok = (
        corpus_ok
        and all(item["passed"] for item in executable)
        and all(item["non_executable_specified"] for item in specifications)
    )
    output = {
        "ok": ok,
        "passed": sum(1 for item in executable if item["passed"]),
        "total": len(executable),
        "non_executable_specified": sum(
            1 for item in specifications if item["non_executable_specified"]
        ),
        "non_executable_total": len(specifications),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
