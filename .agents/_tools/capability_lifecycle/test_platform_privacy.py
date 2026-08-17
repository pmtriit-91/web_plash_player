#!/usr/bin/env python3
"""Eight focused checks for capability-lifecycle platform privacy."""

from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
privacy = importlib.import_module("capability_lifecycle.platform_privacy")
FUNCTIONS = ("windows_dpapi", "usage_receipt_errors", "recent_jsonl_lines")
CONSTANTS = ("SAFE_ID", "PLAN_ID", "SHA256", "USAGE_CONFIDENCE", "USAGE_OUTCOMES", "USAGE_MAX_EVIDENCE_ITEMS", "USAGE_MAX_STORED_RECEIPT_BYTES", "TELEMETRY_KEY_DPAPI_ENTROPY", "USAGE_RECEIPT_FIELDS")  # fmt: skip
EXPECTED_AST = "ae23684562bb53ac7723b79aaadb4050bf8bc296b5824165f8d0e85a04976a65"


def valid_receipt() -> dict[str, Any]:
    receipt = {
        "schema_version": 2,
        "receipt_id": "0" * 24,
        "capability_id": "standard_feature",
        "capability_version": "1.0.0",
        "router_version": "9.1.0",
        "task_hash": "1" * 64,
        "task_hash_algorithm": "hmac-sha256-v2",
        "selected_at": "2026-08-07T03:45:28Z",
        "confidence": "high",
        "evidence_hashes": ["2" * 64],
        "evidence_hash_algorithm": "hmac-sha256-v2",
        "outcome": "completed",
        "raw_prompt_stored": False,
        "raw_evidence_stored": False,
    }
    receipt["content_sha256"] = facade.receipt_hash(receipt)
    return receipt


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    tree = ast.parse(Path(privacy.__file__).read_text(encoding="utf-8"))
    nodes = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    selected = [nodes[name] for name in FUNCTIONS]
    digest = hashlib.sha256(
        "\n".join(
            ast.dump(node, include_attributes=False) for node in selected
        ).encode()
    ).hexdigest()
    check(
        "exact-family-ast-and-lines",
        digest == EXPECTED_AST
        and sum(node.end_lineno - node.lineno + 1 for node in selected) == 173,
    )
    check(
        "facade-directly-reexports-identities-and-signatures",
        all(
            getattr(facade, name) is getattr(privacy, name)
            for name in FUNCTIONS + CONSTANTS
        )
        and all(
            inspect.signature(getattr(facade, name))
            == inspect.signature(getattr(privacy, name))
            for name in FUNCTIONS
        ),
    )
    original_os = privacy.os
    privacy.os = SimpleNamespace(name="posix", SEEK_END=os.SEEK_END)
    diagnostics: list[str] = []
    try:
        non_windows = privacy.windows_dpapi(
            b"secret", protect=True, diagnostics=diagnostics
        )
    finally:
        privacy.os = original_os
    check("non-windows-dpapi-never-protects", non_windows is None and diagnostics == [])
    original_import = builtins.__import__
    privacy.os = SimpleNamespace(name="nt", SEEK_END=os.SEEK_END)
    builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError("blocked")) if name == "ctypes" else original_import(name, *args, **kwargs)  # type: ignore[assignment]  # fmt: skip
    diagnostics = []
    try:
        failed = privacy.windows_dpapi(b"secret", protect=True, diagnostics=diagnostics)
    finally:
        builtins.__import__ = original_import
        privacy.os = original_os
    check(
        "windows-ffi-failure-is-diagnostic-and-closed",
        failed is None and diagnostics == ["DPAPI_PROTECT_EXCEPTION_ImportError"],
    )
    receipt = valid_receipt()
    check("exact-v2-receipt-is-accepted", privacy.usage_receipt_errors(receipt) == [])
    tampered = deepcopy(receipt)
    tampered["outcome"] = "failed"
    unsafe = deepcopy(receipt)
    unsafe["evidence"] = ["raw"]
    check(
        "tampered-and-raw-bearing-receipts-are-rejected",
        "USAGE_CONTENT_HASH_MISMATCH" in privacy.usage_receipt_errors(tampered)
        and "USAGE_RECEIPT_FIELDS_INVALID" in privacy.usage_receipt_errors(unsafe),
    )
    with tempfile.TemporaryDirectory(
        prefix="capability-platform-privacy-"
    ) as directory:
        log = Path(directory) / "usage.jsonl"
        log.write_bytes(b"x" * 9000 + b"\nfirst\nsecond\nthird\n")
        check(
            "jsonl-tail-is-byte-record-and-error-bounded",
            privacy.recent_jsonl_lines(log, 2) == [b"second", b"third"]
            and privacy.recent_jsonl_lines(log, 0) == []
            and privacy.recent_jsonl_lines(log.parent / "missing", 2) == [],
        )
    topology = json.loads(
        (TOOLS_ROOT / "capability_lifecycle/topology.json").read_text()
    )
    owner_source = Path(privacy.__file__).read_text(encoding="utf-8")
    entry = next(
        (
            item
            for item in topology["entries"]
            if item.get("entrypoint", "").endswith("platform_privacy.py")
        ),
        {},
    )
    check(
        "topology-is-one-way-and-discoverable",
        entry.get("depends_on") == ["_tools/capability_lifecycle/shared.py"]
        and "agent_os_capability_lifecycle" not in owner_source,
    )
    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
