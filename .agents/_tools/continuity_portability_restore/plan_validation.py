"""Exact restore-plan admission for the stable restore facade."""

from __future__ import annotations

from typing import Any

from agent_os_context_memory import (
    canonical_hash,
    parse_time,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity_portability_export import BUNDLE_ID
from agent_os_continuity_portability_foundation import FULL_COMMIT, read_regular_bounded
from continuity_portability_restore.contracts import (
    _PLAN_ID,
    BACKUP_ID,
    RESTORE_PLAN_FIELDS,
    RESTORE_TARGET_FIELDS,
    _has_portable_path_collision,
    _valid_hash,
    _valid_time,
)


class RestorePlanValidationMixin:
    """Compatibility-preserving restore-plan validation."""

    def validate_restore_plan(self, plan: Any, plan_id: str) -> list[str]:
        policy, policy_errors = self.policy()
        if policy is None:
            return policy_errors
        if not isinstance(plan, dict) or set(plan) != RESTORE_PLAN_FIELDS:
            return ["PORTABILITY_RESTORE_PLAN_FIELDS_INVALID"]
        try:
            created = parse_time(str(plan.get("created_at")))
            expires = parse_time(str(plan.get("expires_at")))
        except (TypeError, ValueError):
            return ["PORTABILITY_RESTORE_PLAN_INVALID"]
        expected_id = canonical_hash(
            {
                key: value
                for key, value in plan.items()
                if key not in {"plan_id", "content_sha256"}
            }
        )[:24]
        if (
            plan.get("schema_version") != 1
            or plan.get("plan_id") != plan_id
            or _PLAN_ID.fullmatch(plan_id) is None
            or expected_id != plan_id
            or plan.get("status") != "pending-approval"
            or plan.get("operation") != "restore"
            or not _valid_time(plan.get("created_at"))
            or not _valid_time(plan.get("expires_at"))
            or expires <= created
            or not 60 <= (expires - created).total_seconds() <= 3600
            or not isinstance(plan.get("git_head"), str)
            or FULL_COMMIT.fullmatch(plan["git_head"]) is None
            or not isinstance(plan.get("project_id"), str)
            or not 1 <= len(plan["project_id"]) <= 128
            or any(
                not _valid_hash(plan.get(field))
                for field in (
                    "binding_sha256",
                    "adapter_fingerprint_sha256",
                    "core_manifest_sha256",
                    "record_type_registry_sha256",
                    "recovery_profile_sha256",
                    "retention_policy_sha256",
                    "target_inventory_sha256",
                )
            )
            or plan.get("commit_created") is not False
            or plan.get("push_performed") is not False
            or not isinstance(plan.get("exact_diff"), str)
            or len(plan["exact_diff"].encode("utf-8"))
            > policy["bounds"]["max_manifest_bytes"]
            or plan.get("content_sha256") != receipt_hash(plan)
        ):
            return ["PORTABILITY_RESTORE_PLAN_INVALID"]
        bundle_ref = plan.get("bundle")
        if (
            not isinstance(bundle_ref, dict)
            or set(bundle_ref)
            != {
                "bundle_id",
                "staged_path",
                "manifest_sha256",
                "inventory_sha256",
            }
            or not isinstance(bundle_ref.get("bundle_id"), str)
            or BUNDLE_ID.fullmatch(bundle_ref["bundle_id"]) is None
            or bundle_ref.get("staged_path")
            != f"_runtime/continuity-portability/staging/{bundle_ref['bundle_id']}"
            or not _valid_hash(bundle_ref.get("manifest_sha256"))
            or not _valid_hash(bundle_ref.get("inventory_sha256"))
        ):
            return ["PORTABILITY_RESTORE_PLAN_BUNDLE_INVALID"]
        try:
            staged_path = self.agent_path(bundle_ref["staged_path"])
        except ValueError:
            return ["PORTABILITY_RESTORE_PLAN_BUNDLE_INVALID"]
        inspected = self.inspect_bundle(staged_path)
        if (
            not inspected.get("ok")
            or inspected.get("manifest_sha256") != bundle_ref["manifest_sha256"]
            or inspected.get("manifest", {}).get("inventory_sha256")
            != bundle_ref["inventory_sha256"]
        ):
            return ["PORTABILITY_RESTORE_PLAN_BUNDLE_INVALID"]
        manifest = inspected["manifest"]
        entry_by_id = {entry["entry_id"]: entry for entry in manifest["entries"]}
        targets = plan.get("targets")
        if (
            not isinstance(targets, list)
            or not 1 <= len(targets) <= policy["bounds"]["max_entries"]
        ):
            return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
        if _has_portable_path_collision(targets):
            return ["PORTABILITY_RESTORE_TARGET_PATH_COLLISION"]
        paths: list[str] = []
        total_bytes = 0
        for target in targets:
            if not isinstance(target, dict) or set(target) != RESTORE_TARGET_FIELDS:
                return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
            entry = entry_by_id.get(target.get("entry_id"))
            path = target.get("path")
            if not isinstance(path, str) or not 1 <= len(path) <= 512:
                return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
            try:
                target_path = self.project_path(path)
            except ValueError:
                return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
            before, before_error = read_regular_bounded(
                target_path,
                policy["bounds"]["max_file_bytes"],
            )
            if target_path.exists() and before is None:
                return [
                    (
                        "PORTABILITY_RESTORE_TARGET_BOUND_EXCEEDED"
                        if before_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
                        else "PORTABILITY_RESTORE_TARGETS_INVALID"
                    )
                ]
            before_sha = sha256_bytes(before) if before is not None else None
            if (
                entry is None
                or entry["restore_mode"] != "replace"
                or not entry["present"]
                or path != entry["canonical_path"]
                or path in paths
                or target.get("action")
                != ("create" if target.get("before_sha256") is None else "replace")
                or not _valid_hash(target.get("before_sha256"), nullable=True)
                or target.get("before_sha256") != before_sha
                or target.get("after_sha256") != entry["sha256"]
                or target.get("bytes") != entry["bytes"]
                or target.get("backup_required") is not True
            ):
                return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
            paths.append(path)
            total_bytes += target["bytes"]
        if paths != sorted(paths) or total_bytes > policy["bounds"]["max_total_bytes"]:
            return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
        try:
            exact_diff = self.render_restore_diff(targets, staged_path, manifest)
        except ValueError:
            return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
        if (
            plan.get("target_inventory_sha256") != canonical_hash(targets)
            or BACKUP_ID.fullmatch(str(plan.get("backup_id"))) is None
            or plan.get("exact_diff") != exact_diff
        ):
            return ["PORTABILITY_RESTORE_TARGETS_INVALID"]
        expected_order, order_errors = self.restore_target_execution_order(
            staged_path,
            manifest,
            targets,
        )
        if expected_order is None:
            return order_errors
        if plan.get("target_execution_order") != expected_order:
            return ["PORTABILITY_RESTORE_DEPENDENCY_ORDER_INVALID"]
        return []
