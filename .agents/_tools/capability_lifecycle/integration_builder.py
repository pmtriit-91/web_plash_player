"""Capability lifecycle integration construction contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_os_research import normalized_receipt_hash
from capability_lifecycle.candidate_validation import ALLOWED_MODES
from capability_lifecycle.manifest_builder import ManifestBuilderMixin
from capability_lifecycle.platform_privacy import SAFE_ID
from capability_lifecycle.shared import (
    CANDIDATES,
    CAPABILITY_DECISIONS,
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    MANIFEST,
    REGISTRY,
    RESEARCH_DECISIONS,
    ROUTING_CORPUS,
    VENDOR_LOCK,
    canonical_hash,
    json_bytes,
    receipt_hash,
    sha256_bytes,
)


# fmt: off
class IntegrationBuilderMixin(ManifestBuilderMixin):
    def build_integration(self, candidate: dict[str, Any], assembly: dict[str, Any], created_at: str) -> tuple[dict[str, bytes], dict[str, Any], list[dict[str, Any]]]:
        errors = self.validate_candidate_for_activation(candidate)
        if not isinstance(assembly, dict) or assembly.get("schema_version") != 1:
            return {}, {}, [*errors, {"code": "ASSEMBLY_SCHEMA_INVALID"}]
        if assembly.get("candidate_id") != candidate.get("id"):
            errors.append({"code": "ASSEMBLY_CANDIDATE_MISMATCH"})
        capability_id = str(assembly.get("capability_id", ""))
        if not SAFE_ID.fullmatch(capability_id):
            errors.append({"code": "CAPABILITY_ID_INVALID"})
        mode = str(assembly.get("integration_mode", ""))
        if mode not in ALLOWED_MODES or mode != candidate.get("recommendation"):
            errors.append({"code": "ASSEMBLY_INTEGRATION_MODE_INVALID", "mode": mode})
        files, file_errors = self.prepare_assembly_files(candidate, assembly, mode, capability_id)
        errors.extend(file_errors)
        if errors:
            return {}, {}, errors

        documents = self.base_documents()
        registry = deepcopy(documents[REGISTRY])
        descriptors_document = deepcopy(documents[DESCRIPTORS])
        decision_document = deepcopy(documents[CAPABILITY_DECISIONS])
        lifecycle_document = deepcopy(documents[LIFECYCLE_LEDGER])
        candidates_document = deepcopy(documents[CANDIDATES])
        research_decisions = deepcopy(documents[RESEARCH_DECISIONS])
        vendor_lock = deepcopy(documents[VENDOR_LOCK])
        corpus = deepcopy(documents[ROUTING_CORPUS])

        existing_descriptors = {
            item.get("id"): item for item in descriptors_document.get("capabilities", []) if isinstance(item, dict)
        }
        operation = "update" if capability_id in existing_descriptors else "integrate"
        if operation == "update" and existing_descriptors[capability_id].get("integration_mode") != mode:
            errors.append({"code": "UPDATE_INTEGRATION_MODE_CHANGE_REJECTED"})

        routing = assembly.get("routing") if isinstance(assembly.get("routing"), dict) else {}
        route = assembly.get("route") if isinstance(assembly.get("route"), dict) else {}
        if mode == "vendor-pin":
            required_route = {"path", "group", "role", "high_triggers"}
            if set(route) != required_route or route.get("role") != "primary" or not route.get("high_triggers"):
                errors.append({"code": "VENDOR_ROUTE_INVALID"})
        else:
            required_route = {"mode", "triggers", "load", "checks"}
            if set(route) != required_route or route.get("mode") not in {"FAST", "STANDARD", "DEEP"} or not route.get("triggers"):
                errors.append({"code": "LOCAL_ROUTE_INVALID"})
        if errors:
            return {}, {}, errors

        decision_seed = {
            "candidate_id": candidate["id"], "capability_id": capability_id,
            "snapshot": candidate["source"]["snapshot_sha256"], "created_at": created_at,
            "operation": operation, "assembly": canonical_hash(assembly),
        }
        decision_id = f"aos10-{candidate['id']}-{canonical_hash(decision_seed)[:12]}"
        rationale = str(assembly.get("rationale", ""))
        if len(rationale) < 10:
            errors.append({"code": "INTEGRATION_RATIONALE_REQUIRED"})
        decision_receipt = {
            "id": decision_id,
            "candidate_id": candidate["id"],
            "capability_ids": [capability_id],
            "decided_at": created_at,
            "decision": mode,
            "evidence": [
                f"candidate-snapshot:{candidate['source']['snapshot_sha256']}",
                "hard-gates:passed",
                "shadow-routing:passed",
            ],
            "rationale": rationale,
            "constraints": ["No upstream executable content is activated.", "Commit and push remain separately approved."],
            "supersedes": existing_descriptors.get(capability_id, {}).get("decision_ref") if operation == "update" else None,
        }
        decision_receipt["content_sha256"] = normalized_receipt_hash(decision_receipt)

        descriptor = deepcopy(assembly.get("descriptor"))
        source = candidate["source"]
        evaluation_id = f"aos10-{capability_id}-{canonical_hash(routing)[:12]}"
        descriptor.update(
            {
                "id": capability_id,
                "lifecycle_state": "active",
                "integration_mode": mode,
                "source": {
                    "kind": "vendor" if mode == "vendor-pin" else "local",
                    "repository": source.get("repository"),
                    "commit": source.get("commit"),
                    "license": source.get("license"),
                    "provenance_ref": f"routing/capability-decisions.json#{decision_id}",
                },
                "eval": {"status": "passing", "case_ids": [evaluation_id]},
                "decision_ref": decision_id,
            }
        )
        errors.extend(self.validate_descriptor(descriptor))

        existing_descriptors[capability_id] = descriptor
        descriptors_document["capabilities"] = [existing_descriptors[key] for key in sorted(existing_descriptors)]
        registry.setdefault("capabilities", {}).pop(capability_id, None)
        registry.setdefault("vendor_skills", {}).pop(capability_id, None)
        if mode == "vendor-pin":
            registry["vendor_skills"][capability_id] = route
        else:
            registry["capabilities"][capability_id] = route

        shadow_errors = self.validate_shadow(capability_id, registry, descriptors_document, routing)
        errors.extend(shadow_errors)
        if errors:
            return {}, {}, errors

        decision_document.setdefault("receipts", []).append(decision_receipt)
        candidate_after = deepcopy(candidate)
        candidate_after["target_capability_id"] = capability_id
        candidate_after["state"] = "active"
        candidate_after.setdefault("decision_history", []).extend(
            {"state": state, "at": created_at, "actor": "capability-lifecycle"}
            for state in ("approval-pending", "integrating", "active")
        )
        lifecycle_receipt = {
            "schema_version": 1,
            "id": f"lifecycle-{canonical_hash(decision_seed)[:24]}",
            "candidate_id": candidate["id"],
            "capability_id": capability_id,
            "action": operation,
            "state": "active",
            "integration_mode": mode,
            "at": created_at,
            "decision_ref": decision_id,
            "source_snapshot_sha256": source["snapshot_sha256"],
            "eval_case_ids": [evaluation_id],
            "manifest_refresh_required": True,
            "commit_created": False,
            "push_performed": False,
        }
        lifecycle_receipt["content_sha256"] = receipt_hash(lifecycle_receipt)
        lifecycle_document.setdefault("receipts", []).append(lifecycle_receipt)
        corpus_by_id = {item.get("id"): item for item in corpus.get("cases", []) if isinstance(item, dict)}
        corpus_by_id[evaluation_id] = {
            "id": evaluation_id,
            "capability_id": capability_id,
            "positive": routing["positive"],
            "negative": routing["negative"],
            "method": "proposed-portfolio-shadow-v1",
            "status": "passing",
        }
        corpus["cases"] = [corpus_by_id[key] for key in sorted(corpus_by_id)]

        if mode == "vendor-pin":
            package_id = candidate["id"]
            package_root = f"vendor/{package_id}"
            package_files = {path: sha256_bytes(content) for path, content in sorted(files.items())}
            license_paths = [path for path in package_files if Path(path).name.upper() in {"LICENSE", "LICENSE.MD", "COPYING", "NOTICE"}]
            package = {
                "id": package_id,
                "root": package_root,
                "repository": source["repository"],
                "commit": source["commit"],
                "license": source["license"],
                "license_path": license_paths[0],
                "integration": "vendor-pin",
                "excluded_upstream_components": assembly.get("excluded_upstream_components", []),
                "files": package_files,
            }
            packages = {item.get("id"): item for item in vendor_lock.get("packages", []) if isinstance(item, dict)}
            packages[package_id] = package
            vendor_lock["packages"] = [packages[key] for key in sorted(packages)]
            vendor_lock["generated_at"] = created_at

        documents = {
            REGISTRY: registry,
            DESCRIPTORS: descriptors_document,
            CAPABILITY_DECISIONS: decision_document,
            LIFECYCLE_LEDGER: lifecycle_document,
            CANDIDATES: candidates_document,
            RESEARCH_DECISIONS: research_decisions,
            VENDOR_LOCK: vendor_lock,
            ROUTING_CORPUS: corpus,
        }
        errors.extend(self.validate_snapshot(documents, files))
        if errors:
            return {}, {}, errors
        desired: dict[str, bytes | None] = {**{path: json_bytes(value) for path, value in documents.items()}, **files}
        desired[MANIFEST] = self.render_working_manifest(desired, created_at, lifecycle_receipt["id"])
        metadata = {
            "operation": f"capability-{operation}",
            "candidate_id": candidate["id"],
            "capability_id": capability_id,
            "integration_mode": mode,
            "decision_id": decision_id,
            "lifecycle_receipt_id": lifecycle_receipt["id"],
            "eval_case_id": evaluation_id,
            "candidate_sha256": canonical_hash(candidate),
            "guard_hashes": {
                relative: sha256_bytes(self.read_bytes(relative) or b"")
                for relative in (
                    "research/research-policy.json",
                    "routing/capability-policy.json",
                    "core/contracts/ownership-policy.json",
                    "evals/agent-os-evals.json",
                )
            },
            "runtime_candidate": candidate_after,
            "runtime_decision": decision_receipt,
        }
        return desired, metadata, []
# fmt: on
