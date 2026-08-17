#!/usr/bin/env python3
"""Eight focused checks for capability-lifecycle telemetry extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
owner = importlib.import_module("capability_lifecycle.telemetry")
base = importlib.import_module("capability_lifecycle.shared")

# fmt: off
METHODS = ("telemetry_key", "telemetry_hmac", "append_usage_receipt", "record_usage", "usage_review", "queue")
CONSTANTS = ("USAGE_MAX_TASK_BYTES", "USAGE_MAX_EVIDENCE_BYTES", "TELEMETRY_KEY_BYTES", "TELEMETRY_KEY_DPAPI_PREFIX")
EXPECTED_AST = "ff53f1703fb48fd16248118c6bd0c16db0e7ffd6a346d709f467e9cd3d1c3dae"
NOW = datetime(2026, 8, 7, 9, 30, tzinfo=timezone.utc)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def fixture(parent: Path, name: str) -> Any:
    root = parent / name / ".agents"
    write_json(root / facade.DESCRIPTORS, {"capabilities": [{"id": "standard_feature", "version": "1.0.0"}]})
    write_json(root / facade.REGISTRY, {"version": "9.1.0"})
    return facade.CapabilityLifecycleService(root, now=lambda: NOW)


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8"))
    mixin = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "TelemetryMixin")
    nodes = {node.name: node for node in mixin.body if isinstance(node, ast.FunctionDef)}
    selected = [nodes[name] for name in METHODS]
    digest = hashlib.sha256("\n".join(ast.dump(node, include_attributes=False) for node in selected).encode()).hexdigest()
    check("exact-family-ast-and-lines", digest == EXPECTED_AST and sum(node.end_lineno - node.lineno + 1 for node in selected) == 205)
    service_class = facade.CapabilityLifecycleService
    check(
        "facade-reexports-owner-with-stable-constructor",
        all(getattr(service_class, name) is getattr(owner.TelemetryMixin, name) for name in METHODS)
        and all(getattr(facade, name) is getattr(owner, name) for name in CONSTANTS)
        and service_class.__mro__[-3:-1] == (owner.TelemetryMixin, base.CapabilityLifecycleBase)
        and inspect.signature(service_class) == inspect.signature(base.CapabilityLifecycleBase),
    )
    key = b"k" * 32
    check(
        "hmac-is-deterministic-and-domain-separated",
        owner.TelemetryMixin.telemetry_hmac(key, b"task", b"value") == owner.TelemetryMixin.telemetry_hmac(key, b"task", b"value")
        and owner.TelemetryMixin.telemetry_hmac(key, b"task", b"value") != owner.TelemetryMixin.telemetry_hmac(key, b"evidence", b"value"),
    )
    with tempfile.TemporaryDirectory(prefix="capability-telemetry-") as directory:
        root = Path(directory)
        service = fixture(root, "primary")
        generated = service.telemetry_key()
        corrupt = fixture(root, "corrupt")
        corrupt.telemetry_salt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.telemetry_salt.write_bytes(b"short")
        check(
            "key-storage-is-bounded-and-corruption-fails-closed",
            bool(generated and len(generated) == 32 and service.telemetry_key() == generated)
            and (os.name == "nt" or stat.S_IMODE(service.telemetry_salt.stat().st_mode) == 0o600)
            and corrupt.telemetry_key() is None,
        )
        task, evidence = "private-task", "private-evidence"
        recorded = service.record_usage("standard_feature", task, "high", [evidence, evidence], "completed")
        receipt = recorded.get("receipt", {})
        raw = service.telemetry.read_text(encoding="utf-8")
        check(
            "receipt-is-raw-free-keyed-and-deduplicated",
            recorded.get("ok") is True and task not in raw and evidence not in raw
            and len(receipt.get("evidence_hashes", [])) == 1 and not facade.usage_receipt_errors(receipt),
        )
        before = service.telemetry.read_bytes()
        rejected = [
            service.record_usage("standard_feature", "", "high", [], "completed"),
            service.record_usage("standard_feature", "task", "high", ["x" * 4097], "completed"),
        ]
        check("invalid-or-unbounded-input-is-zero-write", all(item.get("ok") is False for item in rejected) and service.telemetry.read_bytes() == before)
        service.telemetry.write_text(raw + "not-json\n" + json.dumps({"schema_version": 1, "evidence": ["raw"]}) + "\n", encoding="utf-8")
        review = service.usage_review()
        summary = next(item for item in review["summary"] if item["capability_id"] == "standard_feature")
        check(
            "review-isolates-malformed-and-unsafe-records",
            review["malformed_records_ignored"] == 2 and review["privacy_unsafe_records_ignored"] == 1
            and summary["observations"] == 1 and review["raw_prompts_stored"] is False,
        )
        write_json(service.plans / "one.json", {"plan": 1})
        write_json(service.receipts / "one.json", {"receipt": 1})
        service.journal.parent.mkdir(parents=True, exist_ok=True)
        service.journal.write_text("{}", encoding="utf-8")
        queued = service.queue()
        topology = json.loads((TOOLS_ROOT / "capability_lifecycle/topology.json").read_text())
        entry = next((item for item in topology["entries"] if item.get("entrypoint", "").endswith("telemetry.py")), {})
        check(
            "queue-and-one-way-topology-remain-discoverable",
            queued == {"ok": True, "plans": [{"plan": 1}], "receipts": [{"receipt": 1}], "recovery_required": True}
            and entry.get("depends_on") == ["_tools/capability_lifecycle/platform_privacy.py", "_tools/capability_lifecycle/shared.py"]
            and "agent_os_capability_lifecycle" not in Path(owner.__file__).read_text(),
        )
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(item["passed"] for item in cases), "total": len(cases), "cases": cases}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
# fmt: on
