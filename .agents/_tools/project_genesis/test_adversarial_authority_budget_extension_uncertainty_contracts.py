#!/usr/bin/env python3
"""Focused Project Genesis adversarial authority and uncertainty contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from project_genesis.adversarial_support import run_lifecycle_case

ROOT = TOOLS_ROOT.parent
CORPUS = ROOT / "evals" / "project-genesis-adversarial.json"
SLICE_START = 30
SLICE_STOP = 40
CASE_IDS = (
    "git-inference-product-truth",
    "fabricated-project-decisions",
    "identity-unknown-confidence",
    "empty-product-truth",
    "boot-budget-exceeded",
    "constitutional-unknown",
    "nonblocking-assumption",
    "required-extension-unvalidated",
    "nested-confirmed-values",
    "empty-uncertainty-history",
)
CASE_IDS_SHA256 = "adc0f37226cab1c716d5ffeaf74603e7cb5e0975369a04988d7f45cccde51d2f"


def selected_cases(corpus: object) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(corpus, dict) or corpus.get("schema_version") != 1:
        return [], ["CORPUS_SCHEMA_INVALID"]
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        return [], ["CORPUS_CASES_INVALID"]
    selected = cases[SLICE_START:SLICE_STOP]
    if len(selected) != len(CASE_IDS) or not all(
        isinstance(case, dict) for case in selected
    ):
        return [], ["FOCUSED_SLICE_INVALID"]
    typed = [case for case in selected if isinstance(case, dict)]
    identifiers = tuple(case.get("id") for case in typed)
    digest = hashlib.sha256("\n".join(CASE_IDS).encode()).hexdigest()
    if identifiers != CASE_IDS or digest != CASE_IDS_SHA256:
        errors.append("FOCUSED_CASE_ORDER_INVALID")
    if any(case.get("kind") != "lifecycle" for case in typed):
        errors.append("FOCUSED_CASE_KIND_INVALID")
    if any(case.get("executable") is not True for case in typed):
        errors.append("FOCUSED_CASE_EXECUTABILITY_INVALID")
    return typed, errors


def main() -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    cases, errors = selected_cases(corpus)
    results = (
        [{"id": case["id"], "passed": run_lifecycle_case(case)} for case in cases]
        if not errors
        else []
    )
    ok = (
        not errors
        and len(results) == len(CASE_IDS)
        and all(item["passed"] for item in results)
    )
    output = {
        "ok": ok,
        "passed": sum(1 for item in results if item["passed"]),
        "total": len(results),
        "case_ids_sha256": CASE_IDS_SHA256,
        "errors": errors,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
