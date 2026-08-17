#!/usr/bin/env python3
"""Shared disposable-repository fixtures for capability lifecycle acceptance shards."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from agent_os_capability_lifecycle import (
    CANDIDATES,
    CAPABILITY_DECISIONS,
    DESCRIPTORS,
    LIFECYCLE_LEDGER,
    MANIFEST,
    REGISTRY,
    RESEARCH_DECISIONS,
    ROUTING_CORPUS,
    VENDOR_LOCK,
    CapabilityLifecycleService,
    json_bytes,
    sha256_bytes,
)
from agent_os_research import normalized_receipt_hash

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)
FULL_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def candidate(candidate_id: str = "widget-helper", commit: str = FULL_COMMIT, license_name: str = "MIT", skill: str | None = None) -> tuple[dict, str]:
    content = skill or "---\nname: widget-helper\ndescription: Coordinate widget-specific release assembly safely.\n---\n\n# Widget Helper\n\nUse deterministic widget assembly.\n"
    files = [{"path": "SKILL.md", "type": "file", "bytes": len(content.encode()), "sha256": sha256_bytes(content.encode())}]
    snapshot = sha256_bytes(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
    value = {
        "schema_version": 1,
        "id": candidate_id,
        "state": "recommended",
        "source": {
            "connector": "local", "repository": f"https://example.invalid/{candidate_id}",
            "commit": commit, "license": license_name, "snapshot_sha256": snapshot,
        },
        "discovered_at": "2026-07-19T00:00:00Z",
        "evidence": [{"kind": "frontmatter", "name": "widget-helper", "description": "Coordinate widget-specific release assembly safely."}],
        "inventory": {"file_count": 1, "total_bytes": len(content.encode()), "files": files},
        "gate_results": [
            {"gate": gate, "status": "pass", "reason_codes": []}
            for gate in ("provenance", "license", "structure", "executable-content", "prompt-integrity", "framework-conflict", "portfolio-overlap", "shadow-routing")
        ],
        "overlap": {"conflict": False},
        "shadow_eval": {"method": "static-shadow-routing-v1", "status": "passing"},
        "recommendation": "adapt-local-skill",
        "decision_history": [
            {"state": state, "at": "2026-07-19T00:00:00Z", "actor": "research-engine"}
            for state in ("discovered", "pinned", "evaluating", "recommended")
        ],
    }
    return value, content


def assembly(candidate_value: dict, content: str, version: str = "1.0.0") -> dict:
    capability_id = "widget-helper"
    return {
        "schema_version": 1,
        "candidate_id": candidate_value["id"],
        "capability_id": capability_id,
        "integration_mode": "adapt-local-skill",
        "files": [{"target": f"skills/{capability_id}/SKILL.md", "content": content}],
        "descriptor": {
            "version": version,
            "summary": "Coordinate widget-specific release assembly with deterministic safety checks.",
            "when_to_use": ["A task explicitly asks for widget assembly or widget release coordination."],
            "not_for": ["General features that do not involve widget assembly."],
            "risk": {"level": "low", "notes": "Instruction-only local adaptation."},
            "permissions": {"filesystem": "task-scoped", "shell": "none", "git": "none", "network": "none", "secrets": "none", "external_state": "none"},
            "dependencies": [f"skills/{capability_id}/SKILL.md"],
            "conflicts": [],
            "token_profile": {"metadata_budget": "tiny", "activation_budget": "small"},
        },
        "route": {
            "mode": "STANDARD", "triggers": ["widget assembly", "widget release"],
            "load": [f"skills/{capability_id}/SKILL.md"], "checks": ["widget contract", "focused tests"],
        },
        "routing": {
            "positive": ["Coordinate this widget assembly and widget release."],
            "negative": ["Prepare vegetable soup for dinner."],
        },
        "rationale": "Adapt the small instruction workflow locally because the approved candidate passed every static and shadow gate.",
    }


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def reason(result: dict, code: str) -> bool:
    return code in result.get("reason_codes", [])


def snapshot(agent: Path) -> dict[str, bytes]:
    return {
        "memory": (agent / "skills/project-memory/SKILL.md").read_bytes(),
        "local": (agent / "skills/project-local/local.md").read_bytes(),
        "application": (agent.parent / "application.txt").read_bytes(),
    }


def _decision(receipt_id: str, capability_id: str) -> dict:
    value = {
        "id": receipt_id,
        "candidate_id": None,
        "capability_ids": [capability_id],
        "decided_at": "2026-07-19T00:00:00Z",
        "decision": "native",
        "evidence": ["fixture"],
        "rationale": "Keep the deterministic fixture fallback capability.",
        "constraints": ["test fixture only"],
        "supersedes": None,
    }
    value["content_sha256"] = normalized_receipt_hash(value)
    return value


def _standard_descriptor() -> dict:
    return {
        "id": "standard_feature",
        "version": "1.0.0",
        "lifecycle_state": "active",
        "summary": "Provide a deterministic fallback for ordinary fixture work.",
        "when_to_use": ["No specialized fixture capability has strong evidence."],
        "not_for": ["A specialized task with an explicit capability trigger."],
        "integration_mode": "native",
        "source": {
            "kind": "local",
            "repository": None,
            "commit": None,
            "license": None,
            "provenance_ref": "fixture",
        },
        "risk": {"level": "low", "notes": "Fixture-only fallback."},
        "permissions": {
            "filesystem": "task-scoped",
            "shell": "none",
            "git": "none",
            "network": "none",
            "secrets": "none",
            "external_state": "none",
        },
        "dependencies": [],
        "conflicts": [],
        "token_profile": {"metadata_budget": "tiny", "activation_budget": "small"},
        "eval": {"status": "passing", "case_ids": ["router-v2-fallback"]},
        "decision_ref": "fixture-native",
    }


def fixture(parent: Path, name: str) -> tuple[Path, Path, CapabilityLifecycleService]:
    project = parent / name
    agent = project / ".agents"
    for relative in (
        "routing", "research", "vendor", "evals", "project", "skills/project-memory",
        "skills/project-local", "core/contracts", "_manifest", "_telemetry",
    ):
        (agent / relative).mkdir(parents=True, exist_ok=True)
    write_json(agent / REGISTRY, {
        "version": "9.1.0", "capabilities": {
            "standard_feature": {"mode": "STANDARD", "triggers": ["feature"], "load": [], "checks": ["focused tests"]}
        }, "vendor_skills": {},
    })
    write_json(agent / DESCRIPTORS, {"schema_version": 1, "agent_os_version": "9.1.0", "capabilities": [_standard_descriptor()]})
    write_json(agent / CAPABILITY_DECISIONS, {"schema_version": 1, "receipts": [_decision("fixture-native", "standard_feature")]})
    write_json(agent / LIFECYCLE_LEDGER, {"schema_version": 1, "append_only": True, "receipts": []})
    write_json(agent / CANDIDATES, {"schema_version": 1, "authority": "research-candidates-only", "candidates": []})
    write_json(agent / RESEARCH_DECISIONS, {"schema_version": 1, "append_only": True, "receipts": []})
    write_json(agent / VENDOR_LOCK, {"schema_version": 1, "generated_at": "2026-07-19T00:00:00Z", "packages": [], "research_sources": []})
    write_json(agent / ROUTING_CORPUS, {"schema_version": 1, "cases": []})
    write_json(agent / "evals/agent-os-evals.json", {"version": "9.1.0", "cases": [{"id": "router-v2-fallback", "type": "routing"}]})
    write_json(agent / "research/research-policy.json", {
        "license": {"vendor_allowlist": ["MIT", "Apache-2.0"]},
        "execution": {"upstream_code_allowed": False},
        "activation": {"human_approval_required": True},
    })
    write_json(agent / "routing/capability-policy.json", {"schema_version": 1, "activation": {"minimum_confidence": 55}})
    write_json(agent / "core/contracts/ownership-policy.json", {
        "schema_version": 1,
        "agent_os_version": "9.1.0",
        "release_owned_roots": ["_manifest", "_telemetry", "_tools", "core", "evals", "research", "routing", "skills", "vendor"],
        "application_owned_scopes": ["project/**", "skills/project-memory/**", "skills/project-local/**"],
        "runtime_scopes": ["_runtime/**", "_telemetry/*.jsonl", "**/__pycache__/**", "**/*.pyc"],
        "manifest_self": MANIFEST,
    })
    write_json(agent / "project/skill-config.json", {
        "schema_version": 1,
        "project_id": "fixture",
        "budgets": {"max_snapshot_bytes": 1048576},
    })
    (agent / "skills/project-memory/SKILL.md").write_text("protected project memory\n", encoding="utf-8")
    (agent / "skills/project-local/local.md").write_text("protected local capability\n", encoding="utf-8")
    (project / "application.txt").write_text("protected application source\n", encoding="utf-8")
    (project / ".gitignore").write_text(".agents/_runtime/\n.agents/_telemetry/*.jsonl\n**/__pycache__/\n", encoding="utf-8")
    git(project, "init", "-q")
    git(project, "config", "user.name", "Agent OS Test")
    git(project, "config", "user.email", "agent-os@example.invalid")
    service = CapabilityLifecycleService(agent, now=lambda: NOW)
    (agent / MANIFEST).write_bytes(service.render_working_manifest({}, "2026-07-19T00:00:00Z", "fixture"))
    git(project, "add", ".")
    git(project, "commit", "-qm", "fixture baseline")
    return project, agent, service
