#!/usr/bin/env python3
"""BR3d0 focused shard for the deep-doctor receipt contract."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

from context_memory import deep_receipt

NOW, HEAD, HANDOFF, LEDGER = (
    datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
    "a" * 40,
    "b" * 64,
    "c" * 64,
)
SUMMARY = {field: 0 for field in deep_receipt.SUMMARY_FIELDS}
VERDICT = {"errors": [], "warnings": [], "summary": SUMMARY}


def receipt(**changes: object) -> dict[str, object]:
    arguments = {
        "project_id": "universal-agent-os",
        "head": HEAD,
        "handoff_tree_sha256": HANDOFF,
        "task_ledger_tree_sha256": LEDGER,
        "created_at": "2026-08-03T12:00:00Z",
        "expires_at": "2026-08-03T12:05:00Z",
        "verdict": VERDICT,
    }
    arguments.update(changes)
    return deep_receipt.build_receipt(**arguments)  # type: ignore[arg-type]


def valid(value: object, **changes: object) -> object:
    arguments = {
        "project_id": "universal-agent-os",
        "head": HEAD,
        "handoff_tree_sha256": HANDOFF,
        "task_ledger_tree_sha256": LEDGER,
        "now": NOW,
    }
    arguments.update(changes)
    return deep_receipt.validate_receipt(value, **arguments)  # type: ignore[arg-type]


def case_valid_detached() -> bool:
    value = receipt()
    result = valid(value)
    return result == VERDICT and result is not value["verdict"]


def case_all_bindings() -> bool:
    changes = [
        {"head": "d" * 40},
        {"handoff_tree_sha256": "d" * 64},
        {"task_ledger_tree_sha256": "d" * 64},
        {"project_id": "foreign"},
    ]
    return all(valid(receipt(), **change) is None for change in changes)


def case_expiry_and_ttl() -> bool:
    expired = (
        valid(receipt(), now=datetime(2026, 8, 3, 12, 5, tzinfo=timezone.utc)) is None
    )
    try:
        receipt(expires_at="2026-08-03T12:05:01Z")
    except ValueError:
        return expired
    return False


def case_tamper_and_fields() -> bool:
    tampered = receipt()
    tampered["verdict"] = {**VERDICT, "warnings": [{"code": "changed"}]}
    extra = {**receipt(), "extra": True}
    return valid(tampered) is None and valid(extra) is None


def case_verdict_privacy_and_shape() -> bool:
    invalid = {"errors": [], "warnings": [], "summary": {}}
    private = {"errors": [{"conversation": "raw"}], "warnings": [], "summary": SUMMARY}
    for verdict in (invalid, private):
        try:
            receipt(verdict=verdict)
        except ValueError:
            continue
        return False
    return True


CASES = [
    ("valid-detached", case_valid_detached),
    ("all-bindings", case_all_bindings),
    ("expiry-ttl", case_expiry_and_ttl),
    ("tamper-fields", case_tamper_and_fields),
    ("verdict-privacy-shape", case_verdict_privacy_and_shape),
]


def main() -> None:
    results = []
    for name, check in CASES:
        try:
            passed, error = bool(check()), None
        except Exception as exc:  # noqa: BLE001 - bounded case diagnostics
            passed, error = False, str(exc)
        results.append(
            {"id": name, "passed": passed, **({"error": error} if error else {})}
        )
    output = {
        "ok": all(item["passed"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
