#!/usr/bin/env python3
"""Eight focused checks for transaction-engine extraction."""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_capability_lifecycle")
owner = importlib.import_module("capability_lifecycle.transaction_engine")
planning = importlib.import_module("capability_lifecycle.state_planning")
integration = importlib.import_module("capability_lifecycle.integration_builder")
manifest = importlib.import_module("capability_lifecycle.manifest_builder")
candidate = importlib.import_module("capability_lifecycle.candidate_validation")
telemetry = importlib.import_module("capability_lifecycle.telemetry")
base = importlib.import_module("capability_lifecycle.shared")

# fmt: off
METHODS = ("acquire_lock", "release_lock", "restore_changes", "write_after_changes", "verify_changes", "apply", "recover", "plan_rollback")
EXPECTED_AST = "aeb5b0077cb5f2b594cc0fba4039e1f77f751be7c732ba73358b6b9ff98901b1"


def change(path: str, before: bytes | None, after: bytes | None) -> dict[str, object]:
    return {"path": path, "before_base64": facade.encoded(before), "after_base64": facade.encoded(after), "before_sha256": facade.sha256_bytes(before) if before is not None else None, "after_sha256": facade.sha256_bytes(after) if after is not None else None}


def main() -> None:
    cases: list[dict[str, object]] = []; check = lambda identifier, passed: cases.append({"id": identifier, "passed": bool(passed)})
    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8")); mixin = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "TransactionEngineMixin")
    nodes = {node.name: node for node in mixin.body if isinstance(node, ast.FunctionDef)}; selected = [nodes[name] for name in METHODS]
    digest = hashlib.sha256("\n".join(ast.dump(node, include_attributes=False) for node in selected).encode()).hexdigest()
    check("exact-family-ast-and-lines", digest == EXPECTED_AST and sum(node.end_lineno - node.lineno + 1 for node in selected) == 274)
    service_class = facade.CapabilityLifecycleService
    expected_mro = (owner.TransactionEngineMixin, planning.StatePlanningMixin, integration.IntegrationBuilderMixin, manifest.ManifestBuilderMixin, candidate.CandidateValidationMixin, telemetry.TelemetryMixin, base.CapabilityLifecycleBase)
    check("facade-identity-mro-and-constructor", all(getattr(service_class, name) is getattr(owner.TransactionEngineMixin, name) for name in METHODS) and service_class.__mro__[1:8] == expected_mro and inspect.signature(service_class) == inspect.signature(base.CapabilityLifecycleBase))
    with tempfile.TemporaryDirectory(prefix="transaction-engine-") as directory:
        service = facade.CapabilityLifecycleService(Path(directory) / ".agents")
        lock = service.acquire_lock(); second = service.acquire_lock(); service.release_lock(lock); third = service.acquire_lock()
        check("lock-is-exclusive-and-releasable", isinstance(lock, int) and second is None and isinstance(third, int)); service.release_lock(third)
        first = change("core/a.txt", None, b"after"); second_change = change("core/b.txt", b"before", None)
        service.path("core/b.txt").parent.mkdir(parents=True, exist_ok=True); service.path("core/b.txt").write_bytes(b"before")
        service.write_after_changes([first, second_change]); after_ok = service.path("core/a.txt").read_bytes() == b"after" and not service.path("core/b.txt").exists()
        restored = service.restore_changes([first, second_change], use_before=True)
        check("write-and-restore-are-byte-exact", after_ok and restored and not service.path("core/a.txt").exists() and service.path("core/b.txt").read_bytes() == b"before")
        service.write_after_changes([first]); verified = service.verify_changes([first], after=True); service.path("core/a.txt").write_bytes(b"drift")
        check("verification-detects-byte-drift", verified and not service.verify_changes([first], after=True))
        invalid = service.apply("!", True); unconfirmed = service.apply("a" * 24, False); held = service.acquire_lock(); busy = service.apply("a" * 24, True); service.release_lock(held)
        check("apply-gates-confirmation-id-and-lock", invalid["reason_codes"] == ["PLAN_ID_INVALID"] and unconfirmed["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and busy["reason_codes"] == ["TRANSACTION_BUSY"])
        recovery_unconfirmed = service.recover(False); recovery_missing = service.recover(True); rollback_missing = service.plan_rollback("missing")
        check("recovery-and-rollback-fail-closed", recovery_unconfirmed["reason_codes"] == ["WRITE_CONFIRMATION_REQUIRED"] and recovery_missing["reason_codes"] == ["RECOVERY_JOURNAL_NOT_FOUND"] and rollback_missing["reason_codes"] == ["TRANSACTION_NOT_ROLLBACK_ELIGIBLE"])
        topology = json.loads((TOOLS_ROOT / "capability_lifecycle/topology.json").read_text()); entry = next(item for item in topology["entries"] if item.get("entrypoint", "").endswith("transaction_engine.py"))
        check("one-way-topology-and-cli-discoverability", entry["depends_on"] == ["_tools/capability_lifecycle/manifest_builder.py", "_tools/capability_lifecycle/platform_privacy.py", "_tools/capability_lifecycle/shared.py", "_tools/capability_lifecycle/state_planning.py"] and entry["focused_shard"].endswith("test_transaction_engine.py") and "agent_os_capability_lifecycle" not in Path(owner.__file__).read_text() and callable(facade.main) and service_class.plan_state_change is planning.StatePlanningMixin.plan_state_change)
    result = {"ok": all(item["passed"] for item in cases), "passed": sum(bool(item["passed"]) for item in cases), "total": len(cases), "cases": cases}; print(json.dumps(result, ensure_ascii=False)); raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__": main()
# fmt: on
