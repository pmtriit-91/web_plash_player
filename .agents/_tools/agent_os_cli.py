#!/usr/bin/env python3
"""Unified dependency-free CLI over Agent OS domain and transaction services."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_os_capability_lifecycle import CapabilityLifecycleService
from agent_os_context_memory import ContextMemoryService
from agent_os_continuity import doctor as continuity_doctor
from agent_os_continuity_portability import (
    ContinuityPortabilityService,
    read_regular_bounded,
)
from agent_os_continuity_transactions import ContinuityTransactionService
from agent_os_domain import (
    lifecycle_snapshot,
    research_snapshot,
    settings_snapshot,
    simulate,
    skill_show,
    skills_list,
    usage_review,
)
from agent_os_genesis import doctor as genesis_doctor
from agent_os_genesis_transactions import GenesisService
from agent_os_lifecycle import doctor
from agent_os_publication import audit as publication_audit
from agent_os_transactions import TransactionService
from governed_reasoning.service import GovernedReasoningService

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
JSON_INPUT_MAX_BYTES = 1048576


def run_json(arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run([sys.executable, *arguments], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=120, check=False)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": {"code": "INVALID_TOOL_OUTPUT", "message": result.stderr[-2000:]}}


def read_json_input(path: str) -> tuple[Any | None, str | None]:
    try:
        source = Path(path).expanduser()
        content, read_error = read_regular_bounded(source, JSON_INPUT_MAX_BYTES)
        if content is None:
            if read_error == "PORTABILITY_FILE_BOUND_EXCEEDED":
                raise ValueError("input exceeds 1048576-byte limit")
            if read_error == "PORTABILITY_FILE_CHANGED_DURING_READ":
                raise ValueError("input changed while being read")
            raise ValueError("input must be a readable regular non-symlink file")
        return json.loads(content.decode("utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return None, str(exc)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-os", description="Universal Agent OS command line")
    top = parser.add_subparsers(dest="area", required=True)
    top.add_parser("doctor")

    skills = top.add_parser("skills").add_subparsers(dest="action", required=True)
    skills.add_parser("list")
    for action in ("show", "explain"):
        command = skills.add_parser(action)
        command.add_argument("capability")
    simulation = skills.add_parser("simulate")
    simulation.add_argument("prompt")
    usage = skills.add_parser("usage")
    usage.add_argument("capability", nargs="?")
    plan_integration = skills.add_parser("plan-integration")
    plan_integration.add_argument("--candidate", required=True)
    plan_integration.add_argument("--assembly", required=True)
    apply_integration = skills.add_parser("apply-integration")
    apply_integration.add_argument("--plan", required=True)
    apply_integration.add_argument("--confirm", action="store_true")
    plan_state = skills.add_parser("plan-state")
    plan_state.add_argument("capability")
    plan_state.add_argument("--state", choices=["manual-only", "disabled", "quarantined", "deprecated"], required=True)
    plan_state.add_argument("--replacement")
    plan_rollback = skills.add_parser("plan-rollback")
    plan_rollback.add_argument("--transaction", required=True)
    apply_rollback = skills.add_parser("apply-rollback")
    apply_rollback.add_argument("--plan", required=True)
    apply_rollback.add_argument("--confirm", action="store_true")
    apply_state = skills.add_parser("apply-state")
    apply_state.add_argument("--plan", required=True)
    apply_state.add_argument("--confirm", action="store_true")
    record_usage = skills.add_parser("record-usage")
    record_usage.add_argument("capability")
    record_usage.add_argument("--task", required=True)
    record_usage.add_argument("--confidence", choices=["low", "medium", "high"], required=True)
    record_usage.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="Evidence signal hashed locally before persistence; raw text is never stored.",
    )
    record_usage.add_argument("--outcome", choices=["selected", "declined", "completed", "failed"], required=True)
    check_update = skills.add_parser("check-update")
    check_update.add_argument("capability")
    check_update.add_argument("--candidate", required=True)

    research = top.add_parser("research").add_subparsers(dest="action", required=True)
    research.add_parser("status")
    discover = research.add_parser("discover")
    discover.add_argument("--connector", choices=["github", "notebooklm", "local", "mcp-skill-index"], required=True)
    discover.add_argument("--source", required=True)
    discover.add_argument("--candidate-id", required=True)
    discover.add_argument("--repository", required=True)
    discover.add_argument("--commit", default="")
    discover.add_argument("--license", default="")
    discover.add_argument("--positive", action="append", default=[])
    discover.add_argument("--negative", action="append", default=[])
    compare = research.add_parser("compare")
    compare.add_argument("candidate_file")

    update = top.add_parser("update").add_subparsers(dest="action", required=True)
    plan_update = update.add_parser("plan")
    plan_update.add_argument("source")
    apply_update = update.add_parser("apply")
    apply_update.add_argument("source")
    apply_update.add_argument("--plan", required=True)
    apply_update.add_argument("--confirm", action="store_true")
    rollback = update.add_parser("rollback")
    rollback.add_argument("--transaction", required=True)
    rollback.add_argument("--confirm", action="store_true")

    migration = top.add_parser("migration").add_subparsers(dest="action", required=True)
    migration_inspect = migration.add_parser("inspect")
    migration_inspect.add_argument("--target", default=".")
    migration_plan = migration.add_parser("plan")
    migration_plan.add_argument("--source", required=True)
    migration_plan.add_argument("--target", default=".")
    migration_apply = migration.add_parser("apply")
    migration_apply.add_argument("--target", default=".")
    migration_apply.add_argument("--plan", required=True)
    migration_apply.add_argument("--confirm", action="store_true")
    migration_rollback = migration.add_parser("rollback")
    migration_rollback.add_argument("--target", default=".")
    migration_rollback.add_argument("--transaction", required=True)
    migration_rollback.add_argument("--confirm", action="store_true")

    clients = top.add_parser("clients").add_subparsers(dest="action", required=True)
    clients.add_parser("list")
    clients.add_parser("validate")

    publication = top.add_parser("publication").add_subparsers(dest="action", required=True)
    publication.add_parser("audit")

    settings = top.add_parser("settings").add_subparsers(dest="action", required=True)
    settings.add_parser("show")
    serve = settings.add_parser("serve")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--session-seconds", type=int, default=1800)
    plan_settings = settings.add_parser("plan")
    plan_settings.add_argument("input")
    apply_settings = settings.add_parser("apply")
    apply_settings.add_argument("--plan", required=True)
    apply_settings.add_argument("--confirm", action="store_true")
    lifecycle = top.add_parser("lifecycle").add_subparsers(dest="action", required=True)
    lifecycle.add_parser("status")
    recover_lifecycle = lifecycle.add_parser("recover")
    recover_lifecycle.add_argument("--confirm", action="store_true")

    genesis = top.add_parser("genesis").add_subparsers(dest="action", required=True)
    genesis.add_parser("doctor")
    genesis.add_parser("plan-migration")
    genesis_apply_migration = genesis.add_parser("apply-migration")
    genesis_apply_migration.add_argument("--plan", required=True)
    genesis_apply_migration.add_argument("--confirm", action="store_true")
    genesis_plan_confirmation = genesis.add_parser("plan-confirmation")
    genesis_plan_confirmation.add_argument("--input", required=True)
    genesis_apply_confirmation = genesis.add_parser("apply-confirmation")
    genesis_apply_confirmation.add_argument("--plan", required=True)
    genesis_apply_confirmation.add_argument("--confirm", action="store_true")
    genesis.add_parser("projection")
    genesis.add_parser("plan-projection")
    genesis_apply_projection = genesis.add_parser("apply-projection")
    genesis_apply_projection.add_argument("--plan", required=True)
    genesis_apply_projection.add_argument("--confirm", action="store_true")
    genesis_recover = genesis.add_parser("recover")
    genesis_recover.add_argument("--confirm", action="store_true")

    reasoning = top.add_parser("reasoning").add_subparsers(dest="action", required=True)
    reasoning_validate = reasoning.add_parser("validate")
    reasoning_validate.add_argument("kind", choices=["request", "plan", "challenge", "decision", "policy"])
    reasoning_validate.add_argument("input")
    for action in ("plan", "challenge", "decide"):
        reasoning.add_parser(action).add_argument("input")
    reasoning_persist = reasoning.add_parser("persist")
    reasoning_persist.add_argument("kind", choices=["plan", "challenge", "decision"])
    reasoning_persist.add_argument("input")
    reasoning_persist.add_argument("--source-receipt-id", action="append", default=[])
    reasoning_persist.add_argument("--expiry-seconds", type=int, default=900)
    reasoning_apply = reasoning.add_parser("apply")
    reasoning_apply.add_argument("--plan", required=True)
    reasoning_apply.add_argument("--confirm", action="store_true")
    reasoning_recover = reasoning.add_parser("recover")
    reasoning_recover.add_argument("--transaction", required=True)
    reasoning_recover.add_argument("--confirm", action="store_true")

    memory = top.add_parser("memory").add_subparsers(dest="action", required=True)
    memory.add_parser("doctor")
    memory_load = memory.add_parser("load")
    memory_load.add_argument("--tier", choices=["hot", "warm", "cold"], default="hot")
    memory.add_parser("initialize")
    memory.add_parser("refresh")
    for action in ("propose", "claim", "continue", "handoff", "compact"):
        command = memory.add_parser(action)
        command.add_argument("input")
    memory_apply = memory.add_parser("apply")
    memory_apply.add_argument("--plan", required=True)
    memory_apply.add_argument("--confirm", action="store_true")
    memory.add_parser("tasks")
    memory.add_parser("handoffs")

    continuity = top.add_parser("continuity").add_subparsers(dest="action", required=True)
    continuity.add_parser("doctor")
    continuity.add_parser("initialize")
    continuity.add_parser("refresh")
    continuity.add_parser("migrate")
    continuity_repair = continuity.add_parser("repair")
    continuity_repair.add_argument("--backup")
    continuity_rollback = continuity.add_parser("rollback")
    continuity_rollback.add_argument("--transaction", required=True)
    continuity_apply = continuity.add_parser("apply")
    continuity_apply.add_argument("--plan", required=True)
    continuity_apply.add_argument("--confirm", action="store_true")
    continuity.add_parser("transactions")
    continuity.add_parser("retention")
    continuity_plan_archive = continuity.add_parser("plan-archive")
    continuity_plan_archive.add_argument("input")
    continuity_apply_archive = continuity.add_parser("apply-archive")
    continuity_apply_archive.add_argument("--plan", required=True)
    continuity_apply_archive.add_argument("--confirm", action="store_true")
    continuity_plan_export = continuity.add_parser("plan-export")
    continuity_plan_export.add_argument("--destination", required=True)
    continuity_apply_export = continuity.add_parser("apply-export")
    continuity_apply_export.add_argument("--plan", required=True)
    continuity_apply_export.add_argument("--confirm", action="store_true")
    continuity_inspect_bundle = continuity.add_parser("inspect-bundle")
    continuity_inspect_bundle.add_argument("--source", required=True)
    continuity_plan_restore = continuity.add_parser("plan-restore")
    continuity_plan_restore.add_argument("--source", required=True)
    continuity_apply_restore = continuity.add_parser("apply-restore")
    continuity_apply_restore.add_argument("--plan", required=True)
    continuity_apply_restore.add_argument("--confirm", action="store_true")
    continuity.add_parser("portability-receipts")

    args = parser.parse_args()
    if args.area == "doctor":
        result = doctor()
    elif args.area == "skills" and args.action == "list":
        result = skills_list()
    elif args.area == "skills" and args.action in {"show", "explain"}:
        result = skill_show(args.capability)
    elif args.area == "skills" and args.action == "simulate":
        result = simulate(args.prompt)
    elif args.area == "skills" and args.action == "usage":
        result = usage_review(args.capability)
    elif args.area == "skills" and args.action == "plan-integration":
        result = CapabilityLifecycleService().plan_integration(
            json.loads(Path(args.candidate).expanduser().read_text(encoding="utf-8")),
            json.loads(Path(args.assembly).expanduser().read_text(encoding="utf-8")),
        )
    elif args.area == "skills" and args.action == "apply-integration":
        result = CapabilityLifecycleService().apply(args.plan, args.confirm, expected_operations={"capability-integrate", "capability-update"})
    elif args.area == "skills" and args.action == "apply-rollback":
        result = CapabilityLifecycleService().apply(args.plan, args.confirm, expected_operations={"capability-rollback"})
    elif args.area == "skills" and args.action == "apply-state":
        result = CapabilityLifecycleService().apply(args.plan, args.confirm, expected_operations={"capability-state-change"})
    elif args.area == "skills" and args.action == "plan-state":
        result = CapabilityLifecycleService().plan_state_change(args.capability, args.state, args.replacement)
    elif args.area == "skills" and args.action == "plan-rollback":
        result = CapabilityLifecycleService().plan_rollback(args.transaction)
    elif args.area == "skills" and args.action == "record-usage":
        result = CapabilityLifecycleService().record_usage(args.capability, args.task, args.confidence, args.evidence, args.outcome)
    elif args.area == "skills" and args.action == "check-update":
        result = CapabilityLifecycleService().compare_update(
            args.capability,
            json.loads(Path(args.candidate).expanduser().read_text(encoding="utf-8")),
        )
    elif args.area == "research" and args.action == "status":
        result = research_snapshot()
    elif args.area == "research" and args.action == "discover":
        command = [
            ".agents/_tools/agent_os_research.py", "discover", "--connector", args.connector,
            "--source", args.source, "--candidate-id", args.candidate_id, "--repository", args.repository,
        ]
        if args.commit:
            command.extend(["--commit", args.commit])
        if args.license:
            command.extend(["--license", args.license])
        for prompt in args.positive:
            command.extend(["--positive", prompt])
        for prompt in args.negative:
            command.extend(["--negative", prompt])
        result = run_json(command)
    elif args.area == "research" and args.action == "compare":
        result = run_json([".agents/_tools/agent_os_research.py", "compare", "--candidate-file", args.candidate_file])
    elif args.area == "update":
        command = [".agents/_tools/agent_os_lifecycle.py"]
        if args.action == "plan":
            command.extend(["plan-update", "--source", args.source])
        elif args.action == "apply":
            command.extend(["apply-update", "--source", args.source, "--plan-id", args.plan])
            if args.confirm:
                command.append("--confirm")
        else:
            command.extend(["rollback-update", "--transaction-id", args.transaction])
            if args.confirm:
                command.append("--confirm")
        result = run_json(command)
    elif args.area == "migration":
        command = [".agents/_tools/agent_os_migrate.py", args.action, "--target", args.target]
        if args.action == "plan":
            command.extend(["--source", args.source])
        elif args.action == "apply":
            command.extend(["--plan", args.plan])
            if args.confirm:
                command.append("--confirm")
        elif args.action == "rollback":
            command.extend(["--transaction", args.transaction])
            if args.confirm:
                command.append("--confirm")
        result = run_json(command)
    elif args.area == "clients":
        result = run_json([".agents/_tools/agent_os_clients.py", args.action])
    elif args.area == "publication" and args.action == "audit":
        result = publication_audit()
    elif args.area == "settings" and args.action == "show":
        result = settings_snapshot()
    elif args.area == "settings" and args.action == "serve":
        os.execv(sys.executable, [sys.executable, str(ROOT / "_tools" / "agent_os_control_center.py"), "--port", str(args.port), "--session-seconds", str(args.session_seconds)])
    elif args.area == "settings" and args.action == "plan":
        try:
            desired = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            result = {"ok": False, "error": {"code": "SETTINGS_INPUT_INVALID", "message": str(exc)}}
        else:
            result = TransactionService().plan_settings(desired)
    elif args.area == "settings" and args.action == "apply":
        result = TransactionService().apply_settings(args.plan, args.confirm)
    elif args.area == "lifecycle" and args.action == "status":
        result = lifecycle_snapshot()
    elif args.area == "lifecycle" and args.action == "recover":
        result = CapabilityLifecycleService().recover(args.confirm)
    elif args.area == "genesis":
        service = GenesisService()
        if args.action == "doctor":
            result = genesis_doctor()
            result["projection"] = service.projection_status()
            result["constitutional_authority_available"] = (
                result.get("state") == "confirmed"
                and result["projection"].get("ok") is True
            )
        elif args.action == "plan-migration":
            result = service.plan_migration()
        elif args.action == "apply-migration":
            result = service.apply_migration(args.plan, args.confirm)
        elif args.action == "plan-confirmation":
            document, input_error = read_json_input(args.input)
            result = (
                {"ok": False, "error": {"code": "GENESIS_INPUT_INVALID", "message": input_error}}
                if input_error
                else service.plan_confirmation(document)
            )
        elif args.action == "apply-confirmation":
            result = service.apply_confirmation(args.plan, args.confirm)
        elif args.action == "projection":
            result = service.projection_status()
        elif args.action == "plan-projection":
            result = service.plan_projection()
        elif args.action == "apply-projection":
            result = service.apply_projection(args.plan, args.confirm)
        else:
            result = service.recover(args.confirm)
    elif args.area == "reasoning":
        working_agent_root = Path.cwd() / ".agents"
        service = GovernedReasoningService(
            working_agent_root
            if working_agent_root.is_dir() and not working_agent_root.is_symlink()
            else ROOT
        )
        if args.action == "apply":
            result = service.apply_receipt(args.plan, confirm=args.confirm)
        elif args.action == "recover":
            result = service.recover_receipt(args.transaction, confirm=args.confirm)
        else:
            document, input_error = read_json_input(args.input)
            if input_error:
                result = {"ok": False, "error": {"code": "GOVERNED_REASONING_INPUT_INVALID", "message": input_error}}
            elif args.action == "validate":
                result = service.validate_artifact(args.kind, document)
            elif args.action == "persist":
                result = service.plan_receipt(
                    args.kind,
                    document,
                    args.source_receipt_id,
                    expiry_seconds=args.expiry_seconds,
                )
            else:
                required = {
                    "plan": {"request", "policy", "snapshot", "draft"},
                    "challenge": {"request", "plan", "policy", "draft"},
                    "decide": {"request", "plan", "challenge", "policy", "draft", "snapshot"},
                }[args.action]
                authority = document.get("authority", {}) if isinstance(document, dict) else None
                authority_required = {"expected_authority_sha256"} if args.action == "challenge" else {"current_intent_sha256"}
                authority_allowed = authority_required if args.action == "challenge" else authority_required | {"current_approval_sha256", "approval_required", "transaction_gates_valid", "constitution_conflict"}
                if not isinstance(document, dict) or not required <= set(document) or not isinstance(authority, dict) or not authority_required <= set(authority) <= authority_allowed:
                    result = {"ok": False, "error": {"code": "GOVERNED_REASONING_INPUT_INVALID", "message": "input envelope or authority is invalid"}}
                elif args.action == "plan":
                    result = service.normalize_plan(document["request"], document["policy"], document["snapshot"], document["draft"], **authority)
                elif args.action == "challenge":
                    result = service.normalize_challenge(document["request"], document["plan"], document["policy"], document["draft"], **authority)
                else:
                    result = service.normalize_decision(document["request"], document["plan"], document["challenge"], document["policy"], document["draft"], document["snapshot"], **authority)
    elif args.area == "memory":
        service = ContextMemoryService()
        if args.action == "doctor":
            result = service.doctor()
        elif args.action == "load":
            result = service.load(args.tier)
        elif args.action == "initialize":
            result = service.plan_initialize()
        elif args.action == "refresh":
            result = service.plan_refresh()
        elif args.action == "propose":
            document, input_error = read_json_input(args.input)
            result = {"ok": False, "error": {"code": "MEMORY_INPUT_INVALID", "message": input_error}} if input_error else service.plan_upsert(document)
        elif args.action == "claim":
            document, input_error = read_json_input(args.input)
            result = {"ok": False, "error": {"code": "MEMORY_INPUT_INVALID", "message": input_error}} if input_error else service.plan_claim_task(document)
        elif args.action == "continue":
            document, input_error = read_json_input(args.input)
            result = {"ok": False, "error": {"code": "MEMORY_INPUT_INVALID", "message": input_error}} if input_error else service.plan_continue_task(document)
        elif args.action == "handoff":
            document, input_error = read_json_input(args.input)
            result = {"ok": False, "error": {"code": "MEMORY_INPUT_INVALID", "message": input_error}} if input_error else service.plan_handoff(document)
        elif args.action == "compact":
            document, input_error = read_json_input(args.input)
            result = {"ok": False, "error": {"code": "MEMORY_INPUT_INVALID", "message": input_error}} if input_error else service.plan_compact(document)
        elif args.action == "apply":
            result = service.apply(args.plan, args.confirm)
        elif args.action == "tasks":
            result = service.list_tasks()
        else:
            result = service.list_handoffs()
    elif args.area == "continuity":
        if args.action == "doctor":
            result = continuity_doctor()
        elif args.action in {
            "initialize",
            "refresh",
            "migrate",
            "repair",
            "rollback",
            "apply",
            "transactions",
        }:
            service = ContinuityTransactionService()
            if args.action == "initialize":
                result = service.plan_initialize()
            elif args.action == "refresh":
                result = service.plan_refresh()
            elif args.action == "migrate":
                result = service.plan_migrate()
            elif args.action == "repair":
                result = service.plan_repair(args.backup)
            elif args.action == "rollback":
                result = service.plan_rollback(args.transaction)
            elif args.action == "apply":
                result = service.apply(args.plan, args.confirm)
            else:
                result = service.list_transactions()
        else:
            working_agent_root = Path.cwd() / ".agents"
            portability = ContinuityPortabilityService(
                working_agent_root
                if (
                    working_agent_root.is_dir()
                    and not working_agent_root.is_symlink()
                )
                else ROOT
            )
            if args.action == "retention":
                result = portability.inspect_retention()
            elif args.action == "plan-archive":
                document, input_error = read_json_input(args.input)
                if input_error:
                    result = {
                        "ok": False,
                        "error": {
                            "code": "PORTABILITY_INPUT_INVALID",
                            "message": input_error,
                        },
                    }
                else:
                    reference_ids = (
                        document.get("reference_ids")
                        if isinstance(document, dict)
                        else document
                    )
                    result = portability.plan_archive(reference_ids)
            elif args.action == "apply-archive":
                result = portability.apply_portability(
                    args.plan,
                    args.confirm,
                    expected_operation="archive",
                )
            elif args.action == "plan-export":
                result = portability.plan_export(args.destination)
            elif args.action == "apply-export":
                result = portability.apply_portability(
                    args.plan,
                    args.confirm,
                    expected_operation="export",
                )
            elif args.action == "inspect-bundle":
                result = portability.inspect_bundle(args.source)
            elif args.action == "plan-restore":
                result = portability.plan_restore(args.source)
            elif args.action == "apply-restore":
                result = portability.apply_restore(args.plan, args.confirm)
            else:
                result = portability.list_receipts()
    else:
        result = {"ok": False, "error": {"code": "COMMAND_NOT_IMPLEMENTED"}}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
