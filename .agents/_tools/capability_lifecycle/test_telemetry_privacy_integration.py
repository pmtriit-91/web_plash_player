#!/usr/bin/env python3
"""Adversarial privacy checks for activation telemetry receipt v2."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

import agent_os_domain
from agent_os_capability_lifecycle import (
    DESCRIPTORS,
    REGISTRY,
    TELEMETRY_KEY_DPAPI_PREFIX,
    CapabilityLifecycleService,
    receipt_hash,
    recent_jsonl_lines,
    usage_receipt_errors,
    windows_dpapi,
)

NOW = datetime(2026, 7, 23, 9, 30, tzinfo=timezone.utc)
TASK_MARKER = "crf03-private-task-marker"
EVIDENCE_MARKER = "crf03-private-evidence-marker"
SECRET_MARKER = "token=crf03-secret-marker"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture(parent: Path, name: str) -> CapabilityLifecycleService:
    root = parent / name / ".agents"
    write_json(
        root / DESCRIPTORS,
        {
            "schema_version": 1,
            "agent_os_version": "9.1.0",
            "capabilities": [{"id": "standard_feature", "version": "1.0.0"}],
        },
    )
    write_json(root / REGISTRY, {"version": "9.1.0", "capabilities": {}})
    return CapabilityLifecycleService(root, now=lambda: NOW)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def legacy_receipt() -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "receipt_id": "0" * 24,
        "capability_id": "standard_feature",
        "capability_version": "1.0.0",
        "router_version": "9.1.0",
        "task_hash": "1" * 64,
        "task_hash_algorithm": "hmac-sha256",
        "selected_at": "2026-07-23T09:30:00Z",
        "confidence": "high",
        "evidence": [EVIDENCE_MARKER],
        "outcome": "completed",
        "raw_prompt_stored": False,
    }
    value["content_sha256"] = receipt_hash(value)
    return value


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-telemetry-privacy-") as directory:
        base = Path(directory)
        if os.name == "nt":
            dpapi_diagnostics: list[str] = []
            dpapi_probe = b"agent-os-dpapi-roundtrip-probe"
            protected_probe = windows_dpapi(
                dpapi_probe,
                protect=True,
                diagnostics=dpapi_diagnostics,
            )
            recovered_probe = (
                windows_dpapi(
                    protected_probe,
                    protect=False,
                    diagnostics=dpapi_diagnostics,
                )
                if protected_probe is not None
                else None
            )
            results.append(
                {
                    "id": "windows-dpapi-roundtrip",
                    "passed": recovered_probe == dpapi_probe,
                    "error": ",".join(dpapi_diagnostics) if dpapi_diagnostics else None,
                }
            )
        service = fixture(base, "primary")
        recorded = service.record_usage(
            "standard_feature",
            TASK_MARKER,
            "high",
            [EVIDENCE_MARKER, SECRET_MARKER],
            "completed",
        )
        receipt = recorded.get("receipt", {})
        raw_log = (
            service.telemetry.read_text(encoding="utf-8")
            if service.telemetry.is_file()
            else ""
        )
        results.append(
            {
                "id": "raw-input-never-persists",
                "error": ",".join(recorded.get("reason_codes", []))
                if recorded.get("ok") is not True
                else None,
                "passed": bool(
                    recorded.get("ok")
                    and TASK_MARKER not in raw_log
                    and EVIDENCE_MARKER not in raw_log
                    and SECRET_MARKER not in raw_log
                    and receipt.get("schema_version") == 2
                    and receipt.get("raw_prompt_stored") is False
                    and receipt.get("raw_evidence_stored") is False
                    and "evidence" not in receipt
                    and not usage_receipt_errors(receipt)
                ),
            }
        )

        key = service.telemetry_key()
        stored_key = (
            service.telemetry_salt.read_bytes()
            if service.telemetry_salt.is_file()
            else b""
        )
        expected_evidence = [
            service.telemetry_hmac(key or b"", b"evidence", EVIDENCE_MARKER.encode("utf-8")),
            service.telemetry_hmac(key or b"", b"evidence", SECRET_MARKER.encode("utf-8")),
        ]
        platform_key_protected = (
            stored_key.startswith(TELEMETRY_KEY_DPAPI_PREFIX)
            and stored_key != key
            and service.telemetry_key() == key
        ) if os.name == "nt" else stat.S_IMODE(service.telemetry_salt.stat().st_mode) == 0o600
        results.append(
            {
                "id": "hashes-are-keyed-and-domain-separated",
                "passed": bool(
                    key
                    and receipt.get("evidence_hashes") == expected_evidence
                    and receipt.get("task_hash") == service.telemetry_hmac(key, b"task", TASK_MARKER.encode("utf-8"))
                    and service.telemetry_hmac(key, b"task", EVIDENCE_MARKER.encode("utf-8")) != expected_evidence[0]
                    and platform_key_protected
                ),
            }
        )

        before_rejections = (
            service.telemetry.read_bytes()
            if service.telemetry.is_file()
            else b""
        )
        rejected = [
            service.record_usage("standard_feature", "", "high", [], "completed"),
            service.record_usage("standard_feature", "task", "high", ["x"] * 9, "completed"),
            service.record_usage("standard_feature", "task", "high", ["x" * 4097], "completed"),
            service.record_usage("standard_feature", "task", "high", [object()], "completed"),  # type: ignore[list-item]
            service.record_usage("standard_feature", "\ud800", "high", [], "completed"),
        ]
        results.append(
            {
                "id": "unbounded-or-invalid-input-is-rejected-before-write",
                "passed": all(item.get("ok") is False for item in rejected)
                and (
                    service.telemetry.read_bytes()
                    if service.telemetry.is_file()
                    else b""
                )
                == before_rejections,
            }
        )

        corrupt_service = fixture(base, "corrupt-key")
        corrupt_service.telemetry_salt.parent.mkdir(parents=True, exist_ok=True)
        corrupt_service.telemetry_salt.write_bytes(b"short")
        corrupt_result = corrupt_service.record_usage("standard_feature", "task", "high", [], "completed")
        results.append(
            {
                "id": "corrupt-hmac-key-fails-closed",
                "passed": corrupt_result.get("reason_codes") == ["USAGE_TELEMETRY_KEY_INVALID"]
                and not corrupt_service.telemetry.exists(),
            }
        )

        legacy_key_service = fixture(base, "legacy-key")
        legacy_key_service.telemetry_salt.parent.mkdir(parents=True, exist_ok=True)
        legacy_key = b"k" * 32
        legacy_key_service.telemetry_salt.write_bytes(legacy_key)
        if os.name != "nt":
            os.chmod(legacy_key_service.telemetry_salt, 0o644)
        migrated_key = legacy_key_service.telemetry_key()
        migrated_storage = legacy_key_service.telemetry_salt.read_bytes()
        results.append(
            {
                "id": "existing-key-is-upgraded-to-platform-protection",
                "passed": bool(
                    migrated_key == legacy_key
                    and (
                        (
                            migrated_storage.startswith(TELEMETRY_KEY_DPAPI_PREFIX)
                            and migrated_storage != legacy_key
                        )
                        if os.name == "nt"
                        else stat.S_IMODE(legacy_key_service.telemetry_salt.stat().st_mode) == 0o600
                    )
                ),
            }
        )

        legacy = legacy_receipt()
        append_jsonl(service.telemetry, legacy)
        tampered = deepcopy(receipt)
        tampered["outcome"] = "failed"
        append_jsonl(service.telemetry, tampered)
        review = service.usage_review()
        summary = next(item for item in review["summary"] if item["capability_id"] == "standard_feature")
        results.append(
            {
                "id": "legacy-and-tampered-receipts-are-isolated",
                "passed": bool(
                    review.get("malformed_records_ignored") == 2
                    and review.get("privacy_unsafe_records_ignored") == 1
                    and summary.get("observations") == 1
                    and review.get("raw_prompts_stored") is False
                    and review.get("raw_evidence_stored") is False
                ),
            }
        )

        original_log = agent_os_domain.ACTIVATION_LOG
        try:
            agent_os_domain.ACTIVATION_LOG = service.telemetry
            history = agent_os_domain.activation_history()
        finally:
            agent_os_domain.ACTIVATION_LOG = original_log
        projected = json.dumps(history, ensure_ascii=False, sort_keys=True)
        records = history.get("standard_feature", [])
        results.append(
            {
                "id": "read-surface-exposes-only-validated-hashes",
                "passed": bool(
                    len(records) == 1
                    and "evidence_hashes" in records[0]
                    and "evidence" not in records[0]
                    and EVIDENCE_MARKER not in projected
                    and SECRET_MARKER not in projected
                ),
            }
        )

        extra_field = deepcopy(receipt)
        extra_field["debug"] = SECRET_MARKER
        extra_field["content_sha256"] = receipt_hash(extra_field)
        wrong_hash_type = deepcopy(receipt)
        wrong_hash_type["evidence_hashes"] = [{"not": "a hash"}]
        results.append(
            {
                "id": "runtime-validator-enforces-exact-v2-schema",
                "passed": bool(
                    "USAGE_RECEIPT_FIELDS_INVALID" in usage_receipt_errors(extra_field)
                    and "USAGE_RECEIPT_SCHEMA_UNSAFE" in usage_receipt_errors(legacy)
                    and "USAGE_EVIDENCE_HASHES_INVALID" in usage_receipt_errors(wrong_hash_type)
                ),
            }
        )

        duplicate = service.record_usage(
            "standard_feature",
            "duplicate-evidence-task",
            "medium",
            ["same-signal", "same-signal"],
            "selected",
        )
        results.append(
            {
                "id": "duplicate-signals-have-one-bounded-hash",
                "passed": bool(
                    duplicate.get("ok")
                    and len(duplicate.get("receipt", {}).get("evidence_hashes", [])) == 1
                    and not usage_receipt_errors(duplicate.get("receipt"))
                ),
            }
        )

        bounded_log = base / "bounded-tail.jsonl"
        bounded_log.write_bytes(b"x" * 9000 + b"\nfirst\nsecond\nthird\n")
        results.append(
            {
                "id": "jsonl-tail-is-byte-and-record-bounded",
                "passed": recent_jsonl_lines(bounded_log, 2) == [b"second", b"third"],
            }
        )

    passed = sum(1 for item in results if item.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
