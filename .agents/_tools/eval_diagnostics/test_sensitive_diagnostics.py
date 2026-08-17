#!/usr/bin/env python3
"""Focused credential-redaction and false-positive diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from eval_diagnostics.test_support import sensitive_scenarios


def evaluate_sensitive_diagnostics() -> list[dict[str, Any]]:
    (
        sensitive_results,
        false_positive_source,
        false_positive_result,
    ) = sensitive_scenarios()
    return [
        *[
            {
                "id": f"redacts-{fixture_id}-without-consuming-safe-suffix",
                "passed": bool(
                    private_value not in redacted
                    and safe_suffix in redacted
                    and "[REDACTED]" in redacted
                ),
            }
            for fixture_id, redacted, private_value, safe_suffix in sensitive_results
        ],
        {
            "id": "credential-like-words-are-not-false-positives",
            "passed": false_positive_result == false_positive_source,
        },
    ]


def main() -> None:
    results = evaluate_sensitive_diagnostics()
    passed = sum(1 for result in results if result["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
