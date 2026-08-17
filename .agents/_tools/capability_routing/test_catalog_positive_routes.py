#!/usr/bin/env python3
"""Catalog and first positive-route acceptance for capability routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capabilities import route_capability, validate_catalog

CASES = [
    ("Make a small typo fix and minor CSS spacing change.", "fast_ui_fix"),
    ("Design a multi-module architecture migration with rollback.", "architecture_refactor"),
    ("Audit the Agent OS vendor skill provenance.", "agent_os_maintenance"),
    ("Use NotebookLM Studio to create a report.", "notebooklm_research"),
    ("Design a public REST API contract and module boundary.", "api-and-interface-design"),
    ("Review this PR for code quality before merge.", "code-review-and-quality"),
]


def main() -> None:
    catalog = validate_catalog()
    results: list[dict[str, object]] = [
        {"id": "catalog-valid", "passed": catalog.get("ok") is True},
        {"id": "all-routes-described", "passed": catalog.get("routes") == catalog.get("descriptors") == 15},
    ]
    for index, (prompt, expected) in enumerate(CASES, start=1):
        routed = route_capability(prompt)
        selected = routed["selected"]
        results.append(
            {
                "id": f"positive-route-{index}",
                "passed": selected.get("id") == expected and bool(selected.get("evidence")),
            }
        )
    passed = sum(1 for result in results if result["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
