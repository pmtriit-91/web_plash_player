from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from agent_os_context_memory import iso_time, json_bytes, sha256_bytes
from agent_os_continuity import doctor, validate_catalog_shape, validate_reference_shape
from continuity_transactions.contracts import PROFILE_REL, REGISTRY_REL


# fmt: off
class CatalogInitializationMixin:
    def initial_catalog(self) -> tuple[dict[str, Any] | None, list[str]]:
        binding = self.binding()
        project_id = binding.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            return None, ["PROJECT_BINDING_REQUIRED"]
        timestamp = iso_time(self.now())
        registry = self.path(REGISTRY_REL)
        profile = self.path(PROFILE_REL)
        if not registry.is_file() or not profile.is_file():
            return None, ["CONTINUITY_CORE_CONTRACT_UNREADABLE"]

        definitions = [
            {
                "reference_id": "project-binding",
                "record_type": "project-binding",
                "profile_role": "project-binding",
                "path": ".agents/project/project-binding.json",
                "schema_id": "project-binding",
                "schema_version": 1,
                "record_id": project_id,
                "record_revision": None,
                "requirement": "required",
                "load_policy": "boot",
                "authority_provider": "binding-doctor",
                "dependencies": [],
                "retention_class": "critical-active",
            },
            {
                "reference_id": "agent-os-release",
                "record_type": "agent-os-release",
                "profile_role": "agent-os-release",
                "path": ".agents/_manifest/base-release-manifest.json",
                "schema_id": "base-release-manifest",
                "schema_version": 1,
                "identity": "release_id",
                "revision": "agent_os_version",
                "requirement": "required",
                "load_policy": "boot",
                "authority_provider": "core-manifest-validator",
                "dependencies": [{"relation": "requires", "target_reference_id": "project-binding"}],
                "retention_class": "critical-active",
            },
            {
                "reference_id": "project-genesis",
                "record_type": "project-genesis",
                "profile_role": "project-genesis",
                "path": ".agents/project/genesis.json",
                "schema_id": "project-genesis",
                "schema_version": 1,
                "record_id": "project-genesis",
                "record_revision": None,
                "requirement": "state-aware",
                "load_policy": "boot",
                "authority_provider": "genesis-doctor",
                "dependencies": [{"relation": "requires", "target_reference_id": "project-binding"}],
                "retention_class": "critical-active",
                "missing_allowed": True,
            },
            {
                "reference_id": "context-manifest",
                "record_type": "context-manifest",
                "profile_role": "context-manifest",
                "path": ".agents/project/context/context-manifest.json",
                "schema_id": "context-manifest",
                "schema_version": 1,
                "identity": "project_id",
                "revision": "refreshed_commit",
                "requirement": "required",
                "load_policy": "boot",
                "authority_provider": "context-memory-doctor",
                "dependencies": [{"relation": "requires", "target_reference_id": "project-binding"}],
                "retention_class": "critical-active",
            },
            {
                "reference_id": "roadmap",
                "record_type": "roadmap",
                "profile_role": "roadmap",
                "path": "docs/roadmap.md",
                "schema_id": None,
                "schema_version": None,
                "record_id": "master-roadmap",
                "requirement": "required",
                "load_policy": "just-in-time",
                "authority_provider": "governance-document-validator",
                "dependencies": [{"relation": "requires", "target_reference_id": "project-binding"}],
                "retention_class": "critical-active",
            },
            {
                "reference_id": "current-status",
                "record_type": "current-status",
                "profile_role": "current-status",
                "path": "docs/context/current-status.md",
                "schema_id": None,
                "schema_version": None,
                "record_id": "current-status",
                "requirement": "required",
                "load_policy": "boot",
                "authority_provider": "governance-document-validator",
                "dependencies": [{"relation": "generated-from", "target_reference_id": "roadmap"}],
                "retention_class": "critical-active",
            },
            {
                "reference_id": "active-task-ledger",
                "record_type": "active-task-ledger",
                "profile_role": "active-task-ledger",
                "path": ".agents/project/context/active-tasks.json",
                "schema_id": "active-task-ledger",
                "schema_version": 1,
                "identity": "project_id",
                "record_revision": None,
                "requirement": "required",
                "load_policy": "boot",
                "authority_provider": "task-ledger-validator",
                "dependencies": [{"relation": "requires", "target_reference_id": "context-manifest"}],
                "retention_class": "critical-active",
            },
        ]
        references: list[dict[str, Any]] = []
        errors: list[str] = []
        for definition in definitions:
            source, document, source_errors = self.source_descriptor(
                definition["path"],
                definition["schema_id"],
                definition["schema_version"],
                missing_allowed=bool(definition.get("missing_allowed")),
            )
            errors.extend(source_errors)
            if source is None:
                continue
            content_hash = source.get("sha256")
            record_id = definition.get("record_id")
            if record_id is None and isinstance(document, dict):
                record_id = document.get(definition.get("identity"))
            revision = definition.get("record_revision")
            if "record_revision" not in definition:
                revision = (
                    document.get(definition.get("revision"))
                    if isinstance(document, dict) and definition.get("revision")
                    else content_hash
                )
            if not isinstance(record_id, str) or not record_id:
                errors.append("CONTINUITY_INITIAL_REFERENCE_IDENTITY_INVALID")
                continue
            references.append(
                {
                    "reference_id": definition["reference_id"],
                    "record_type": definition["record_type"],
                    "profile_role": definition["profile_role"],
                    "record_id": record_id,
                    "record_revision": revision,
                    "requirement": definition["requirement"],
                    "lifecycle": "active",
                    "load_policy": definition["load_policy"],
                    "authority_provider": definition["authority_provider"],
                    "source": source,
                    "dependencies": definition["dependencies"],
                    "supersedes": [],
                    "retention_class": definition["retention_class"],
                    "privacy_class": "project-internal",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
        if errors:
            return None, list(dict.fromkeys(errors))
        return {
            "schema_version": 2,
            "project_id": project_id,
            "catalog_id": f"continuity-{project_id}",
            "catalog_revision": 1,
            "record_type_registry": {
                "registry_id": "universal-continuity-record-types",
                "registry_version": 1,
                "registry_sha256": sha256_bytes(registry.read_bytes()),
            },
            "recovery_profile": {
                "profile_id": "universal-project-continuity",
                "profile_version": 1,
                "profile_sha256": sha256_bytes(profile.read_bytes()),
            },
            "migration_extensions": [],
            "references": references,
            "created_at": timestamp,
            "updated_at": timestamp,
        }, []

    def validate_target(self, catalog: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        shape_errors = validate_catalog_shape(catalog)
        for index, reference in enumerate(catalog.get("references", [])):
            shape_errors.extend(validate_reference_shape(reference, index))
        if shape_errors:
            return None, list(dict.fromkeys(item["code"] for item in shape_errors))
        with tempfile.TemporaryDirectory(prefix="agent-os-continuity-") as directory:
            target = Path(directory) / "continuity.json"
            target.write_bytes(json_bytes(catalog))
            health = doctor(self.root, target)
        if health.get("topology_state") != "complete":
            return None, list(
                dict.fromkeys(
                    [
                        *health.get("reason_codes", []),
                        "CONTINUITY_TARGET_NOT_SEMANTICALLY_COMPLETE",
                    ]
                )
            )
        return health, []

    def projection_for(self, catalog: dict[str, Any]) -> tuple[bytes | None, dict[str, Any] | None, list[str]]:
        health, errors = self.validate_target(catalog)
        if errors or health is None:
            return None, None, errors
        projection = health.get("projection_preview")
        if not isinstance(projection, dict) or not projection:
            return None, None, ["CONTINUITY_PROJECTION_UNAVAILABLE"]
        return json_bytes(projection), health, []
