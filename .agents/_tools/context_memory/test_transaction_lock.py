#!/usr/bin/env python3
"""Focused Context Memory adoption checks for the shared transaction lock."""

from __future__ import annotations

import json
import os
import runpy
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

from agent_os_context_memory import (
    HOT_REL,
    ContextMemoryService,
)

SUPPORT = runpy.run_path(str(ROOT / "_tools" / "test-context-memory.py"))
fixture = cast(Callable[[Path], ContextMemoryService], SUPPORT["fixture"])
initialize = cast(Callable[[ContextMemoryService], None], SUPPORT["initialize"])
proposal = cast(
    Callable[[str, str, str, str], dict[str, Any]], SUPPORT["evidence_proposal"]
)


def plan(service: ContextMemoryService, identifier: str) -> dict[str, Any]:
    planned = service.plan_upsert(
        proposal(identifier, "hot", "guardrail", "user-confirmed")
    )
    if not planned.get("ok"):
        raise RuntimeError(planned)
    return planned["plan"]


def contains(service: ContextMemoryService, identifier: str) -> bool:
    return any(
        item.get("id") == identifier
        for item in service.document(HOT_REL, {"records": []})["records"]
    )


def receipts(service: ContextMemoryService) -> set[str]:
    return {item.name for item in service.receipts.glob("*.json") if item.is_file()}


def case_stable_lock_retained(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    metadata = json.loads(service.lock_path.read_text(encoding="utf-8"))
    return bool(
        service.lock_path.is_file()
        and metadata.get("format") == "agent-os-transaction-lock-v1"
        and metadata.get("owner") == "context-memory-apply"
    )


def case_normal_apply_reacquires(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    result = service.apply(plan(service, "normal-reacquire")["plan_id"], True)
    return bool(result.get("ok") and contains(service, "normal-reacquire"))


def case_live_owner_excluded(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    pending = plan(service, "live-owner-blocked")
    before = receipts(service)
    held = service.acquire_lock()
    try:
        result = service.apply(pending["plan_id"], True)
    finally:
        service.release_lock(held)
    return bool(
        result.get("reason_codes") == ["TRANSACTION_BUSY", "TRANSACTION_LOCK_BUSY"]
        and not contains(service, "live-owner-blocked")
        and receipts(service) == before
    )


def case_legacy_empty_fails_closed(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    pending = plan(service, "legacy-empty-blocked")
    before = receipts(service)
    service.lock_path.write_bytes(b"")
    result = service.apply(pending["plan_id"], True)
    return bool(
        result.get("reason_codes") == ["TRANSACTION_LOCK_LEGACY_UNVERIFIED"]
        and not contains(service, "legacy-empty-blocked")
        and receipts(service) == before
    )


def case_corrupt_metadata_fails_closed(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    pending = plan(service, "corrupt-metadata-blocked")
    before = receipts(service)
    service.lock_path.write_text("not-json\n", encoding="utf-8")
    result = service.apply(pending["plan_id"], True)
    return bool(
        result.get("reason_codes") == ["TRANSACTION_LOCK_LEGACY_UNVERIFIED"]
        and not contains(service, "corrupt-metadata-blocked")
        and receipts(service) == before
    )


def case_rollback_releases_kernel_lock(base: Path) -> bool:
    service = fixture(base)
    initialize(service)
    failed_plan = plan(service, "injected-failure")
    os.environ["AGENT_OS_TEST_MODE"] = "1"
    try:
        failed = service.apply(failed_plan["plan_id"], True, test_fail_after=1)
    finally:
        os.environ.pop("AGENT_OS_TEST_MODE", None)
    recovered = service.apply(plan(service, "after-rollback")["plan_id"], True)
    return bool(
        failed.get("reason_codes") == ["MEMORY_APPLY_FAILED_ROLLED_BACK"]
        and recovered.get("ok")
        and contains(service, "after-rollback")
        and service.lock_path.is_file()
    )


CASES = [
    ("stable-lock-retained", case_stable_lock_retained),
    ("normal-apply-reacquires", case_normal_apply_reacquires),
    ("live-owner-excluded", case_live_owner_excluded),
    ("legacy-empty-fails-closed", case_legacy_empty_fails_closed),
    ("corrupt-metadata-fails-closed", case_corrupt_metadata_fails_closed),
    ("rollback-releases-kernel-lock", case_rollback_releases_kernel_lock),
]


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="agent-os-context-memory-transaction-lock-"
    ) as temporary:
        root = Path(temporary)
        for index, (identifier, check) in enumerate(CASES):
            try:
                passed = bool(check(root / f"{index:02d}-{identifier}"))
                results.append({"id": identifier, "passed": passed})
            except Exception as error:  # noqa: BLE001 - report isolated case failure
                results.append(
                    {
                        "id": identifier,
                        "passed": False,
                        "error": f"{error.__class__.__name__}: {error}",
                    }
                )
    passed = sum(1 for item in results if item["passed"])
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
