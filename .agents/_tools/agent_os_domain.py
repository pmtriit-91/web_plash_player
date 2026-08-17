#!/usr/bin/env python3
"""Shared read domain for Agent OS CLI, MCP, and Control Center clients."""

from __future__ import annotations

import argparse
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_os_capabilities import capability_card, capability_cards, validate_catalog
from agent_os_capability_lifecycle import CapabilityLifecycleService, recent_jsonl_lines, usage_receipt_errors
from agent_os_context_memory import ContextMemoryService
from agent_os_lifecycle import doctor
from agent_os_research import status as research_status, validate_registry as validate_research_registry
from agent_os_resolver import resolve

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DEFAULTS_PATH = ROOT / "settings" / "defaults.json"
PROJECT_SETTINGS_PATH = ROOT / "project" / "skill-config.json"
PROJECT_BINDING_PATH = ROOT / "project" / "project-binding.json"
CANDIDATES_PATH = ROOT / "research" / "candidate-registry.json"
DECISIONS_PATH = ROOT / "research" / "decision-history.json"
ACTIVATION_LOG = ROOT / "_telemetry" / "activation-receipts.jsonl"

HARD_LOCKS = {
    "automation.activation_requires_approval": True,
    "automation.background_daemon": False,
    "automation.auto_commit": False,
    "automation.auto_push": False,
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def git_output(*arguments: str) -> str | None:
    try:
        process = subprocess.run(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return process.stdout.strip() if process.returncode == 0 else None


def merge_settings(defaults: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in project.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = deepcopy(value)
    for dotted, value in HARD_LOCKS.items():
        group, field = dotted.split(".", 1)
        merged.setdefault(group, {})[field] = value
    return merged


def validate_project_settings(settings: Any, expected_project_id: str | None = None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(settings, dict):
        return [{"code": "SETTINGS_INVALID"}]
    required = {"schema_version", "project_id", "default_mode", "automation", "connectors", "budgets"}
    allowed = required | {"capability_overrides"}
    if not required <= set(settings) or set(settings) - allowed or settings.get("schema_version") != 1:
        errors.append({"code": "SETTINGS_FIELDS_INVALID", "required": sorted(required)})
    if expected_project_id and settings.get("project_id") != expected_project_id:
        errors.append({"code": "PROJECT_ID_IMMUTABLE"})
    if settings.get("default_mode") not in {"FAST", "STANDARD", "DEEP"}:
        errors.append({"code": "DEFAULT_MODE_INVALID"})
    automation = settings.get("automation") if isinstance(settings.get("automation"), dict) else {}
    expected_automation = {"discovery", "activation_requires_approval", "background_daemon", "auto_commit", "auto_push"}
    if set(automation) != expected_automation:
        errors.append({"code": "AUTOMATION_FIELDS_INVALID"})
    if automation.get("discovery") not in {"event-driven-and-manual", "manual-only", "disabled"}:
        errors.append({"code": "DISCOVERY_POLICY_INVALID"})
    for dotted, expected in HARD_LOCKS.items():
        _, field = dotted.split(".", 1)
        if automation.get(field) is not expected:
            errors.append({"code": "HARD_SAFETY_SETTING_VIOLATION", "setting": dotted, "required": expected})
    connectors = settings.get("connectors") if isinstance(settings.get("connectors"), dict) else {}
    if set(connectors) != {"github", "notebooklm", "mcp-skill-index"} or any(value not in {"optional", "disabled"} for value in connectors.values()):
        errors.append({"code": "CONNECTOR_SETTINGS_INVALID"})
    budgets = settings.get("budgets") if isinstance(settings.get("budgets"), dict) else {}
    if set(budgets) != {"max_candidates_per_scan", "max_snapshot_bytes", "plan_expiry_seconds"}:
        errors.append({"code": "BUDGET_FIELDS_INVALID"})
    ranges = {
        "max_candidates_per_scan": (1, 100),
        "max_snapshot_bytes": (1024, 104857600),
        "plan_expiry_seconds": (60, 3600),
    }
    for field, (minimum, maximum) in ranges.items():
        value = budgets.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            errors.append({"code": "BUDGET_VALUE_INVALID", "field": field, "minimum": minimum, "maximum": maximum})
    overrides = settings.get("capability_overrides", {})
    if not isinstance(overrides, dict) or any(
        not isinstance(capability_id, str) or not capability_id or value not in {"automatic", "manual-only", "disabled"}
        for capability_id, value in overrides.items()
    ):
        errors.append({"code": "CAPABILITY_OVERRIDES_INVALID"})
    return errors


def settings_snapshot() -> dict[str, Any]:
    defaults = load_json(DEFAULTS_PATH, {})
    project = load_json(PROJECT_SETTINGS_PATH, {})
    binding = load_json(PROJECT_BINDING_PATH, {})
    expected_project_id = str(binding.get("project_id") or project.get("project_id", ""))
    errors = validate_project_settings(project, expected_project_id)
    return {
        "ok": not errors,
        "effective": merge_settings(defaults, project),
        "project": project,
        "release_defaults": defaults,
        "precedence": ["core-hard-safety", "session-user-instruction", "project-settings", "release-defaults", "runtime-fallback"],
        "hard_locked": HARD_LOCKS,
        "errors": errors,
    }


def overview() -> dict[str, Any]:
    health = doctor()
    manifest = load_json(ROOT / "_manifest" / "base-release-manifest.json", {})
    status = research_status()
    return {
        "ok": health.get("ok") is True,
        "doctor": health,
        "release": {
            "release_id": manifest.get("release_id"),
            "agent_os_version": manifest.get("agent_os_version"),
            "source_commit": manifest.get("provenance", {}).get("source_commit"),
            "entries": len(manifest.get("entries", [])),
        },
        "git": {
            "head": git_output("rev-parse", "HEAD"),
            "branch": git_output("branch", "--show-current"),
            "dirty": bool(git_output("status", "--porcelain")),
            "remotes": (git_output("remote", "-v") or "").splitlines(),
        },
        "connectors": status.get("connector_health", []),
    }


def skills_list() -> dict[str, Any]:
    validation = validate_catalog()
    history = activation_history()
    usage = {capability_id: len(records) for capability_id, records in history.items()}
    return {"ok": validation.get("ok") is True, "validation": validation, "capabilities": capability_cards(), "usage_counts": usage}


def activation_history() -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    if not ACTIVATION_LOG.is_file():
        return records
    lines = recent_jsonl_lines(ACTIVATION_LOG, 1000)
    allowed = {
        "capability_id",
        "task_hash",
        "task_hash_algorithm",
        "selected_at",
        "confidence",
        "evidence_hashes",
        "evidence_hash_algorithm",
        "outcome",
        "raw_prompt_stored",
        "raw_evidence_stored",
    }
    for line in lines:
        try:
            item = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if usage_receipt_errors(item):
            continue
        redacted = {key: item[key] for key in allowed if key in item}
        records.setdefault(item["capability_id"], []).append(redacted)
    return records


def skill_show(capability_id: str) -> dict[str, Any]:
    card = capability_card(capability_id)
    return {
        "ok": card is not None,
        "capability": card,
        "activation_history": activation_history().get(capability_id, []),
        "raw_prompts_stored": False,
        "raw_evidence_stored": False,
        **({} if card is not None else {"error": {"code": "CAPABILITY_NOT_FOUND", "message": capability_id}}),
    }


def simulate(prompt: str, files: list[str] | None = None, errors: str = "") -> dict[str, Any]:
    arguments = argparse.Namespace(prompt=prompt, files=files or [], errors=errors)
    return resolve(arguments)


def research_snapshot() -> dict[str, Any]:
    status = research_status()
    registry = load_json(CANDIDATES_PATH, {})
    decisions = load_json(DECISIONS_PATH, {})
    validation = validate_research_registry()
    lifecycle = CapabilityLifecycleService()
    runtime_candidates = lifecycle.runtime_candidate_records()
    runtime_decisions = lifecycle.runtime_decision_records()
    return {
        "ok": status.get("ok") is True and validation.get("ok") is True,
        "status": status,
        "candidates": [*registry.get("candidates", []), *runtime_candidates],
        "decisions": [*decisions.get("receipts", []), *runtime_decisions],
        "runtime_state": {
            "candidate_count": len(runtime_candidates),
            "decision_receipt_count": len(runtime_decisions),
            "release_seed_is_operational_authority": False,
        },
        "validation": validation,
    }


def candidate_show(candidate_id: str) -> dict[str, Any]:
    registry = load_json(CANDIDATES_PATH, {})
    runtime = CapabilityLifecycleService().runtime_candidate_records()
    candidate = next(
        (
            item for item in [*registry.get("candidates", []), *runtime]
            if isinstance(item, dict) and item.get("id") == candidate_id
        ),
        None,
    )
    return {
        "ok": candidate is not None,
        "candidate": candidate,
        **({} if candidate is not None else {"error": {"code": "CANDIDATE_NOT_FOUND", "message": candidate_id}}),
    }


def usage_review(capability_id: str | None = None) -> dict[str, Any]:
    result = CapabilityLifecycleService().usage_review()
    if capability_id is None:
        return result
    record = next((item for item in result.get("summary", []) if item.get("capability_id") == capability_id), None)
    return {
        "ok": record is not None,
        "capability": record,
        "malformed_records_ignored": result.get("malformed_records_ignored", 0),
        "privacy_unsafe_records_ignored": result.get("privacy_unsafe_records_ignored", 0),
        "raw_prompts_stored": False,
        "raw_evidence_stored": False,
        "authority": "local-telemetry-only",
        **({} if record is not None else {"error": {"code": "CAPABILITY_NOT_FOUND", "message": capability_id}}),
    }


def lifecycle_snapshot() -> dict[str, Any]:
    service = CapabilityLifecycleService()
    ledger = load_json(ROOT / "routing" / "capability-lifecycle.json", {"receipts": []})
    queue = service.queue()
    usage = service.usage_review()
    return {
        "ok": queue.get("ok") is True and usage.get("ok") is True,
        "release_receipts": ledger.get("receipts", []),
        "transactions": queue,
        "usage": usage,
        "activation_policy": {
            "human_approval_required": True,
            "working_baseline_before_verified_release": True,
            "content_and_manifest_commits_separate": True,
            "push_performed": False,
        },
    }


def memory_snapshot(tier: str = "hot", service: ContextMemoryService | None = None) -> dict[str, Any]:
    service = service or ContextMemoryService()
    health = service.doctor()
    loaded = service.load(tier) if health.get("state") not in {"UNCONFIGURED", "DEGRADED"} else {
        "ok": False,
        "authoritative": False,
        "records": [],
        "tasks": [],
    }
    handoffs = service.list_handoffs()
    return {
        "ok": health.get("state") in {"FRESH", "STALE"},
        "health": health,
        "context": loaded,
        "handoff_count": len(handoffs.get("handoffs", [])),
        "raw_conversation_stored": False,
        "notebooklm_authority": "cold-research-only",
    }


def route_cli(args: argparse.Namespace) -> dict[str, Any]:
    if args.resource == "overview":
        return overview()
    if args.resource == "skills":
        return skills_list()
    if args.resource == "skill":
        return skill_show(args.capability)
    if args.resource == "simulate":
        return simulate(args.prompt, args.files, args.errors)
    if args.resource == "research":
        return research_snapshot()
    if args.resource == "settings":
        return settings_snapshot()
    if args.resource == "candidate":
        return candidate_show(args.candidate)
    if args.resource == "usage":
        return usage_review(args.capability)
    if args.resource == "lifecycle":
        return lifecycle_snapshot()
    if args.resource == "memory":
        return memory_snapshot(args.tier)
    return {"ok": False, "error": {"code": "RESOURCE_NOT_IMPLEMENTED"}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent OS shared read domain")
    sub = parser.add_subparsers(dest="resource", required=True)
    sub.add_parser("overview")
    sub.add_parser("skills")
    skill = sub.add_parser("skill")
    skill.add_argument("--capability", required=True)
    simulation = sub.add_parser("simulate")
    simulation.add_argument("--prompt", required=True)
    simulation.add_argument("--files", nargs="*", default=[])
    simulation.add_argument("--errors", default="")
    sub.add_parser("research")
    sub.add_parser("settings")
    candidate = sub.add_parser("candidate")
    candidate.add_argument("--candidate", required=True)
    usage = sub.add_parser("usage")
    usage.add_argument("--capability")
    sub.add_parser("lifecycle")
    memory = sub.add_parser("memory")
    memory.add_argument("--tier", choices=["hot", "warm", "cold"], default="hot")
    args = parser.parse_args()
    try:
        result = route_cli(args)
    except Exception as exc:
        result = {"ok": False, "error": {"code": exc.__class__.__name__, "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
