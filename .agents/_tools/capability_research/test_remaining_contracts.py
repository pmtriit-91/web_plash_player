#!/usr/bin/env python3
"""Remaining candidate, connector, transition, and receipt contracts."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_research import (
    inspect_candidate,
    normalized_receipt_hash,
    status,
    validate_candidate,
)
from capability_research.test_support import (
    CANDIDATE_SHARD_SIZE,
    CORPUS,
    FULL_COMMIT,
    materialize,
    namespace,
)


def main() -> None:
    document = json.loads(CORPUS.read_text(encoding="utf-8"))
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-research-") as temporary:
        root = Path(temporary)
        (root / "outside.md").write_text("outside snapshot", encoding="utf-8")
        for case in document.get("cases", [])[CANDIDATE_SHARD_SIZE:]:
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

    connector_status = status()
    results.append(
        {
            "id": "optional-connectors-never-block-boot",
            "passed": bool(
                connector_status.get("ok")
                and connector_status.get("boot_dependency") is False
                and connector_status.get("network_contacted") is False
                and all(item.get("failure_mode") == "isolated" for item in connector_status.get("connector_health", []))
            ),
        }
    )

    invalid_transition = {
        "schema_version": 1,
        "id": "invalid-transition",
        "state": "active",
        "source": {"commit": FULL_COMMIT},
        "decision_history": [
            {"state": "discovered"},
            {"state": "active"},
        ],
    }
    transition_errors = validate_candidate(invalid_transition)
    results.append(
        {
            "id": "invalid-state-transition-rejected",
            "passed": any(item.get("code") == "CANDIDATE_TRANSITION_INVALID" for item in transition_errors),
        }
    )

    receipt = {
        "id": "receipt-1",
        "candidate_id": "safe-markdown-skill",
        "capability_ids": ["api-contract-review"],
        "decided_at": "2026-07-19T00:00:00Z",
        "decision": "vendor-pin",
        "evidence": ["static-gates-pass"],
        "rationale": "All hard gates and shadow routing passed.",
        "constraints": ["human activation approval required"],
        "supersedes": None,
    }
    receipt["content_sha256"] = normalized_receipt_hash(receipt)
    valid_hash = receipt["content_sha256"] == normalized_receipt_hash(receipt)
    receipt["rationale"] = "tampered"
    results.append(
        {
            "id": "decision-receipt-tamper-evident",
            "passed": valid_hash and receipt["content_sha256"] != normalized_receipt_hash(receipt),
        }
    )

    passed = sum(1 for result in results if result.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
