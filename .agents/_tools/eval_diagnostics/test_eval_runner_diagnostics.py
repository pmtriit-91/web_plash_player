#!/usr/bin/env python3
"""Aggregate regression checks for bounded eval failure diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from eval_diagnostics.test_sensitive_diagnostics import (
    evaluate_sensitive_diagnostics,
)
from eval_diagnostics.test_structured_diagnostics import (
    evaluate_structured_diagnostics,
)


def main() -> None:
    structured_results = evaluate_structured_diagnostics()
    sensitive_results = evaluate_sensitive_diagnostics()
    results: list[dict[str, Any]] = [
        *structured_results,
        *sensitive_results,
    ]
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
