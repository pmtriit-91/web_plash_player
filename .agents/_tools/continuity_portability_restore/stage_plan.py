"""Restore bundle staging and bounded plan construction.

This mixin is imported by the stable restore facade. It never imports that facade,
so dependency direction remains one-way while public method lookup stays compatible.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_os_context_memory import (
    canonical_hash,
    iso_time,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity_portability_export import EXPORT_MANIFEST_NAME
from agent_os_continuity_portability_foundation import read_regular_bounded
from agent_os_paths import safe_join


class RestoreStagePlanMixin:
    """Compatibility-preserving staging and planning methods for restore services."""

    def stage_bundle(
        self,
        source: Path,
        manifest: dict[str, Any],
        manifest_sha256: str,
    ) -> dict[str, Any]:
        staging_root = self.verified_owned_directory(
            "_runtime/continuity-portability/staging",
            create=True,
        )
        if staging_root is None:
            return {"ok": False, "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"]}
        destination = staging_root / manifest["bundle_id"]
        if destination.exists():
            existing = self.inspect_bundle(destination)
            if (
                existing.get("ok")
                and existing.get("manifest_sha256") == manifest_sha256
                and existing.get("manifest", {}).get("inventory_sha256")
                == manifest["inventory_sha256"]
            ):
                return {
                    "ok": True,
                    "staged_path": destination,
                }
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_STAGING_CONFLICT"],
            }
        temporary = self._create_scoped_temp_directory(
            self.root,
            "_runtime/continuity-portability/staging",
            prefix=f".{manifest['bundle_id']}.",
            suffix=".staging",
        )
        if temporary is None:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_STAGING_FAILED"],
                "error": "unsafe portability staging directory",
            }
        temporary_relative = f"_runtime/continuity-portability/staging/{temporary.name}"
        try:
            policy, policy_errors = self.policy()
            if policy is None:
                raise ValueError(f"retention policy invalid: {policy_errors}")
            bounds_by_name = {
                EXPORT_MANIFEST_NAME: policy["bounds"]["max_manifest_bytes"],
                **{
                    entry["storage_path"]: entry["bytes"]
                    for entry in manifest["entries"]
                    if entry["present"]
                },
            }
            for name, maximum in bounds_by_name.items():
                payload, _payload_error = read_regular_bounded(
                    safe_join(source, name, canonical=True),
                    maximum,
                )
                if payload is None:
                    raise ValueError(f"bundle payload disappeared: {name}")
                self._atomic_scoped_bytes(
                    self.root,
                    f"{temporary_relative}/{name}",
                    payload,
                    create_parents=True,
                )
            verified = self.inspect_bundle(temporary)
            if (
                not verified.get("ok")
                or verified.get("manifest_sha256") != manifest_sha256
            ):
                raise ValueError(
                    f"staged bundle failed verification: {verified.get('reason_codes')}"
                )
            if (
                self.verified_owned_directory(
                    "_runtime/continuity-portability/staging",
                    create=False,
                )
                != staging_root
                or temporary.parent != staging_root
            ):
                raise ValueError("portability staging root changed")
            if not self._rename_scoped_directory(
                self.root,
                "_runtime/continuity-portability/staging",
                temporary.name,
                destination.name,
            ):
                raise ValueError("portability staging destination changed")
            return {"ok": True, "staged_path": destination}
        except Exception as exc:  # noqa: BLE001 - preserve fail-closed staging parity
            try:
                self._remove_scoped_tree(self.root, temporary_relative)
            except (OSError, ValueError):
                pass
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_STAGING_FAILED"],
                "error": str(exc)[:480],
            }

    def plan_restore(
        self,
        source: str | Path,
        expiry_seconds: int = 900,
    ) -> dict[str, Any]:
        if not 60 <= expiry_seconds <= 3600:
            return {"ok": False, "reason_codes": ["PORTABILITY_PLAN_EXPIRY_INVALID"]}
        inspected = self.inspect_bundle(source)
        if not inspected.get("ok"):
            return inspected
        manifest = inspected["manifest"]
        compatibility = self.restore_compatibility(manifest)
        if compatibility:
            return {
                "ok": False,
                "reason_codes": list(
                    dict.fromkeys(item["code"] for item in compatibility)
                ),
                "issues": compatibility,
            }
        source_path = Path(inspected["bundle_path"])
        staged = self.stage_bundle(
            source_path,
            manifest,
            inspected["manifest_sha256"],
        )
        if not staged.get("ok"):
            return staged
        staged_path: Path = staged["staged_path"]
        policy, policy_errors = self.policy()
        if policy is None:
            return {"ok": False, "reason_codes": policy_errors}
        targets: list[dict[str, Any]] = []
        for entry in manifest["entries"]:
            if entry["restore_mode"] != "replace" or not entry["present"]:
                continue
            target_path = self.project_path(entry["canonical_path"])
            before, before_error = read_regular_bounded(
                target_path,
                policy["bounds"]["max_file_bytes"],
            )
            if target_path.exists() and before is None:
                return {
                    "ok": False,
                    "reason_codes": [
                        (
                            "PORTABILITY_RESTORE_TARGET_BOUND_EXCEEDED"
                            if before_error == "PORTABILITY_FILE_BOUND_EXCEEDED"
                            else "PORTABILITY_RESTORE_TARGET_INVALID"
                        )
                    ],
                }
            if before is not None and sha256_bytes(before) == entry["sha256"]:
                continue
            targets.append(
                {
                    "entry_id": entry["entry_id"],
                    "path": entry["canonical_path"],
                    "action": "create" if before is None else "replace",
                    "before_sha256": (
                        sha256_bytes(before) if before is not None else None
                    ),
                    "after_sha256": entry["sha256"],
                    "bytes": entry["bytes"],
                    "backup_required": True,
                }
            )
        targets = sorted(targets, key=lambda item: item["path"])
        if not targets:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_RESTORE_NO_CHANGES"],
                "bundle": {
                    "bundle_id": manifest["bundle_id"],
                    "integrity_state": "valid",
                    "compatibility_state": "compatible",
                },
            }
        target_execution_order, order_errors = self.restore_target_execution_order(
            staged_path,
            manifest,
            targets,
        )
        if target_execution_order is None:
            return {"ok": False, "reason_codes": order_errors}
        contracts = self.contract_hashes()
        head = self.head()
        binding = self.binding()
        if contracts is None or head is None or not binding.get("project_id"):
            return {"ok": False, "reason_codes": ["PORTABILITY_PREFLIGHT_INVALID"]}
        bundle_reference = {
            "bundle_id": manifest["bundle_id"],
            "staged_path": staged_path.relative_to(self.root).as_posix(),
            "manifest_sha256": inspected["manifest_sha256"],
            "inventory_sha256": manifest["inventory_sha256"],
        }
        created = self.now()
        backup_id = f"continuity-restore-backup-{secrets.token_hex(12)}"
        try:
            exact_diff = self.render_restore_diff(
                targets,
                staged_path,
                manifest,
            )
        except ValueError:
            return {
                "ok": False,
                "reason_codes": ["PORTABILITY_RESTORE_DIFF_BOUND_EXCEEDED"],
            }
        plan: dict[str, Any] = {
            "schema_version": 1,
            "plan_id": "",
            "status": "pending-approval",
            "operation": "restore",
            "created_at": iso_time(created),
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "git_head": head,
            "project_id": binding["project_id"],
            **contracts,
            "bundle": bundle_reference,
            "targets": targets,
            "target_inventory_sha256": canonical_hash(targets),
            "target_execution_order": target_execution_order,
            "backup_id": backup_id,
            "exact_diff": exact_diff,
            "commit_created": False,
            "push_performed": False,
        }
        plan["plan_id"] = canonical_hash(
            {
                key: value
                for key, value in plan.items()
                if key not in {"plan_id", "content_sha256"}
            }
        )[:24]
        plan["content_sha256"] = receipt_hash(plan)
        errors = self.validate_restore_plan(plan, plan["plan_id"])
        if errors:
            return {"ok": False, "reason_codes": errors}
        plan_root = self.verified_owned_directory(
            "_runtime/continuity-portability/plans",
            create=True,
        )
        if plan_root is None:
            return {"ok": False, "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"]}
        try:
            self._atomic_scoped_bytes(
                self.root,
                f"_runtime/continuity-portability/plans/{plan['plan_id']}.json",
                json_bytes(plan),
                create_parents=True,
            )
        except (OSError, ValueError):
            return {"ok": False, "reason_codes": ["PORTABILITY_RUNTIME_UNSAFE"]}
        return {
            "ok": True,
            "plan": plan,
            "bundle": {
                "bundle_id": manifest["bundle_id"],
                "integrity_state": "valid",
                "compatibility_state": "compatible",
            },
        }
