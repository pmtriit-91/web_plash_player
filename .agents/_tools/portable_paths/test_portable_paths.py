#!/usr/bin/env python3
"""Canonical cross-platform path safety aggregate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from portable_paths.test_filesystem_checkout import evaluate_filesystem_checkout
from portable_paths.test_lexical_policy import evaluate_portable_lexical_policy


def main() -> None:
    results = evaluate_portable_lexical_policy()
    results.extend(evaluate_filesystem_checkout())
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
