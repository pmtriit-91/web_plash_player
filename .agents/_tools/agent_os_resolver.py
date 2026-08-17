#!/usr/bin/env python3
"""
Agent OS Resolver — Agent OS V9.1.0

Resolves internal workflows and capabilities from a task prompt using the
authoritative routing registries. This is a deterministic helper for wrappers,
evals, and IDE integrations; it is not a replacement for agent judgment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from agent_os_capabilities import (
    capability_card,
    capability_cards,
    route_capability,
    validate_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_REGISTRY = ROOT / "routing" / "workflow-registry.json"
CAPABILITY_REGISTRY = ROOT / "routing" / "capability-registry.json"
MODE_RANK = {"FAST": 1, "STANDARD": 2, "DEEP": 3}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def normalize_text(parts: list[str]) -> str:
    return " ".join(part for part in parts if part).lower()


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def score_triggers(text: str, triggers: list[str]) -> tuple[int, list[str]]:
    matched = []
    for trigger in triggers:
        if trigger and trigger.lower() in text:
            matched.append(trigger)
    if not matched:
        return 0, []
    score = min(100, 55 + (len(matched) * 15))
    return score, matched


def select_best(candidates: list[dict], fallback: dict) -> dict:
    ranked = sorted(
        candidates,
        key=lambda item: (
            item.get("score", 0),
            MODE_RANK.get(item.get("mode", "STANDARD"), 2),
            item.get("id", ""),
        ),
        reverse=True,
    )
    if ranked and ranked[0].get("score", 0) > 0:
        return ranked[0]
    return fallback


def resolve_workflow(text: str, registry: dict) -> dict:
    candidates = []
    for workflow_id, workflow in (registry.get("workflows") or {}).items():
        score, matched = score_triggers(text, workflow.get("triggers", []))
        candidates.append({
            "id": workflow_id,
            "type": "workflow",
            "path": workflow.get("path", ""),
            "mode": workflow.get("mode", "STANDARD"),
            "score": score,
            "matched_triggers": matched,
        })

    fallback_id = "planner"
    if any(word in text for word in ["implement", "execute", "apply changes"]):
        fallback_id = "executor"
    if any(word in text for word in ["review", "audit"]):
        fallback_id = "reviewer"
    if any(word in text for word in ["bug", "error", "debug", "regression"]):
        fallback_id = "debugging"

    fallback_entry = (registry.get("workflows") or {}).get(fallback_id, {})
    fallback = {
        "id": fallback_id,
        "type": "workflow",
        "path": fallback_entry.get("path", ""),
        "mode": fallback_entry.get("mode", "STANDARD"),
        "score": 40,
        "matched_triggers": [],
        "fallback": True,
    }
    return select_best(candidates, fallback)


def dominant_mode(workflow: dict, capability: dict) -> str:
    workflow_mode = workflow.get("mode", "STANDARD")
    capability_mode = capability.get("mode", "STANDARD")
    return max([workflow_mode, capability_mode], key=lambda mode: MODE_RANK.get(mode, 2))


def resolve(args) -> dict:
    workflow_registry = load_json(WORKFLOW_REGISTRY, {})
    capability_registry = load_json(CAPABILITY_REGISTRY, {})
    text = normalize_text([args.prompt, " ".join(args.files or []), args.errors or ""])

    workflow = resolve_workflow(text, workflow_registry)
    capability_routing = route_capability(text, capability_registry)
    capability = capability_routing["selected"]

    warnings = []
    if workflow.get("fallback"):
        warnings.append("workflow_resolved_by_fallback")
    if capability.get("fallback"):
        warnings.append("capability_resolved_by_fallback")

    return {
        "ok": True,
        "version": capability_registry.get("version", "unknown"),
        "prompt_sha256": prompt_hash(args.prompt),
        "mode": dominant_mode(workflow, capability),
        "workflow": workflow,
        "capability": capability,
        "alternatives": capability_routing["alternatives"],
        "excluded_capabilities": capability_routing["excluded"],
        "capability_gap": capability_routing["capability_gap"],
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve Agent OS workflow and capability routing")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve")
    r.add_argument("--prompt", required=True)
    r.add_argument("--files", nargs="*", default=[])
    r.add_argument("--errors", default="")

    sub.add_parser("list")

    show = sub.add_parser("show")
    show.add_argument("--capability", required=True)

    explain = sub.add_parser("explain")
    explain.add_argument("--capability", required=True)

    simulate = sub.add_parser("simulate")
    simulate.add_argument("--prompt", required=True)
    simulate.add_argument("--files", nargs="*", default=[])
    simulate.add_argument("--errors", default="")

    sub.add_parser("validate-catalog")

    args = parser.parse_args()
    try:
        if args.cmd in {"resolve", "simulate"}:
            result = resolve(args)
        elif args.cmd == "list":
            result = {"ok": True, "version": load_json(CAPABILITY_REGISTRY, {}).get("version"), "capabilities": capability_cards()}
        elif args.cmd in {"show", "explain"}:
            card = capability_card(args.capability)
            result = {"ok": card is not None, "capability": card}
            if card is None:
                result["error"] = {"code": "CAPABILITY_NOT_FOUND", "message": args.capability}
        elif args.cmd == "validate-catalog":
            result = validate_catalog()
        else:
            result = {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": "Unknown command.", "details": {}}}
    except Exception as exc:
        result = {"ok": False, "error": {"code": exc.__class__.__name__, "message": str(exc), "details": {}}}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
