from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from typing import Any

from agent_os_context_memory import (
    atomic_bytes,
    canonical_hash,
    encoded,
    iso_time,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)
from agent_os_continuity import (
    generic_json_identity,
    load_json,
    validate_reference_shape,
)
from continuity_transactions.contracts import (
    CATALOG_REL,
    MAX_PLAN_SECONDS,
    OPERATIONS,
    PROFILE_REL,
    PROJECTION_REL,
    REGISTRY_REL,
    strict_document,
)


# fmt: off
class TransitionPlanningMixin:
    def refresh_catalog(self, catalog: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        if catalog.get("schema_version") not in {1, 2}:
            return None, ["CONTINUITY_GENERATION_UNSUPPORTED"]
        updated = deepcopy(catalog)
        timestamp = iso_time(self.now())
        try:
            registry_document = load_json(self.path(REGISTRY_REL))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None, ["CONTINUITY_CORE_CONTRACT_UNREADABLE"]
        type_contracts = {
            item.get("record_type"): item
            for item in registry_document.get("types", [])
            if isinstance(item, dict) and isinstance(item.get("record_type"), str)
        }
        updated["record_type_registry"]["registry_sha256"] = sha256_bytes(self.path(REGISTRY_REL).read_bytes())
        updated["recovery_profile"]["profile_sha256"] = sha256_bytes(self.path(PROFILE_REL).read_bytes())
        errors: list[str] = []
        for reference in updated.get("references", []):
            contract = type_contracts.get(reference.get("record_type"))
            if not isinstance(contract, dict):
                errors.append("CONTINUITY_RECORD_TYPE_UNSUPPORTED")
                continue
            source = reference.get("source", {})
            descriptor, document, source_errors = self.source_descriptor(
                str(source.get("path", "")),
                source.get("schema_id"),
                source.get("schema_version"),
                missing_allowed=(
                    reference.get("requirement") == "state-aware"
                    and contract.get("missing_state_allowed") is True
                ),
            )
            errors.extend(source_errors)
            if descriptor is None:
                continue
            before = deepcopy(reference)
            reference["source"] = descriptor
            identity = generic_json_identity(document, str(contract.get("identity_rule", "")))
            if identity is not None:
                reference["record_id"] = identity
            rule = str(contract.get("revision_rule", ""))
            if rule.startswith("json-field:") and isinstance(document, dict):
                reference["record_revision"] = document.get(rule.split(":", 1)[1])
            elif rule == "catalog-field:record_revision" and descriptor.get("sha256") is not None:
                reference["record_revision"] = descriptor["sha256"]
            elif rule == "constant:null":
                reference["record_revision"] = None
            if reference != before:
                reference["updated_at"] = timestamp
        if errors:
            return None, list(dict.fromkeys(errors))
        if updated == catalog:
            return None, ["NO_CHANGES"]
        updated["catalog_revision"] = catalog["catalog_revision"] + 1
        updated["updated_at"] = timestamp
        return updated, []

    def migration_target(
        self,
        source: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]:
        source_generation = source.get("schema_version")
        if type(source_generation) is not int or source_generation < 0:
            return None, None, ["CONTINUITY_MIGRATION_SOURCE_INVALID"]
        chain, chain_errors = self.migration_chain(source_generation, 2)
        if chain_errors:
            return None, None, chain_errors
        if not chain:
            return None, None, ["NO_CHANGES"]
        references = source.get("references")
        if not isinstance(references, list):
            return None, None, ["CONTINUITY_MIGRATION_SOURCE_INVALID"]
        reference_bytes = json_bytes(references)
        target = deepcopy(source)
        path: list[dict[str, Any]] = []
        extensions: list[dict[str, Any]] = []
        for entry in chain:
            expected_fields = set(entry["source_fields"])
            actual_fields = set(target)
            unknown_fields = actual_fields - expected_fields
            if (
                target.get("schema_version") != entry["source_generation"]
                or not isinstance(target.get("record_type_registry"), dict)
                or not isinstance(target.get("recovery_profile"), dict)
            ):
                return None, None, ["CONTINUITY_MIGRATION_SOURCE_INVALID"]
            if unknown_fields and entry["reject_unknown_fields"]:
                return None, None, ["CONTINUITY_MIGRATION_UNKNOWN_FIELDS_UNSUPPORTED"]
            if expected_fields - actual_fields:
                return None, None, ["CONTINUITY_MIGRATION_SOURCE_INVALID"]
            reference_errors = [
                error
                for index, reference in enumerate(target.get("references", []))
                for error in validate_reference_shape(reference, index)
            ]
            if reference_errors:
                return None, None, list(dict.fromkeys(item["code"] for item in reference_errors))
            fields = {key: deepcopy(target[key]) for key in sorted(unknown_fields)}
            evidence_hash = canonical_hash(fields)
            hop = {
                "migration_id": entry["migration_id"],
                "provider": entry["provider"],
                "source_generation": entry["source_generation"],
                "target_generation": entry["target_generation"],
                "unknown_fields_sha256": evidence_hash,
            }
            if entry["provider"] not in {
                "builtin:continuity-catalog-draft-v0-to-v1",
                "builtin:continuity-catalog-v1-to-v2",
            }:
                return None, None, ["CONTINUITY_MIGRATION_PROVIDER_UNSUPPORTED"]
            before_critical = self.critical_set(target)
            target["schema_version"] = entry["target_generation"]
            if entry["source_generation"] == 0:
                target["catalog_revision"] = 1
            target["record_type_registry"]["registry_sha256"] = sha256_bytes(self.path(REGISTRY_REL).read_bytes())
            target["recovery_profile"]["profile_sha256"] = sha256_bytes(self.path(PROFILE_REL).read_bytes())
            target["updated_at"] = iso_time(self.now())
            if before_critical != self.critical_set(target):
                return None, None, ["CONTINUITY_MIGRATION_CRITICAL_SET_DRIFT"]
            path.append(hop)
            extensions.append(
                {
                    "source_generation": entry["source_generation"],
                    "migration_id": entry["migration_id"],
                    "unknown_fields_sha256": evidence_hash,
                    "fields": fields,
                }
            )
        target["migration_extensions"] = extensions
        if json_bytes(target.get("references")) != reference_bytes:
            return None, None, ["CONTINUITY_MIGRATION_REFERENCE_DRIFT"]
        return target, path, []

    def migrate_catalog(self, source: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        target, _path, errors = self.migration_target(source)
        return target, errors

    def change_set(
        self,
        desired: dict[str, bytes | None],
    ) -> tuple[list[dict[str, Any]], str]:
        changes: list[dict[str, Any]] = []
        for relative in sorted(desired):
            before = self.target_bytes(relative)
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
        return changes, self.render_exact_diff(changes)

    def create_plan(
        self,
        operation: str,
        desired: dict[str, bytes | None],
        *,
        before_catalog: Any,
        after_catalog: Any,
        source_paths: set[str],
        metadata: dict[str, Any] | None = None,
        expiry_seconds: int = 900,
    ) -> dict[str, Any]:
        if operation not in OPERATIONS or not 60 <= expiry_seconds <= MAX_PLAN_SECONDS:
            return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_ARGUMENT_INVALID"]}
        head = self.head()
        contracts = self.contract_hashes()
        binding = self.binding()
        project_id = binding.get("project_id")
        if not head or contracts is None or not isinstance(project_id, str) or not project_id:
            return {"ok": False, "reason_codes": ["CONTINUITY_PLAN_ENVIRONMENT_INVALID"]}
        changes, exact_diff = self.change_set(desired)
        if not changes:
            return {"ok": False, "reason_codes": ["NO_CHANGES"]}
        inventory, inventory_hash = self.source_inventory(source_paths)
        created = self.now()
        seed = {
            "operation": operation,
            "head": head,
            "project_id": project_id,
            "created_at": iso_time(created),
            "changes": [(item["path"], item["before_sha256"], item["after_sha256"]) for item in changes],
        }
        transaction_id = f"continuity-tx-{canonical_hash(seed)[:24]}"
        backup_id = f"continuity-backup-{canonical_hash({**seed, 'backup': True})[:24]}"
        plan = {
            "schema_version": 1,
            "plan_id": "",
            "status": "pending-approval",
            "operation": operation,
            "created_at": iso_time(created),
            "expires_at": iso_time(created + timedelta(seconds=expiry_seconds)),
            "git_head": head,
            "project_id": project_id,
            **contracts,
            "source_inventory": inventory,
            "source_inventory_sha256": inventory_hash,
            "changes": changes,
            "exact_diff": exact_diff,
            "metadata": {
                **(metadata or {}),
                "transaction_id": transaction_id,
                "backup_id": backup_id,
                "source_generation": before_catalog.get("schema_version") if isinstance(before_catalog, dict) else None,
                "target_generation": after_catalog.get("schema_version") if isinstance(after_catalog, dict) else None,
                "critical_set_before": self.critical_set(before_catalog),
                "critical_set_after": self.critical_set(after_catalog),
                "unknown_fields_sha256": (metadata or {}).get("unknown_fields_sha256"),
            },
            "commit_created": False,
            "push_performed": False,
        }
        plan["plan_id"] = canonical_hash(
            {key: value for key, value in plan.items() if key not in {"plan_id", "content_sha256"}}
        )[:24]
        plan["content_sha256"] = receipt_hash(plan)
        self.plans.mkdir(parents=True, exist_ok=True)
        atomic_bytes(self.plans / f"{plan['plan_id']}.json", json_bytes(plan))
        return {"ok": True, "plan": plan}

    def plan_initialize(self) -> dict[str, Any]:
        if self.target_bytes(CATALOG_REL) is not None:
            return {"ok": False, "reason_codes": ["CONTINUITY_ALREADY_CONFIGURED"]}
        catalog, errors = self.initial_catalog()
        if errors or catalog is None:
            return {"ok": False, "reason_codes": errors}
        projection, _health, projection_errors = self.projection_for(catalog)
        if projection_errors or projection is None:
            return {"ok": False, "reason_codes": projection_errors}
        return self.create_plan(
            "initialize",
            {CATALOG_REL: json_bytes(catalog), PROJECTION_REL: projection},
            before_catalog=None,
            after_catalog=catalog,
            source_paths=self.catalog_source_paths(catalog),
        )

    def plan_refresh(self, operation: str = "refresh") -> dict[str, Any]:
        content = self.target_bytes(CATALOG_REL)
        if content is None:
            return {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_MISSING"]}
        try:
            catalog = strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_INVALID_JSON"]}
        if not isinstance(catalog, dict):
            return {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_NOT_OBJECT"]}
        updated, errors = self.refresh_catalog(catalog)
        if errors or updated is None:
            return {"ok": False, "reason_codes": errors}
        projection, _health, projection_errors = self.projection_for(updated)
        if projection_errors or projection is None:
            return {"ok": False, "reason_codes": projection_errors}
        return self.create_plan(
            operation,
            {CATALOG_REL: json_bytes(updated), PROJECTION_REL: projection},
            before_catalog=catalog,
            after_catalog=updated,
            source_paths=self.catalog_source_paths(updated),
        )

    def plan_migrate(self) -> dict[str, Any]:
        content = self.target_bytes(CATALOG_REL)
        if content is None:
            return {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_MISSING"]}
        try:
            source = strict_document(content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"ok": False, "reason_codes": ["CONTINUITY_CATALOG_INVALID_JSON"]}
        if not isinstance(source, dict):
            return {"ok": False, "reason_codes": ["CONTINUITY_MIGRATION_SOURCE_INVALID"]}
        target, path, errors = self.migration_target(source)
        if errors or target is None or path is None:
            return {"ok": False, "reason_codes": errors}
        projection, _health, projection_errors = self.projection_for(target)
        if projection_errors or projection is None:
            return {"ok": False, "reason_codes": projection_errors}
        return self.create_plan(
            "migrate",
            {CATALOG_REL: json_bytes(target), PROJECTION_REL: projection},
            before_catalog=source,
            after_catalog=target,
            source_paths=self.catalog_source_paths(target),
            metadata={
                "migration_id": path[-1]["migration_id"],
                "migration_path": path,
                "migration_path_sha256": canonical_hash(path),
                "unknown_fields_sha256": canonical_hash(
                    [item["unknown_fields_sha256"] for item in path]
                ),
            },
        )
