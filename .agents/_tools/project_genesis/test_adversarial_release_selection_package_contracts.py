#!/usr/bin/env python3
"""Focused Project Genesis adversarial release-selection package contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from project_genesis.adversarial_support import release_selection_cases

CASE_IDS = (
    "actual-genesis-excluded",
    "actual-confirmation-ledger-excluded",
    "unbound-template-release-owned-without-private-bytes",
)
CASE_IDS_SHA256 = "246684b9d4f77868c958ae089a849bc0870ce9ee4298401b33db0f9e42b974f5"


def selected_results(value: object) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list) or len(value) != len(CASE_IDS):
        return [], ["FOCUSED_RELEASE_SELECTION_INVALID"]
    if not all(isinstance(item, dict) for item in value):
        return [], ["FOCUSED_RELEASE_SELECTION_INVALID"]
    typed = [item for item in value if isinstance(item, dict)]
    identifiers = tuple(item.get("id") for item in typed)
    digest = hashlib.sha256("\n".join(CASE_IDS).encode()).hexdigest()
    errors: list[str] = []
    if identifiers != CASE_IDS or digest != CASE_IDS_SHA256:
        errors.append("FOCUSED_CASE_ORDER_INVALID")
    if any(item.get("passed") is not True for item in typed):
        errors.append("FOCUSED_CASE_ACCEPTANCE_FAILED")
    return typed, errors


def main() -> None:
    results, errors = selected_results(release_selection_cases())
    ok = not errors and len(results) == len(CASE_IDS)
    output = {
        "ok": ok,
        "passed": sum(1 for item in results if item.get("passed") is True),
        "total": len(results),
        "case_ids_sha256": CASE_IDS_SHA256,
        "errors": errors,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
