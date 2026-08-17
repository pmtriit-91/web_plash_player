"""Capability lifecycle planning and state-transition contracts."""

from __future__ import annotations

import difflib
from copy import deepcopy
from datetime import timedelta
from typing import Any

from capability_lifecycle.candidate_validation import ALLOWED_STATES, SAFE_ID
from capability_lifecycle.integration_builder import IntegrationBuilderMixin
from capability_lifecycle.shared import (
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    MANIFEST,
    atomic_json,
    canonical_hash,
    encoded,
    iso_time,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)


# fmt: off
class StatePlanningMixin(IntegrationBuilderMixin):
    def diff_for(self, before: bytes | None, after: bytes | None, relative: str) -> str:
        before_text = (before or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        after_text = (after or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        return "".join(difflib.unified_diff(before_text, after_text, fromfile=f"a/.agents/{relative}", tofile=f"b/.agents/{relative}"))

    def create_plan(self, desired: dict[str, bytes | None], metadata: dict[str, Any], expiry_seconds: int = 900, allow_dirty: bool = False) -> dict[str, Any]:
        head, dirty = self.clean_head()
        if not head:
            return {"ok": False, "reason_codes": ["GIT_HEAD_UNAVAILABLE"]}
        if dirty and not allow_dirty:
            return {"ok": False, "reason_codes": ["DIRTY_GIT"], "dirty": dirty}
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["PLAN_EXPIRY_INVALID"]}
        now = self.now()
        changes: list[dict[str, Any]] = []
        exact_diff = ""
        for relative in sorted(desired):
            before = self.read_bytes(relative)
            after = desired[relative]
            if before == after:
                continue
            changes.append(
                {
                    "path": relative,
                    "before_sha256": sha256_bytes(before) if before is not None else None,
                    "after_sha256": sha256_bytes(after) if after is not None else None,
                    "before_base64": encoded(before),
                    "after_base64": encoded(after),
                }
            )
            exact_diff += self.diff_for(before, after, relative)
        if not changes:
            return {"ok": False, "reason_codes": ["NO_CHANGES"]}
        plan_input = {
            **metadata,
            "git_head": head,
            "protected_digest": self.protected_digest(),
            "created_at": iso_time(now),
            "expires_at": iso_time(now + timedelta(seconds=expiry_seconds)),
            "changes": changes,
            "allow_dirty": allow_dirty,
        }
        plan_id = canonical_hash(plan_input)[:24]
        plan = {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "pending-approval",
            "risk": "release-owned-capability-lifecycle",
            "requires": ["human-approval", "exact-diff-review", "separate-content-commit", "separate-manifest-commit"],
            "input": plan_input,
            "exact_diff": exact_diff,
            "manifest_refresh_required": True,
            "commit_preview": {"enabled": False, "commit_created": False, "push_performed": False},
        }
        atomic_json(self.plans / f"{plan_id}.json", plan)
        return {"ok": True, "plan": plan}

    def plan_integration(self, candidate: Any, assembly: Any, expiry_seconds: int | None = None) -> dict[str, Any]:
        created_at = iso_time(self.now())
        desired, metadata, errors = self.build_integration(candidate, assembly, created_at)
        if errors:
            return {"ok": False, "reason_codes": ["INTEGRATION_VALIDATION_FAILED"], "errors": errors}
        lifetime = expiry_seconds if expiry_seconds is not None else 900
        try:
            return self.create_plan(desired, metadata, lifetime)
        except (OSError, ValueError) as exc:
            return {"ok": False, "reason_codes": ["INTEGRATION_PATH_OR_IO_REJECTED"], "error": str(exc)}

    def compare_update(self, capability_id: str, candidate: Any) -> dict[str, Any]:
        descriptors = self.document(DESCRIPTORS, {}).get("capabilities", [])
        current = next((item for item in descriptors if item.get("id") == capability_id), None)
        if not isinstance(current, dict):
            return {"ok": False, "reason_codes": ["CAPABILITY_NOT_FOUND"]}
        errors = self.validate_candidate_for_activation(candidate)
        source = candidate.get("source", {}) if isinstance(candidate, dict) else {}
        current_source = current.get("source", {})
        same_pin = bool(source.get("commit") and source.get("commit") == current_source.get("commit"))
        return {
            "ok": not errors,
            "capability_id": capability_id,
            "current": {
                "version": current.get("version"),
                "commit": current_source.get("commit"),
                "license": current_source.get("license"),
                "decision_ref": current.get("decision_ref"),
            },
            "candidate": {
                "id": candidate.get("id") if isinstance(candidate, dict) else None,
                "commit": source.get("commit"),
                "license": source.get("license"),
                "snapshot_sha256": source.get("snapshot_sha256"),
                "recommendation": candidate.get("recommendation") if isinstance(candidate, dict) else None,
            },
            "same_pin": same_pin,
            "eligible_for_plan": not errors and not same_pin,
            "old_pin_remains_active_until_apply": True,
            "errors": errors,
        }

    def plan_state_change(self, capability_id: str, state: str, replacement: str | None = None, expiry_seconds: int = 900) -> dict[str, Any]:
        if not SAFE_ID.fullmatch(capability_id) or state not in ALLOWED_STATES - {"active"}:
            return {"ok": False, "reason_codes": ["STATE_CHANGE_INVALID"]}
        documents = self.base_documents()
        descriptors = documents[DESCRIPTORS].get("capabilities", [])
        target = next((item for item in descriptors if item.get("id") == capability_id), None)
        if not isinstance(target, dict):
            return {"ok": False, "reason_codes": ["CAPABILITY_NOT_FOUND"]}
        if replacement and replacement not in {item.get("id") for item in descriptors}:
            return {"ok": False, "reason_codes": ["REPLACEMENT_CAPABILITY_NOT_FOUND"]}
        if replacement == capability_id:
            return {"ok": False, "reason_codes": ["REPLACEMENT_CAPABILITY_SELF_REFERENCE"]}
        if replacement:
            replacement_descriptor = next(item for item in descriptors if item.get("id") == replacement)
            if replacement_descriptor.get("lifecycle_state") != "active":
                return {"ok": False, "reason_codes": ["REPLACEMENT_CAPABILITY_NOT_ACTIVE"]}
        target["lifecycle_state"] = state
        now = iso_time(self.now())
        receipt = {
            "schema_version": 1,
            "id": f"lifecycle-{canonical_hash({'capability': capability_id, 'state': state, 'at': now})[:24]}",
            "candidate_id": None,
            "capability_id": capability_id,
            "action": "state-change",
            "state": state,
            "integration_mode": target.get("integration_mode"),
            "at": now,
            "decision_ref": target.get("decision_ref"),
            "source_snapshot_sha256": None,
            "eval_case_ids": target.get("eval", {}).get("case_ids", []),
            "replacement": replacement,
            "manifest_refresh_required": True,
            "commit_created": False,
            "push_performed": False,
        }
        receipt["content_sha256"] = receipt_hash(receipt)
        documents[LIFECYCLE_LEDGER].setdefault("receipts", []).append(receipt)
        errors = self.validate_snapshot(documents, {})
        if errors:
            return {"ok": False, "reason_codes": ["STATE_CHANGE_VALIDATION_FAILED"], "errors": errors}
        desired: dict[str, bytes | None] = {
            DESCRIPTORS: json_bytes(documents[DESCRIPTORS]),
            LIFECYCLE_LEDGER: json_bytes(documents[LIFECYCLE_LEDGER]),
        }
        desired[MANIFEST] = self.render_working_manifest(desired, now, receipt["id"])
        runtime_candidates = [
            item for item in self.runtime_candidate_records()
            if item.get("target_capability_id") == capability_id and item.get("state") == "active"
        ]
        runtime_candidate = deepcopy(runtime_candidates[-1]) if runtime_candidates else None
        if isinstance(runtime_candidate, dict) and state in {"deprecated", "quarantined"}:
            runtime_candidate["state"] = state
            runtime_candidate.setdefault("decision_history", []).append(
                {"state": state, "at": now, "actor": "capability-lifecycle"}
            )
        elif state in {"manual-only", "disabled"}:
            runtime_candidate = None
        return self.create_plan(
            desired,
            {"operation": "capability-state-change", "capability_id": capability_id, "state": state, "replacement": replacement, "runtime_candidate": runtime_candidate},
            expiry_seconds,
        )
# fmt: on
