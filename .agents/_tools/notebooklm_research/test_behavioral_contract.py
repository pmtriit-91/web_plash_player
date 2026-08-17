#!/usr/bin/env python3
"""Offline behavioral contract tests for the NotebookLM research capability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals" / "notebooklm-behavioral-evals.json"
SCHEMA = ROOT / "core" / "contracts" / "notebooklm-research-trace.schema.json"
REGISTRY = ROOT / "routing" / "capability-registry.json"
SKILL = ROOT / "skills" / "notebooklm-research" / "SKILL.md"

ALLOWED_EXPORT_REASONS = {
    "requested-deliverable",
    "offline-evidence",
    "retention-requirement",
    "exact-visual-inspection",
    "live-tool-format-limitation",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_trace(trace: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    events = trace.get("events") if isinstance(trace.get("events"), list) else []
    operations = [event.get("operation") for event in events if isinstance(event, dict)]
    sequences = [event.get("sequence") for event in events if isinstance(event, dict)]

    if trace.get("schema_version") != 1 or trace.get("capability_id") != "notebooklm_research":
        errors.append("trace-identity-invalid")
    if not events or sequences != list(range(1, len(events) + 1)):
        errors.append("event-sequence-invalid")
    if not operations or operations[0] != "server_info":
        errors.append("server-info-must-be-first")
    if "ask_interface_choice" in operations:
        errors.append("interface-choice-asked-without-material-need")

    queries = [event for event in events if event.get("operation") == "notebook_query"]
    if queries:
        first_query_index = operations.index("notebook_query")
        if "select_existing_notebook" not in operations[:first_query_index]:
            errors.append("existing-notebook-not-selected")
        if "select_sources" not in operations[:first_query_index]:
            errors.append("source-scope-not-selected")
        if not queries[0].get("source_refs"):
            errors.append("first-query-source-scope-empty")
    elif not any(operation in {"download_artifact", "download_all_artifacts"} for operation in operations):
        errors.append("research-query-missing")

    studio_events = [event for event in events if event.get("operation") == "studio_status"]
    if studio_events:
        focused = [event for event in queries if event.get("derived_from_artifact") is True]
        if not focused:
            errors.append("studio-follow-up-missing")
        elif queries and focused[0].get("conversation_ref") != queries[0].get("conversation_ref"):
            errors.append("conversation-continuity-broken")

    for event in events:
        operation = event.get("operation")
        if trace.get("read_only") is True and operation in {
            "download_artifact", "download_all_artifacts", "external_mutation"
        }:
            errors.append("write-operation-in-read-only-trace")
        if operation == "download_all_artifacts":
            errors.append("bulk-download-not-accepted-by-research-contract")
        if operation == "download_artifact" and (
            event.get("user_intent") != "explicit" or event.get("reason") not in ALLOWED_EXPORT_REASONS
        ):
            errors.append("targeted-download-without-explicit-exception")

    if queries and "handoff" not in operations:
        errors.append("durable-handoff-missing")
    handoffs = [event for event in events if event.get("operation") == "handoff"]
    for handoff in handoffs:
        provenance = handoff.get("provenance") if isinstance(handoff.get("provenance"), dict) else {}
        if any(provenance.get(key) is not True for key in ("notebook", "sources", "conversation", "artifact")):
            errors.append("handoff-provenance-incomplete")
    return sorted(set(errors))


def validate_precedence() -> list[str]:
    errors: list[str] = []
    registry = load_json(REGISTRY)
    policy = registry.get("host_skill_precedence", {})
    rules = policy.get("rules", []) if isinstance(policy, dict) else []
    rule = next((item for item in rules if item.get("capability_id") == "notebooklm_research"), None)
    if policy.get("default_rule") != "registered-repository-capability-wins":
        errors.append("host-precedence-default-invalid")
    if not isinstance(rule, dict) or "nlm-skill" not in rule.get("external_skill_ids", []):
        errors.append("notebooklm-host-overlap-unregistered")
    elif rule.get("on_conflict") != "repository-local-wins":
        errors.append("notebooklm-host-conflict-policy-invalid")
    skill = SKILL.read_text(encoding="utf-8")
    for phrase in ("Host-skill precedence", "reference-only", "Do not ask the user to choose"):
        if phrase not in skill:
            errors.append(f"skill-precedence-text-missing:{phrase}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate NotebookLM behavioral trace fixtures")
    parser.add_argument("--trace", action="append", default=[], help="Additional trace JSON to validate")
    args = parser.parse_args()
    spec = load_json(EVALS)
    schema = load_json(SCHEMA)
    results: list[dict[str, Any]] = []
    for case in spec.get("cases", []):
        errors = validate_trace(case)
        actual = "pass" if not errors else "fail"
        results.append({
            "id": case.get("id"),
            "expected": case.get("expected_outcome"),
            "actual": actual,
            "passed": actual == case.get("expected_outcome"),
            "errors": errors,
        })
    for trace_path in args.trace:
        case = load_json(Path(trace_path))
        errors = validate_trace(case)
        actual = "pass" if not errors else "fail"
        results.append({
            "id": case.get("id"),
            "expected": case.get("expected_outcome"),
            "actual": actual,
            "passed": actual == case.get("expected_outcome"),
            "errors": errors,
            "source": str(trace_path),
        })
    precedence_errors = validate_precedence()
    schema_ok = schema.get("$id") == "https://universal-agent-os.local/schemas/notebooklm-research-trace.schema.json"
    ok = all(result["passed"] for result in results) and not precedence_errors and schema_ok
    output = {
        "ok": ok,
        "version": "1.0.0",
        "passed": sum(1 for result in results if result["passed"]),
        "total": len(results),
        "precedence_ok": not precedence_errors,
        "precedence_errors": precedence_errors,
        "schema_ok": schema_ok,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
