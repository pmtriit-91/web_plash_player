#!/usr/bin/env python3
"""First ten static candidate-corpus acceptance cases."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_research import inspect_candidate, validate_candidate
from capability_research.test_support import (
    CANDIDATE_SHARD_SIZE,
    CORPUS,
    materialize,
    namespace,
)


def main() -> None:
    document = json.loads(CORPUS.read_text(encoding="utf-8"))
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-research-") as temporary:
        root = Path(temporary)
        (root / "outside.md").write_text("outside snapshot", encoding="utf-8")
        for case in document.get("cases", [])[:CANDIDATE_SHARD_SIZE]:
            source = root / case["id"]
            source.mkdir()
            materialize(case, source)
            inspected = inspect_candidate(namespace(case, source))
            candidate = inspected.get("candidate", {})
            passed = bool(
                inspected.get("ok") is True
                and inspected.get("zero_execution") is True
                and candidate.get("state") == case["expected_state"]
                and candidate.get("recommendation") == case["expected_recommendation"]
                and not validate_candidate(candidate)
                and not (source / "scripts" / "EXECUTED").exists()
            )
            results.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "actual_state": candidate.get("state"),
                    "actual_recommendation": candidate.get("recommendation"),
                }
            )

    passed = sum(1 for result in results if result.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
