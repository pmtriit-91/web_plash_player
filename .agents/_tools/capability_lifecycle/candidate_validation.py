"""Candidate, descriptor, assembly, routing, and snapshot validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_os_capabilities import INTEGRATION_MODES, tokens, trigger_matches_text
from agent_os_research import FULL_COMMIT, validate_candidate
from capability_lifecycle.platform_privacy import SAFE_ID, SHA256
from capability_lifecycle.shared import (
    CAPABILITY_DECISIONS,
    CONTROL_DOCUMENTS,
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    REGISTRY,
    ROUTING_CORPUS,
    VENDOR_LOCK,
    receipt_valid,
    safe_relative,
    sha256_bytes,
)

SCRIPT_SUFFIXES = {
    ".sh",
    ".bash",
    ".zsh",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".ps1",
    ".bat",
    ".cmd",
    ".exe",
}
ALLOWED_MODES = {"vendor-pin", "adapt-local-skill", "adapt-local-principles"}
ALLOWED_STATES = {"active", "manual-only", "disabled", "quarantined", "deprecated"}
PERMISSION_FIELDS = {
    "filesystem",
    "shell",
    "git",
    "network",
    "secrets",
    "external_state",
}


class CandidateValidationMixin:
    # fmt: off
    def validate_candidate_for_activation(self, candidate: Any) -> list[dict[str, Any]]:
        errors = validate_candidate(candidate)
        if not isinstance(candidate, dict):
            return errors
        if candidate.get("state") != "recommended":
            errors.append({"code": "CANDIDATE_NOT_RECOMMENDED", "state": candidate.get("state")})
        if candidate.get("recommendation") not in ALLOWED_MODES:
            errors.append({"code": "INTEGRATION_MODE_NOT_ACTIVATABLE", "mode": candidate.get("recommendation")})
        recommendation = candidate.get("recommendation")
        gates = candidate.get("gate_results") if isinstance(candidate.get("gate_results"), list) else []
        for gate in gates:
            if gate.get("status") in {"block", "quarantine"}:
                if recommendation == "adapt-local-principles" and gate.get("gate") == "framework-conflict" and gate.get("status") == "block":
                    continue
                errors.append({"code": "CANDIDATE_GATE_NOT_PASSING", "gate": gate.get("gate"), "status": gate.get("status")})
        source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
        if not FULL_COMMIT.fullmatch(str(source.get("commit", ""))):
            errors.append({"code": "FULL_COMMIT_REQUIRED"})
        if not source.get("license"):
            errors.append({"code": "LICENSE_REQUIRED"})
        allowed_licenses = set(self.document("research/research-policy.json", {}).get("license", {}).get("vendor_allowlist", []))
        if source.get("license") not in allowed_licenses:
            errors.append({"code": "LICENSE_NOT_ALLOWED", "license": source.get("license")})
        inventory = candidate.get("inventory") if isinstance(candidate.get("inventory"), dict) else {}
        files = inventory.get("files") if isinstance(inventory.get("files"), list) else []
        expected_snapshot = sha256_bytes(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if source.get("snapshot_sha256") != expected_snapshot:
            errors.append({"code": "CANDIDATE_SNAPSHOT_HASH_INVALID"})
        shadow = candidate.get("shadow_eval") if isinstance(candidate.get("shadow_eval"), dict) else {}
        if shadow.get("status") != "passing":
            errors.append({"code": "SHADOW_EVAL_NOT_PASSING"})
        return errors

    def validate_descriptor(self, descriptor: Any) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        required = {
            "id", "version", "lifecycle_state", "summary", "when_to_use", "not_for",
            "integration_mode", "source", "risk", "permissions", "dependencies",
            "conflicts", "token_profile", "eval", "decision_ref",
        }
        if not isinstance(descriptor, dict) or set(descriptor) != required:
            return [{"code": "DESCRIPTOR_FIELDS_INVALID"}]
        if not SAFE_ID.fullmatch(str(descriptor.get("id", ""))):
            errors.append({"code": "CAPABILITY_ID_INVALID"})
        if descriptor.get("lifecycle_state") not in ALLOWED_STATES:
            errors.append({"code": "CAPABILITY_STATE_INVALID"})
        if descriptor.get("integration_mode") not in INTEGRATION_MODES:
            errors.append({"code": "INTEGRATION_MODE_INVALID"})
        if not isinstance(descriptor.get("summary"), str) or not 10 <= len(descriptor["summary"]) <= 240:
            errors.append({"code": "SUMMARY_INVALID"})
        if not isinstance(descriptor.get("when_to_use"), list) or not descriptor["when_to_use"]:
            errors.append({"code": "WHEN_TO_USE_REQUIRED"})
        if not isinstance(descriptor.get("not_for"), list) or not descriptor["not_for"]:
            errors.append({"code": "NOT_FOR_REQUIRED"})
        permissions = descriptor.get("permissions")
        if not isinstance(permissions, dict) or set(permissions) != PERMISSION_FIELDS:
            errors.append({"code": "PERMISSIONS_INVALID"})
        evaluation = descriptor.get("eval") if isinstance(descriptor.get("eval"), dict) else {}
        if evaluation.get("status") != "passing" or not evaluation.get("case_ids"):
            errors.append({"code": "CAPABILITY_EVAL_NOT_PASSING"})
        return errors

    def inventory_files(self, candidate: dict[str, Any]) -> dict[str, str]:
        files = candidate.get("inventory", {}).get("files", [])
        return {
            str(item.get("path")): str(item.get("sha256"))
            for item in files
            if isinstance(item, dict) and item.get("type") == "file" and SHA256.fullmatch(str(item.get("sha256", "")))
        }

    def prepare_assembly_files(self, candidate: dict[str, Any], assembly: dict[str, Any], mode: str, capability_id: str) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        output: dict[str, bytes] = {}
        inventory = self.inventory_files(candidate)
        expected_prefix = f"vendor/{candidate['id']}/" if mode == "vendor-pin" else f"skills/{capability_id}/"
        records = assembly.get("files") if isinstance(assembly.get("files"), list) else []
        if not records:
            return {}, [{"code": "ASSEMBLY_FILES_REQUIRED"}]
        total = 0
        has_skill = False
        has_license = False
        for item in records:
            if not isinstance(item, dict):
                errors.append({"code": "ASSEMBLY_FILE_INVALID"})
                continue
            try:
                target = safe_relative(str(item.get("target", "")))
            except ValueError:
                errors.append({"code": "ASSEMBLY_TARGET_UNSAFE", "target": item.get("target")})
                continue
            if not target.startswith(expected_prefix) or target in CONTROL_DOCUMENTS:
                errors.append({"code": "ASSEMBLY_TARGET_OUTSIDE_MODE_SCOPE", "target": target})
                continue
            if Path(target).suffix.lower() in SCRIPT_SUFFIXES:
                errors.append({"code": "EXECUTABLE_CONTENT_NOT_ACTIVATABLE", "target": target})
            content_value = item.get("content")
            if not isinstance(content_value, str):
                errors.append({"code": "ASSEMBLY_CONTENT_MUST_BE_TEXT", "target": target})
                continue
            content = content_value.encode("utf-8")
            total += len(content)
            if target.endswith("/SKILL.md"):
                has_skill = True
            if Path(target).name.upper() in {"LICENSE", "LICENSE.MD", "COPYING", "NOTICE"}:
                has_license = True
            if mode == "vendor-pin":
                source_path = str(item.get("source_path", ""))
                actual = sha256_bytes(content)
                if inventory.get(source_path) != actual:
                    errors.append({"code": "VENDOR_BYTE_PROVENANCE_MISMATCH", "target": target, "source_path": source_path})
            output[target] = content
        if total > self.budget():
            errors.append({"code": "ASSEMBLY_BUDGET_EXCEEDED", "bytes": total, "maximum": self.budget()})
        if not has_skill:
            errors.append({"code": "SKILL_MD_REQUIRED"})
        if mode == "vendor-pin" and not has_license:
            errors.append({"code": "VENDOR_LICENSE_FILE_REQUIRED"})
        if mode == "adapt-local-principles":
            principles = assembly.get("derived_principles")
            upstream_hashes = set(inventory.values())
            if not isinstance(principles, list) or not principles or any(not isinstance(item, str) or len(item) < 10 for item in principles):
                errors.append({"code": "DERIVED_PRINCIPLES_REQUIRED"})
            if any(sha256_bytes(content) in upstream_hashes for content in output.values()):
                errors.append({"code": "PRINCIPLES_MODE_CANNOT_COPY_UPSTREAM_BYTES"})
        if len(output) != len(records):
            errors.append({"code": "ASSEMBLY_TARGET_DUPLICATED"})
        return output, errors

    def route_from_documents(self, prompt: str, registry: dict[str, Any], descriptors_document: dict[str, Any]) -> str:
        normalized = prompt.lower()
        prompt_tokens = tokens(prompt)
        descriptors = {item.get("id"): item for item in descriptors_document.get("capabilities", []) if isinstance(item, dict)}
        routes: dict[str, dict[str, Any]] = {}
        for group in ("capabilities", "vendor_skills"):
            for capability_id, route in (registry.get(group) or {}).items():
                if isinstance(route, dict):
                    routes[capability_id] = route
        ranked: list[tuple[int, str]] = []
        for capability_id, route in routes.items():
            descriptor = descriptors.get(capability_id, {})
            if descriptor.get("lifecycle_state") != "active":
                continue
            trigger_values = route.get("triggers", route.get("high_triggers", []))
            matches = [value for value in trigger_values if trigger_matches_text(value, normalized, prompt_tokens)]
            score = 70 + min(20, (len(matches) - 1) * 10) if matches else 0
            if capability_id.replace("_", " ").replace("-", " ") in normalized:
                score += 25
            positive = " ".join([str(descriptor.get("summary", "")), *descriptor.get("when_to_use", [])])
            score += min(25, len(prompt_tokens & tokens(positive)) * 5)
            ranked.append((max(0, min(100, score)), capability_id))
        ranked.sort(reverse=True)
        minimum = 55
        best = ranked[0] if ranked else (0, "standard_feature")
        return best[1] if best[0] >= minimum else "standard_feature"

    def validate_shadow(self, capability_id: str, registry: dict[str, Any], descriptors: dict[str, Any], routing: dict[str, Any]) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        positives = routing.get("positive") if isinstance(routing.get("positive"), list) else []
        negatives = routing.get("negative") if isinstance(routing.get("negative"), list) else []
        if not positives or not negatives:
            return [{"code": "POSITIVE_AND_NEGATIVE_ROUTING_CASES_REQUIRED"}]
        for prompt in positives:
            if not isinstance(prompt, str) or self.route_from_documents(prompt, registry, descriptors) != capability_id:
                errors.append({"code": "PROPOSED_POSITIVE_ROUTE_FAILED", "prompt_sha256": sha256_bytes(str(prompt).encode())})
        for prompt in negatives:
            if not isinstance(prompt, str) or self.route_from_documents(prompt, registry, descriptors) == capability_id:
                errors.append({"code": "PROPOSED_NEGATIVE_ROUTE_FAILED", "prompt_sha256": sha256_bytes(str(prompt).encode())})
        return errors

    def validate_snapshot(self, documents: dict[str, Any], extra_files: dict[str, bytes]) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        registry = documents[REGISTRY]
        descriptor_document = documents[DESCRIPTORS]
        descriptors = descriptor_document.get("capabilities", []) if isinstance(descriptor_document, dict) else []
        descriptor_map = {item.get("id"): item for item in descriptors if isinstance(item, dict)}
        routes = {**(registry.get("capabilities") or {}), **(registry.get("vendor_skills") or {})}
        if set(routes) != set(descriptor_map):
            errors.append({"code": "ROUTE_DESCRIPTOR_COVERAGE_INVALID", "routes": sorted(routes), "descriptors": sorted(descriptor_map)})
        known_decisions: set[str] = set()
        for receipt in documents[CAPABILITY_DECISIONS].get("receipts", []):
            if not isinstance(receipt, dict) or not receipt_valid(receipt):
                errors.append({"code": "CAPABILITY_DECISION_INVALID", "id": receipt.get("id") if isinstance(receipt, dict) else None})
            elif receipt.get("id") in known_decisions:
                errors.append({"code": "CAPABILITY_DECISION_DUPLICATED", "id": receipt.get("id")})
            else:
                known_decisions.add(receipt["id"])
        base_evals = self.document("evals/agent-os-evals.json", {})
        corpus_ids = {
            case.get("id") for case in documents[ROUTING_CORPUS].get("cases", [])
            if isinstance(case, dict) and isinstance(case.get("id"), str)
        }
        corpus_ids.update(
            case.get("id") for case in base_evals.get("cases", [])
            if isinstance(case, dict) and isinstance(case.get("id"), str)
        )
        for capability_id, descriptor in descriptor_map.items():
            errors.extend({**error, "id": capability_id} for error in self.validate_descriptor(descriptor))
            if descriptor.get("decision_ref") not in known_decisions:
                errors.append({"code": "CAPABILITY_DECISION_MISSING", "id": capability_id})
            for case_id in descriptor.get("eval", {}).get("case_ids", []):
                if case_id not in corpus_ids and not str(case_id).startswith(("route-", "router-v2-")):
                    errors.append({"code": "CAPABILITY_EVAL_CASE_MISSING", "id": capability_id, "case_id": case_id})
            for dependency in descriptor.get("dependencies", []):
                if dependency in extra_files:
                    continue
                if not self.path(str(dependency)).exists():
                    errors.append({"code": "CAPABILITY_DEPENDENCY_MISSING", "id": capability_id, "path": dependency})
        referenced_paths: set[str] = set()
        for descriptor in descriptor_map.values():
            referenced_paths.update(str(item) for item in descriptor.get("dependencies", []))
        for route in routes.values():
            referenced_paths.update(str(item) for item in route.get("load", []))
            if route.get("path"):
                referenced_paths.add(f"{route['path']}/SKILL.md")
        for relative in extra_files:
            if relative.endswith("/SKILL.md") and relative not in referenced_paths:
                errors.append({"code": "INSTALLED_SKILL_ORPHANED", "path": relative})

        packages = documents[VENDOR_LOCK].get("packages", [])
        package_ids: set[str] = set()
        package_by_root: dict[str, dict[str, Any]] = {}
        for package in packages if isinstance(packages, list) else []:
            package_id = package.get("id") if isinstance(package, dict) else None
            root = package.get("root") if isinstance(package, dict) else None
            if not isinstance(package_id, str) or package_id in package_ids or not isinstance(root, str):
                errors.append({"code": "VENDOR_PACKAGE_ID_OR_ROOT_INVALID", "id": package_id})
                continue
            package_ids.add(package_id)
            package_by_root[root] = package
            if not FULL_COMMIT.fullmatch(str(package.get("commit", ""))) or not package.get("license"):
                errors.append({"code": "VENDOR_PACKAGE_PROVENANCE_INVALID", "id": package_id})
            for relative, expected_hash in (package.get("files") or {}).items():
                content = extra_files.get(relative)
                if content is None:
                    content = self.read_bytes(relative)
                if content is None or sha256_bytes(content) != expected_hash:
                    errors.append({"code": "VENDOR_PACKAGE_FILE_HASH_INVALID", "id": package_id, "path": relative})
        for capability_id, route in (registry.get("vendor_skills") or {}).items():
            root = route.get("path") if isinstance(route, dict) else None
            package = package_by_root.get(str(root))
            descriptor = descriptor_map.get(capability_id, {})
            if not package or descriptor.get("source", {}).get("commit") != package.get("commit"):
                errors.append({"code": "VENDOR_ROUTE_PACKAGE_MISMATCH", "id": capability_id})
        lifecycle_ids: set[str] = set()
        for receipt in documents[LIFECYCLE_LEDGER].get("receipts", []):
            if not isinstance(receipt, dict) or not receipt_valid(receipt):
                errors.append({"code": "LIFECYCLE_RECEIPT_INVALID"})
            elif receipt.get("id") in lifecycle_ids:
                errors.append({"code": "LIFECYCLE_RECEIPT_DUPLICATED", "id": receipt.get("id")})
            else:
                lifecycle_ids.add(receipt["id"])
        return errors
    # fmt: on
