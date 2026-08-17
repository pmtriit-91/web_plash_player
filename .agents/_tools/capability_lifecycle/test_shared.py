#!/usr/bin/env python3
"""Eight focused checks for capability-lifecycle shared foundations."""

from __future__ import annotations

import importlib
import inspect
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
shared = importlib.import_module("capability_lifecycle.shared")
HELPERS = (
    "utc_now",
    "iso_time",
    "parse_time",
    "sha256_bytes",
    "canonical_hash",
    "load_json",
    "json_bytes",
    "atomic_bytes",
    "atomic_json",
    "encoded",
    "decoded",
    "safe_relative",
    "receipt_hash",
    "receipt_valid",
)
CONSTANTS = ("DEFAULT_ROOT", "REGISTRY", "DESCRIPTORS", "CAPABILITY_DECISIONS", "LIFECYCLE_LEDGER", "CANDIDATES", "RESEARCH_DECISIONS", "VENDOR_LOCK", "ROUTING_CORPUS", "MANIFEST", "CONTROL_DOCUMENTS")  # fmt: skip


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    check(
        "facade-reexports-exact-foundation-identities",
        all(
            getattr(facade, name) is getattr(shared, name)
            for name in HELPERS + CONSTANTS
        ),
    )
    check(
        "service-retains-public-signature-and-base",
        issubclass(facade.CapabilityLifecycleService, shared.CapabilityLifecycleBase)
        and inspect.signature(facade.CapabilityLifecycleService)
        == inspect.signature(shared.CapabilityLifecycleBase),
    )
    instant = datetime(2026, 8, 7, 1, 2, 3, tzinfo=timezone.utc)
    receipt = {"id": "r1"}
    receipt["content_sha256"] = shared.receipt_hash(receipt)
    check(
        "time-hash-and-receipt-contracts",
        shared.parse_time(shared.iso_time(instant)) == instant
        and len(shared.sha256_bytes(b"x")) == 64
        and shared.receipt_valid(receipt),
    )
    with tempfile.TemporaryDirectory(prefix="capability-shared-") as temporary:
        root = Path(temporary) / ".agents"
        root.mkdir()
        value_path = root / "state" / "value.json"
        shared.atomic_json(value_path, {"value": shared.encoded(b"bytes")})
        check(
            "atomic-json-and-base64-roundtrip",
            shared.decoded(shared.load_json(value_path, {})["value"]) == b"bytes",
        )
        service = facade.CapabilityLifecycleService(root, now=lambda: instant)
        check(
            "safe-path-accepts-local-and-blocks-traversal",
            service.path("state/value.json") == value_path.resolve()
            and raises(ValueError, service.path, "../escape"),
        )
        (root / "project").mkdir()
        (root / "project" / "state.txt").write_text("one", encoding="utf-8")
        digest = service.protected_digest()
        (root / "project" / "state.txt").write_text("two", encoding="utf-8")
        check("protected-digest-tracks-bytes", digest != service.protected_digest())
        service.persist_runtime_candidate({"id": "c1", "source": {"commit": "abc"}})
        service.persist_runtime_decision({"id": "d1"})
        service.persist_runtime_decision({"id": "d1"})
        check(
            "runtime-record-persistence-is-stable",
            len(service.runtime_candidate_records()) == 1
            and len(service.runtime_decision_records()) == 1,
        )
        policy = {
            "manifest_self": "_manifest/base-release-manifest.json",
            "application_owned_scopes": ["project/**"],
            "runtime_scopes": ["_runtime/**"],
            "release_owned_roots": ["routing"],
        }
        shared.atomic_json(root / "core/contracts/ownership-policy.json", policy)
        index = shared.load_json(TOOLS_ROOT / "module-topology-index.json", {})
        topology = shared.load_json(
            TOOLS_ROOT / "capability_lifecycle/topology.json", {}
        )
        check(
            "ownership-documents-and-topology-remain-live",
            service.owner("project/state.txt") == "application"
            and service.owner("routing/x.json") == "release"
            and set(service.base_documents())
            == set(shared.CONTROL_DOCUMENTS) - {shared.MANIFEST}
            and any(
                item.get("domain") == "capability-lifecycle"
                for item in index["domains"]
            )
            and topology.get("public_facade")
            == "_tools/agent_os_capability_lifecycle.py",
        )
    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


def raises(error: type[Exception], function: Any, *arguments: Any) -> bool:
    try:
        function(*arguments)
    except error:
        return True
    return False


if __name__ == "__main__":
    main()
