#!/usr/bin/env python3
"""Transactional capability assembly, activation, update, and rollback.

The lifecycle never executes candidate code. An agent prepares a bounded assembly
document, the operator reviews an exact multi-file diff, and one explicit apply
confirmation atomically updates the release authorities plus an internally
consistent working-baseline manifest. Verified-release provenance still requires
the separate content and generated-manifest commits defined by release policy.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_os_capabilities import INTEGRATION_MODES, tokens, trigger_matches_text
from agent_os_research import FULL_COMMIT, normalized_receipt_hash, validate_candidate
from capability_lifecycle.state_planning import StatePlanningMixin
from capability_lifecycle.platform_privacy import (
    PLAN_ID,
    SAFE_ID,
    SHA256,
    TELEMETRY_KEY_DPAPI_ENTROPY,
    USAGE_CONFIDENCE,
    USAGE_MAX_EVIDENCE_ITEMS,
    USAGE_MAX_STORED_RECEIPT_BYTES,
    USAGE_OUTCOMES,
    USAGE_RECEIPT_FIELDS,
    recent_jsonl_lines,
    usage_receipt_errors,
    windows_dpapi,
)
from capability_lifecycle.shared import (
    CANDIDATES,
    CAPABILITY_DECISIONS,
    CONTROL_DOCUMENTS,
    DEFAULT_ROOT,  # noqa: F401 - public facade re-export
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    MANIFEST,
    REGISTRY,
    RESEARCH_DECISIONS,
    ROUTING_CORPUS,
    VENDOR_LOCK,
    CapabilityLifecycleBase,
    atomic_bytes,
    atomic_json,
    canonical_hash,
    decoded,
    encoded,
    iso_time,
    json_bytes,
    load_json,
    parse_time,
    receipt_hash,
    receipt_valid,
    safe_relative,
    sha256_bytes,
    utc_now,  # noqa: F401 - public facade re-export
)
from capability_lifecycle.candidate_validation import (
    ALLOWED_MODES,
    ALLOWED_STATES,
    PERMISSION_FIELDS,
    SCRIPT_SUFFIXES,
    CandidateValidationMixin,
)
from capability_lifecycle.integration_builder import IntegrationBuilderMixin
from capability_lifecycle.manifest_builder import ManifestBuilderMixin
from capability_lifecycle.transaction_engine import TransactionEngineMixin
from capability_lifecycle.telemetry import (
    TELEMETRY_KEY_BYTES,
    TELEMETRY_KEY_DPAPI_PREFIX,
    USAGE_MAX_EVIDENCE_BYTES,
    USAGE_MAX_TASK_BYTES,
    TelemetryMixin,
)

class CapabilityLifecycleService(TransactionEngineMixin, StatePlanningMixin, IntegrationBuilderMixin, ManifestBuilderMixin, CandidateValidationMixin, TelemetryMixin, CapabilityLifecycleBase):
    pass



def main() -> None:
    parser = argparse.ArgumentParser(description="Agent OS capability lifecycle transaction engine")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan-integration")
    plan.add_argument("--candidate", required=True)
    plan.add_argument("--assembly", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm", action="store_true")
    compare = sub.add_parser("compare-update")
    compare.add_argument("--capability", required=True)
    compare.add_argument("--candidate", required=True)
    rollback = sub.add_parser("plan-rollback")
    rollback.add_argument("--transaction", required=True)
    rollback.add_argument("--expiry-seconds", type=int, default=900)
    state = sub.add_parser("plan-state")
    state.add_argument("--capability", required=True)
    state.add_argument("--state", required=True)
    state.add_argument("--replacement")
    usage = sub.add_parser("record-usage")
    usage.add_argument("--capability", required=True)
    usage.add_argument("--task", required=True)
    usage.add_argument("--confidence", required=True)
    usage.add_argument("--evidence", action="append", default=[])
    usage.add_argument("--outcome", required=True)
    sub.add_parser("usage-review")
    sub.add_parser("queue")
    recover = sub.add_parser("recover")
    recover.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    service = CapabilityLifecycleService()
    try:
        if args.command == "plan-integration":
            result = service.plan_integration(load_json(Path(args.candidate).expanduser().resolve(), None), load_json(Path(args.assembly).expanduser().resolve(), None))
        elif args.command == "apply":
            result = service.apply(args.plan, args.confirm)
        elif args.command == "compare-update":
            result = service.compare_update(args.capability, load_json(Path(args.candidate).expanduser().resolve(), None))
        elif args.command == "plan-rollback":
            result = service.plan_rollback(args.transaction, args.expiry_seconds)
        elif args.command == "plan-state":
            result = service.plan_state_change(args.capability, args.state, args.replacement)
        elif args.command == "record-usage":
            result = service.record_usage(args.capability, args.task, args.confidence, args.evidence, args.outcome)
        elif args.command == "usage-review":
            result = service.usage_review()
        elif args.command == "queue":
            result = service.queue()
        elif args.command == "recover":
            result = service.recover(args.confirm)
        else:
            result = {"ok": False, "reason_codes": ["COMMAND_NOT_IMPLEMENTED"]}
    except Exception as exc:
        result = {"ok": False, "error": {"code": exc.__class__.__name__, "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
