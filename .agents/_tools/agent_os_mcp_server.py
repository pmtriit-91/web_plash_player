#!/usr/bin/env python3
"""Optional stdio MCP adapter over the Agent OS V9 canonical tools."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_os_context_memory import ContextMemoryService
from agent_os_continuity_transactions import ContinuityTransactionService
from agent_os_paths import portable_relative
from governed_reasoning.service import GovernedReasoningService

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "universal-agent-os"
SERVER_VERSION = "9.1.0"


def error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "details": details or {}}}


def run_script(arguments: list[str], timeout: int = 30) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    try:
        result = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        return error(
            "INVALID_TOOL_OUTPUT",
            "Agent OS tool did not return JSON.",
            {"returncode": process.returncode, "stdout": process.stdout[-2000:], "stderr": process.stderr[-2000:]},
        )
    if process.returncode != 0 and result.get("ok") is not False:
        return error("TOOL_FAILED", "Agent OS tool failed.", {"returncode": process.returncode, "result": result})
    return result


def normalize_paths(raw_paths: Any) -> list[str]:
    if not isinstance(raw_paths, list):
        raise ValueError("target_files must be a list")
    normalized: list[str] = []
    root = PROJECT_ROOT.resolve()
    for raw in raw_paths:
        value = str(raw)
        if not Path(value).is_absolute():
            value = portable_relative(value)
        candidate = Path(value)
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Path is outside repository root: {raw}")
        normalized.append(resolved.relative_to(root).as_posix())
    return normalized


def lifecycle(command: str) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_lifecycle.py", command])


def tool_doctor(_arguments: dict[str, Any]) -> dict[str, Any]:
    return lifecycle("doctor")


def tool_verify_core(_arguments: dict[str, Any]) -> dict[str, Any]:
    return lifecycle("verify-core")


def tool_verify_adapter(_arguments: dict[str, Any]) -> dict[str, Any]:
    return lifecycle("verify-adapter")


def tool_verify_vendors(_arguments: dict[str, Any]) -> dict[str, Any]:
    return lifecycle("verify-vendors")


def tool_validate_skills(_arguments: dict[str, Any]) -> dict[str, Any]:
    return lifecycle("validate-skills")


def tool_preflight(arguments: dict[str, Any]) -> dict[str, Any]:
    mode = arguments.get("mode")
    if mode not in {"FAST", "STANDARD", "DEEP"}:
        return error("INVALID_ARGUMENT", "mode must be FAST, STANDARD, or DEEP")
    command = [
        ".agents/_tools/preflight.py",
        "--mode",
        str(mode),
        "--files",
        *normalize_paths(arguments.get("target_files", [])),
    ]
    if arguments.get("scan_git_staged"):
        command.append("--scan-git-staged")
    return run_script(command)


def tool_validate_routing(arguments: dict[str, Any]) -> dict[str, Any]:
    command = [".agents/_tools/validate-routing-sync.py"]
    if arguments.get("check_manifest") is False:
        command.append("--skip-manifest")
    return run_script(command)


def tool_resolve_routing(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return error("INVALID_ARGUMENT", "prompt is required")
    command = [
        ".agents/_tools/agent_os_resolver.py",
        "resolve",
        "--prompt",
        prompt,
        "--files",
        *normalize_paths(arguments.get("target_files", [])),
    ]
    if arguments.get("errors"):
        command.extend(["--errors", str(arguments["errors"])])
    return run_script(command)


def tool_list_capabilities(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_domain.py", "skills"])


def tool_show_capability(arguments: dict[str, Any]) -> dict[str, Any]:
    capability = arguments.get("capability")
    if not isinstance(capability, str) or not capability:
        return error("INVALID_ARGUMENT", "capability is required")
    return run_script([".agents/_tools/agent_os_domain.py", "skill", "--capability", capability])


def tool_simulate_routing(arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return error("INVALID_ARGUMENT", "prompt is required")
    command = [
        ".agents/_tools/agent_os_domain.py",
        "simulate",
        "--prompt",
        prompt,
        "--files",
        *normalize_paths(arguments.get("target_files", [])),
    ]
    if arguments.get("errors"):
        command.extend(["--errors", str(arguments["errors"])])
    return run_script(command)


def tool_validate_capability_catalog(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_resolver.py", "validate-catalog"])


def tool_research_status(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_domain.py", "research"])


def tool_validate_research_registry(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_research.py", "validate-registry"])


def tool_effective_settings(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_domain.py", "settings"])


def tool_capability_lifecycle_status(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_domain.py", "lifecycle"])


def tool_usage_review(arguments: dict[str, Any]) -> dict[str, Any]:
    command = [".agents/_tools/agent_os_domain.py", "usage"]
    capability = arguments.get("capability")
    if capability is not None:
        if not isinstance(capability, str) or not capability:
            return error("INVALID_ARGUMENT", "capability must be a non-empty string")
        command.extend(["--capability", capability])
    return run_script(command)


def tool_show_candidate(arguments: dict[str, Any]) -> dict[str, Any]:
    candidate = arguments.get("candidate")
    if not isinstance(candidate, str) or not candidate:
        return error("INVALID_ARGUMENT", "candidate is required")
    return run_script([".agents/_tools/agent_os_domain.py", "candidate", "--candidate", candidate])


def tool_context_memory_doctor(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_context_memory.py", "doctor"])


def tool_context_memory_load(arguments: dict[str, Any]) -> dict[str, Any]:
    tier = arguments.get("tier", "hot")
    if tier not in {"hot", "warm", "cold"}:
        return error("INVALID_ARGUMENT", "tier must be hot, warm, or cold")
    return run_script([".agents/_tools/agent_os_context_memory.py", "load", "--tier", tier])


def tool_context_memory_tasks(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_context_memory.py", "tasks"])


def tool_context_memory_handoffs(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_context_memory.py", "handoffs"])


def tool_context_memory_plan_continue(arguments: dict[str, Any]) -> dict[str, Any]:
    return ContextMemoryService().plan_continue_task(arguments)


def tool_continuity_doctor(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_continuity.py", "doctor"])


def tool_continuity_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    operation = arguments.get("operation")
    service = ContinuityTransactionService()
    if operation == "initialize":
        return service.plan_initialize()
    if operation == "refresh":
        return service.plan_refresh()
    if operation == "migrate":
        return service.plan_migrate()
    if operation == "repair":
        backup = arguments.get("backup")
        if backup is not None and not isinstance(backup, str):
            return error("INVALID_ARGUMENT", "backup must be a string when provided")
        return service.plan_repair(backup)
    if operation == "rollback":
        transaction = arguments.get("transaction")
        if not isinstance(transaction, str) or not transaction:
            return error("INVALID_ARGUMENT", "transaction is required for rollback")
        return service.plan_rollback(transaction)
    return error("INVALID_ARGUMENT", "operation must be initialize, refresh, migrate, repair, or rollback")


def tool_continuity_apply(arguments: dict[str, Any]) -> dict[str, Any]:
    plan = arguments.get("plan")
    confirm = arguments.get("confirm")
    if not isinstance(plan, str) or not plan:
        return error("INVALID_ARGUMENT", "plan is required")
    if confirm is not True:
        return error("WRITE_CONFIRMATION_REQUIRED", "confirm must be true")
    return ContinuityTransactionService().apply(plan, True)


def tool_continuity_transactions(_arguments: dict[str, Any]) -> dict[str, Any]:
    return ContinuityTransactionService().list_transactions()


def tool_client_bridges(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_clients.py", "list"])


def tool_migration_inspect(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_migrate.py", "inspect", "--target", "."])


def tool_publication_audit(_arguments: dict[str, Any]) -> dict[str, Any]:
    return run_script([".agents/_tools/agent_os_publication.py", "audit"])


def _closed(arguments: Any, required: set[str], optional: set[str] | None = None) -> bool:
    return isinstance(arguments, dict) and required <= set(arguments) <= required | (optional or set())


def _reasoning_normalize(action: str, arguments: Any) -> dict[str, Any]:
    fields = {
        "plan": {"request", "policy", "snapshot", "draft", "authority"},
        "challenge": {"request", "plan", "policy", "draft", "authority"},
        "decide": {"request", "plan", "challenge", "policy", "draft", "snapshot", "authority"},
    }[action]
    if not _closed(arguments, fields):
        return error("INVALID_ARGUMENT", "reasoning normalization envelope is invalid")
    authority = arguments["authority"]
    required = {"expected_authority_sha256"} if action == "challenge" else {"current_intent_sha256"}
    allowed = required if action == "challenge" else required | {"current_approval_sha256", "approval_required", "transaction_gates_valid", "constitution_conflict"}
    if not isinstance(authority, dict) or not required <= set(authority) <= allowed:
        return error("INVALID_ARGUMENT", "reasoning authority envelope is invalid")
    service = GovernedReasoningService(ROOT)
    if action == "plan":
        return service.normalize_plan(arguments["request"], arguments["policy"], arguments["snapshot"], arguments["draft"], **authority)
    if action == "challenge":
        return service.normalize_challenge(arguments["request"], arguments["plan"], arguments["policy"], arguments["draft"], **authority)
    return service.normalize_decision(arguments["request"], arguments["plan"], arguments["challenge"], arguments["policy"], arguments["draft"], arguments["snapshot"], **authority)


def tool_reasoning_validate(arguments: dict[str, Any]) -> dict[str, Any]:
    if not _closed(arguments, {"kind", "artifact"}) or arguments.get("kind") not in {"request", "plan", "challenge", "decision", "policy"}:
        return error("INVALID_ARGUMENT", "kind and artifact are required")
    return GovernedReasoningService(ROOT).validate_artifact(arguments["kind"], arguments["artifact"])


def tool_reasoning_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    return _reasoning_normalize("plan", arguments)


def tool_reasoning_challenge(arguments: dict[str, Any]) -> dict[str, Any]:
    return _reasoning_normalize("challenge", arguments)


def tool_reasoning_decide(arguments: dict[str, Any]) -> dict[str, Any]:
    return _reasoning_normalize("decide", arguments)


def tool_reasoning_persist(arguments: dict[str, Any]) -> dict[str, Any]:
    required, optional = {"kind", "receipt"}, {"source_receipt_ids", "expiry_seconds"}
    sources, expiry = arguments.get("source_receipt_ids", []) if isinstance(arguments, dict) else None, arguments.get("expiry_seconds", 900) if isinstance(arguments, dict) else None
    if not _closed(arguments, required, optional) or arguments.get("kind") not in {"plan", "challenge", "decision"} or not isinstance(arguments.get("receipt"), dict) or not isinstance(sources, list) or len(sources) > 16 or not all(isinstance(item, str) and item for item in sources) or type(expiry) is not int:
        return error("INVALID_ARGUMENT", "receipt persistence envelope is invalid")
    return GovernedReasoningService(ROOT).plan_receipt(arguments["kind"], arguments["receipt"], sources, expiry_seconds=expiry)


def tool_reasoning_apply(arguments: dict[str, Any]) -> dict[str, Any]:
    if not _closed(arguments, {"plan"}, {"confirm"}) or not isinstance(arguments.get("plan"), str) or not arguments["plan"]:
        return error("INVALID_ARGUMENT", "plan is required")
    if arguments.get("confirm") is not True:
        return error("WRITE_CONFIRMATION_REQUIRED", "confirm must be true")
    return GovernedReasoningService(ROOT).apply_receipt(arguments["plan"], confirm=True)


def tool_reasoning_recover(arguments: dict[str, Any]) -> dict[str, Any]:
    if not _closed(arguments, {"transaction"}, {"confirm"}) or not isinstance(arguments.get("transaction"), str) or not arguments["transaction"]:
        return error("INVALID_ARGUMENT", "transaction is required")
    if arguments.get("confirm") is not True:
        return error("WRITE_CONFIRMATION_REQUIRED", "confirm must be true")
    return GovernedReasoningService(ROOT).recover_receipt(arguments["transaction"], confirm=True)


def _closed_schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": properties}


_OBJECT = {"type": "object"}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_IDENTIFIER = {"type": "string", "pattern": "^[0-9a-f]{24}$"}
_RECEIPT_IDENTIFIER = {"type": "string", "pattern": "^(plan|challenge|decision)-[0-9a-f]{24}$"}
_AUTHORITY = _closed_schema(
    ["current_intent_sha256"],
    {
        "current_intent_sha256": _HASH,
        "current_approval_sha256": {"oneOf": [_HASH, {"type": "null"}]},
        "approval_required": {"type": "boolean"},
        "transaction_gates_valid": {"type": "boolean"},
        "constitution_conflict": {"type": "boolean"},
    },
)
_CHALLENGE_AUTHORITY = _closed_schema(["expected_authority_sha256"], {"expected_authority_sha256": _HASH})
REASONING_TOOLS = [
    {"name": "agent_os/reasoning_validate", "description": "Validate one governed-reasoning artifact without writing.", "inputSchema": _closed_schema(["kind", "artifact"], {"kind": {"type": "string", "enum": ["request", "plan", "challenge", "decision", "policy"]}, "artifact": _OBJECT})},
    {"name": "agent_os/reasoning_plan", "description": "Normalize one bounded governed plan without writing.", "inputSchema": _closed_schema(["request", "policy", "snapshot", "draft", "authority"], {"request": _OBJECT, "policy": _OBJECT, "snapshot": _OBJECT, "draft": _OBJECT, "authority": _AUTHORITY})},
    {"name": "agent_os/reasoning_challenge", "description": "Normalize one adversarial challenge without writing.", "inputSchema": _closed_schema(["request", "plan", "policy", "draft", "authority"], {"request": _OBJECT, "plan": _OBJECT, "policy": _OBJECT, "draft": _OBJECT, "authority": _CHALLENGE_AUTHORITY})},
    {"name": "agent_os/reasoning_decide", "description": "Normalize one deterministic governed decision without writing.", "inputSchema": _closed_schema(["request", "plan", "challenge", "policy", "draft", "snapshot", "authority"], {"request": _OBJECT, "plan": _OBJECT, "challenge": _OBJECT, "policy": _OBJECT, "draft": _OBJECT, "snapshot": _OBJECT, "authority": _AUTHORITY})},
    {"name": "agent_os/reasoning_persist", "description": "Plan persistence of one immutable reasoning receipt without applying it.", "inputSchema": _closed_schema(["kind", "receipt"], {"kind": {"type": "string", "enum": ["plan", "challenge", "decision"]}, "receipt": _OBJECT, "source_receipt_ids": {"type": "array", "maxItems": 16, "items": _RECEIPT_IDENTIFIER}, "expiry_seconds": {"type": "integer", "minimum": 60, "maximum": 3600}})},
    {"name": "agent_os/reasoning_apply", "description": "Apply one reviewed reasoning persistence plan with explicit confirmation.", "inputSchema": _closed_schema(["plan", "confirm"], {"plan": _IDENTIFIER, "confirm": {"const": True}})},
    {"name": "agent_os/reasoning_recover", "description": "Recover one interrupted reasoning transaction with explicit confirmation.", "inputSchema": _closed_schema(["transaction", "confirm"], {"transaction": _IDENTIFIER, "confirm": {"const": True}})},
]


HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "agent_os/doctor": tool_doctor,
    "agent_os/verify_core": tool_verify_core,
    "agent_os/verify_adapter": tool_verify_adapter,
    "agent_os/verify_vendors": tool_verify_vendors,
    "agent_os/validate_skills": tool_validate_skills,
    "agent_os/run_preflight": tool_preflight,
    "agent_os/validate_routing": tool_validate_routing,
    "agent_os/resolve_routing": tool_resolve_routing,
    "agent_os/list_capabilities": tool_list_capabilities,
    "agent_os/show_capability": tool_show_capability,
    "agent_os/simulate_routing": tool_simulate_routing,
    "agent_os/validate_capability_catalog": tool_validate_capability_catalog,
    "agent_os/research_status": tool_research_status,
    "agent_os/validate_research_registry": tool_validate_research_registry,
    "agent_os/effective_settings": tool_effective_settings,
    "agent_os/capability_lifecycle_status": tool_capability_lifecycle_status,
    "agent_os/usage_review": tool_usage_review,
    "agent_os/show_candidate": tool_show_candidate,
    "agent_os/context_memory_doctor": tool_context_memory_doctor,
    "agent_os/context_memory_load": tool_context_memory_load,
    "agent_os/context_memory_tasks": tool_context_memory_tasks,
    "agent_os/context_memory_handoffs": tool_context_memory_handoffs,
    "agent_os/context_memory_plan_continue": tool_context_memory_plan_continue,
    "agent_os/continuity_doctor": tool_continuity_doctor,
    "agent_os/continuity_plan": tool_continuity_plan,
    "agent_os/continuity_apply": tool_continuity_apply,
    "agent_os/continuity_transactions": tool_continuity_transactions,
    "agent_os/client_bridges": tool_client_bridges,
    "agent_os/migration_inspect": tool_migration_inspect,
    "agent_os/publication_audit": tool_publication_audit,
    "agent_os/reasoning_validate": tool_reasoning_validate,
    "agent_os/reasoning_plan": tool_reasoning_plan,
    "agent_os/reasoning_challenge": tool_reasoning_challenge,
    "agent_os/reasoning_decide": tool_reasoning_decide,
    "agent_os/reasoning_persist": tool_reasoning_persist,
    "agent_os/reasoning_apply": tool_reasoning_apply,
    "agent_os/reasoning_recover": tool_reasoning_recover,
}

TOOLS = [
    *REASONING_TOOLS,
    {
        "name": "agent_os/doctor",
        "description": "Derive Agent OS state and report Core, Adapter, bridge, Genesis source/projection, vendor, and skill evidence.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/verify_core",
        "description": "Verify release-owned files against the split base release manifest.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/verify_adapter",
        "description": "Validate project binding and Adapter evidence without loading Project Memory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/verify_vendors",
        "description": "Verify vendor commit, license metadata, allowlisted paths, and file hashes.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/validate_skills",
        "description": "Validate release and governed vendor skill frontmatter and context-size limits.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/run_preflight",
        "description": "Validate mode and repository-local target-file boundaries before writes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["FAST", "STANDARD", "DEEP"]},
                "target_files": {"type": "array", "items": {"type": "string"}},
                "scan_git_staged": {"type": "boolean"},
            },
            "required": ["mode", "target_files"],
        },
    },
    {
        "name": "agent_os/validate_routing",
        "description": "Validate routing, lifecycle paths, vendor lock, skills, and Core integrity.",
        "inputSchema": {
            "type": "object",
            "properties": {"check_manifest": {"type": "boolean"}},
        },
    },
    {
      "name": "agent_os/resolve_routing",
        "description": "Resolve one internal workflow and one primary capability for a task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "target_files": {"type": "array", "items": {"type": "string"}},
                "errors": {"type": "string"},
            },
            "required": ["prompt"],
      },
    },
    {
        "name": "agent_os/list_capabilities",
        "description": "List active and inactive capability cards with purpose, provenance, risk, permissions, and eval status.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/show_capability",
        "description": "Explain one capability and its route without activating it.",
        "inputSchema": {
            "type": "object",
            "properties": {"capability": {"type": "string"}},
            "required": ["capability"],
        },
    },
    {
        "name": "agent_os/simulate_routing",
        "description": "Simulate explainable workflow and capability selection and report alternatives and capability gaps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "target_files": {"type": "array", "items": {"type": "string"}},
                "errors": {"type": "string"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "agent_os/validate_capability_catalog",
        "description": "Validate descriptor coverage, decisions, dependencies, lifecycle states, and vendor provenance.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/research_status",
        "description": "Report optional connector configuration and candidate/decision counts without contacting the network.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/validate_research_registry",
        "description": "Validate research connector isolation, candidate transitions, policy, and immutable receipt hashes.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/effective_settings",
        "description": "Show release defaults, project settings, hard locks, and effective precedence without writing them.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/capability_lifecycle_status",
        "description": "Read lifecycle receipts, pending plans, and redacted usage review without mutating state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/usage_review",
        "description": "Review redacted local capability usage metadata; raw prompts are never returned.",
        "inputSchema": {
            "type": "object",
            "properties": {"capability": {"type": "string"}},
        },
    },
    {
        "name": "agent_os/show_candidate",
        "description": "Show one tracked research candidate without activating, importing, or executing it.",
        "inputSchema": {
            "type": "object",
            "properties": {"candidate": {"type": "string"}},
            "required": ["candidate"],
        },
    },
    {
        "name": "agent_os/context_memory_doctor",
        "description": "Diagnose project-bound Context Memory freshness, contamination, authority conflicts, and task overlap without writing.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/context_memory_load",
        "description": "Read one Context Memory tier with explicit freshness and authority metadata; stale memory is never promoted to authority.",
        "inputSchema": {
            "type": "object",
            "properties": {"tier": {"type": "string", "enum": ["hot", "warm", "cold"]}},
        },
    },
    {
        "name": "agent_os/context_memory_tasks",
        "description": "Read the project-owned active-task ledger and overlap/stale-base diagnostics.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/context_memory_handoffs",
        "description": "Read hash-verifiable project handoff receipts without mutating tasks or memory.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/context_memory_plan_continue",
        "description": "Plan an exact active-task continuation/rebase at current Git HEAD without applying it.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["task_id", "owner", "evidence"],
            "properties": {
                "task_id": {"type": "string"},
                "owner": {"type": "string"},
                "evidence": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string"}
                }
            }
        },
    },
    {
        "name": "agent_os/continuity_doctor",
        "description": "Diagnose the project continuity catalog, critical-set topology, source authority readiness, graph integrity, and registry/profile drift without writing.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/continuity_plan",
        "description": "Create a reviewable continuity initialize, refresh, migrate, repair, or rollback plan; no application state is applied.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["operation"],
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["initialize", "refresh", "migrate", "repair", "rollback"]
                },
                "backup": {"type": "string"},
                "transaction": {"type": "string"}
            }
        },
    },
    {
        "name": "agent_os/continuity_apply",
        "description": "Apply one reviewed continuity plan with backup, rollback verification, and durable receipt; explicit confirm=true is mandatory.",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["plan", "confirm"],
            "properties": {
                "plan": {"type": "string"},
                "confirm": {"const": True}
            }
        },
    },
    {
        "name": "agent_os/continuity_transactions",
        "description": "List validated application-owned continuity transaction receipts without mutating state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/client_bridges",
        "description": "List governed repository-local client bridges and their discovery evidence from the canonical registry.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/migration_inspect",
        "description": "Read the current repository migration family, protected inventory, Git cleanliness, and bridge compatibility without writing.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_os/publication_audit",
        "description": "Audit project license, disclosure policy, third-party notices, immutable CI pins, secret signatures, and manual publication gates without contacting the network or changing state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def mcp_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
        "isError": not data.get("ok", False),
    }


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(name)
        if not handler:
            data = error("INVALID_ARGUMENT", f"Unknown tool: {name}")
        else:
            try:
                data = handler(params.get("arguments") or {})
            except subprocess.TimeoutExpired:
                data = error("TOOL_TIMEOUT", "Agent OS tool timed out")
            except Exception as exc:  # MCP boundary must return structured errors.
                data = error("INTERNAL_ERROR", str(exc))
        return {"jsonrpc": "2.0", "id": request_id, "result": mcp_result(data)}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line))
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Invalid request: {exc}"},
            }
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
