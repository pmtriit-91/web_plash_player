#!/usr/bin/env python3
"""Static, zero-execution research and admission analysis for skill candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_capabilities import descriptor_map, route_capability, tokens

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS_PATH = ROOT / "research" / "connectors.json"
REGISTRY_PATH = ROOT / "research" / "candidate-registry.json"
DECISIONS_PATH = ROOT / "research" / "decision-history.json"
POLICY_PATH = ROOT / "research" / "research-policy.json"
RUNTIME_CANDIDATES_PATH = ROOT / "_runtime" / "research" / "candidates.json"

FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ARCHIVE_SUFFIXES = {".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar"}
SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".bat", ".cmd", ".exe"}
TEXT_SUFFIXES = {"", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".py", ".js", ".ts", ".sh", ".ps1"}
PROMPT_INJECTION_PATTERNS = {
    "PROMPT_INJECTION_IGNORE_POLICY": re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions", re.I),
    "PROMPT_INJECTION_BYPASS_SAFETY": re.compile(r"(bypass|disable|override).{0,30}(safety|policy|approval)", re.I),
    "PROMPT_INJECTION_HIDDEN_INSTRUCTION": re.compile(r"do\s+not\s+(tell|reveal|show).{0,30}(user|operator)", re.I),
}
MUTATION_PATTERNS = {
    "UPSTREAM_AUTO_COMMIT": re.compile(r"\bgit\s+commit\b|auto[- ]commit", re.I),
    "UPSTREAM_DESTRUCTIVE_GIT": re.compile(r"git\s+(reset\s+--hard|push\s+--force|clean\s+-[a-z]*f)", re.I),
    "UPSTREAM_AUTO_DEPLOY": re.compile(r"auto[- ]deploy|\bdeploy\s+automatically\b", re.I),
}
GLOBAL_INSTALL_PATTERNS = {
    "GLOBAL_INSTALLER": re.compile(r"(npm\s+(install|i)\s+-g|pipx?\s+install|uv\s+tool\s+install|curl[^\n|]*\|\s*(ba)?sh)", re.I),
}
COMPETING_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}
COMPETING_DIRS = {"hooks", "commands", ".claude", ".github/agents", "memory"}

TRANSITIONS = {
    "discovered": {"pinned", "blocked", "evaluating", "rejected", "quarantined"},
    "pinned": {"evaluating", "blocked", "rejected", "quarantined"},
    "evaluating": {"recommended", "blocked", "rejected", "quarantined", "failed"},
    "recommended": {"approval-pending", "research-only", "rejected", "deprecated"},
    "approval-pending": {"integrating", "research-only", "rejected", "failed"},
    "integrating": {"active", "failed", "quarantined"},
    "active": {"deprecated", "quarantined"},
    "failed": {"evaluating", "rejected", "quarantined"},
    "blocked": {"evaluating", "research-only", "rejected"},
    "quarantined": {"evaluating", "research-only", "rejected"},
    "research-only": {"evaluating", "rejected", "deprecated"},
    "deprecated": set(),
    "rejected": set(),
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalized_receipt_hash(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "content_sha256"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def persist_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    errors = validate_candidate(candidate)
    if errors:
        return {"ok": False, "reason_codes": ["CANDIDATE_VALIDATION_FAILED"], "errors": errors}
    document = load_json(RUNTIME_CANDIDATES_PATH, {"schema_version": 1, "authority": "runtime-research-state", "candidates": []})
    records = {
        f"{item.get('id')}@{item.get('source', {}).get('commit')}": item
        for item in document.get("candidates", [])
        if isinstance(item, dict)
    }
    key = f"{candidate.get('id')}@{candidate.get('source', {}).get('commit')}"
    records[key] = candidate
    atomic_json(
        RUNTIME_CANDIDATES_PATH,
        {"schema_version": 1, "authority": "runtime-research-state", "candidates": [records[item] for item in sorted(records)]},
    )
    return {"ok": True, "candidate_key": key, "path": "_runtime/research/candidates.json"}


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def relative_key(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def inspect_inventory(source: Path) -> tuple[dict[str, Any], dict[str, list[str]]]:
    files: list[dict[str, Any]] = []
    findings = {
        "archives": [],
        "scripts": [],
        "executables": [],
        "unsafe_symlinks": [],
        "prompt_injection": [],
        "mutations": [],
        "global_installers": [],
        "competing": [],
    }
    source_resolved = source.resolve()
    for path in sorted(source.rglob("*"), key=lambda value: value.as_posix()):
        relative = relative_key(path, source)
        lowered_parts = {part.lower() for part in Path(relative).parts}
        if path.is_symlink():
            target = os.readlink(path)
            resolved = (path.parent / target).resolve()
            within = resolved == source_resolved or source_resolved in resolved.parents
            files.append({"path": relative, "type": "symlink", "target": target, "target_within_snapshot": within})
            if not within:
                findings["unsafe_symlinks"].append(relative)
            continue
        if path.is_dir():
            continue
        try:
            content = path.read_bytes()
            mode = path.stat().st_mode
        except OSError:
            content = b""
            mode = 0
        entry = {"path": relative, "type": "file", "bytes": len(content), "sha256": sha256_bytes(content)}
        files.append(entry)
        suffix = path.suffix.lower()
        if suffix in ARCHIVE_SUFFIXES:
            findings["archives"].append(relative)
        if suffix in SCRIPT_SUFFIXES or "scripts" in lowered_parts:
            findings["scripts"].append(relative)
        if mode and stat.S_ISREG(mode) and mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            findings["executables"].append(relative)
        if path.name in COMPETING_FILES or any(relative == item or relative.startswith(item + "/") for item in COMPETING_DIRS):
            findings["competing"].append(relative)
        if suffix not in TEXT_SUFFIXES or len(content) > 1024 * 1024:
            continue
        text = content.decode("utf-8", errors="ignore")
        for code, pattern in PROMPT_INJECTION_PATTERNS.items():
            if pattern.search(text):
                findings["prompt_injection"].append(f"{code}:{relative}")
        for code, pattern in MUTATION_PATTERNS.items():
            if pattern.search(text):
                findings["mutations"].append(f"{code}:{relative}")
        for code, pattern in GLOBAL_INSTALL_PATTERNS.items():
            if pattern.search(text):
                findings["global_installers"].append(f"{code}:{relative}")
    digest_input = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    inventory = {
        "file_count": len(files),
        "total_bytes": sum(int(item.get("bytes", 0)) for item in files),
        "files": files,
        "snapshot_sha256": sha256_bytes(digest_input),
    }
    return inventory, findings


def overlap_analysis(name: str, description: str) -> dict[str, Any]:
    candidate_tokens = tokens(f"{name} {description}")
    ranked: list[dict[str, Any]] = []
    for capability_id, descriptor in descriptor_map().items():
        existing = tokens(" ".join([descriptor.get("summary", ""), *descriptor.get("when_to_use", [])]))
        union = candidate_tokens | existing
        score = len(candidate_tokens & existing) / len(union) if union else 0.0
        ranked.append({"capability_id": capability_id, "score": round(score, 4)})
    ranked.sort(key=lambda item: (item["score"], item["capability_id"]), reverse=True)
    maximum = float(load_json(POLICY_PATH, {}).get("portfolio", {}).get("maximum_overlap_for_vendor", 0.45))
    return {
        "method": "token-jaccard-v1",
        "threshold": maximum,
        "highest": ranked[0] if ranked else None,
        "top_matches": ranked[:3],
        "conflict": bool(ranked and ranked[0]["score"] >= maximum),
    }


def shadow_evaluate(name: str, description: str, positives: list[str], negatives: list[str]) -> dict[str, Any]:
    candidate_tokens = tokens(f"{name} {description}")

    def candidate_matches(prompt: str) -> bool:
        prompt_tokens = tokens(prompt)
        return bool(candidate_tokens & prompt_tokens)

    positive_results = [{"prompt_sha256": sha256_bytes(prompt.encode()), "matched": candidate_matches(prompt)} for prompt in positives]
    negative_results = [{"prompt_sha256": sha256_bytes(prompt.encode()), "matched": candidate_matches(prompt)} for prompt in negatives]
    conflict_results = []
    for prompt in positives:
        routed = route_capability(prompt)
        conflict_results.append(
            {
                "prompt_sha256": sha256_bytes(prompt.encode()),
                "active_capability": routed.get("selected", {}).get("id"),
                "active_confidence": routed.get("selected", {}).get("confidence"),
            }
        )
    if not positives or not negatives:
        status = "pending"
    elif all(item["matched"] for item in positive_results) and not any(item["matched"] for item in negative_results):
        status = "passing"
    else:
        status = "failing"
    return {
        "method": "static-shadow-routing-v1",
        "status": status,
        "positive": positive_results,
        "negative": negative_results,
        "active_portfolio_comparison": conflict_results,
        "raw_prompts_stored": False,
    }


def gate(gate_id: str, status: str, reason_codes: list[str]) -> dict[str, Any]:
    return {"gate": gate_id, "status": status, "reason_codes": sorted(set(reason_codes))}


def inspect_candidate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        return {"ok": False, "error": {"code": "SOURCE_DIRECTORY_MISSING", "message": str(source)}}
    if not SAFE_ID.fullmatch(args.candidate_id):
        return {"ok": False, "error": {"code": "CANDIDATE_ID_INVALID", "message": args.candidate_id}}

    inventory, findings = inspect_inventory(source)
    metadata = parse_frontmatter(source / "SKILL.md")
    license_value = args.license or metadata.get("license") or None
    commit = args.commit if FULL_COMMIT.fullmatch(args.commit or "") else None
    policy = load_json(POLICY_PATH, {})
    allowed_licenses = set(policy.get("license", {}).get("vendor_allowlist", []))
    name = metadata.get("name", source.name)
    description = metadata.get("description", "")
    overlap = overlap_analysis(name, description)
    shadow = shadow_evaluate(name, description, args.positive or [], args.negative or [])

    gates = [
        gate("provenance", "pass" if commit else "block", [] if commit else ["FULL_COMMIT_REQUIRED"]),
        gate("license", "pass" if license_value in allowed_licenses else "block", [] if license_value in allowed_licenses else ["LICENSE_NOT_VENDOR_ALLOWED"]),
        gate("structure", "block" if findings["archives"] or findings["unsafe_symlinks"] else "pass", [
            *(["OPAQUE_ARCHIVE_REJECTED"] if findings["archives"] else []),
            *(["UNSAFE_SYMLINK_REJECTED"] if findings["unsafe_symlinks"] else []),
            *(["SKILL_MD_MISSING"] if not (source / "SKILL.md").is_file() else []),
        ]),
        gate("executable-content", "quarantine" if findings["scripts"] or findings["executables"] else "pass", ["UPSTREAM_EXECUTABLE_QUARANTINED"] if findings["scripts"] or findings["executables"] else []),
        gate("prompt-integrity", "block" if findings["prompt_injection"] or findings["mutations"] or findings["global_installers"] else "pass", [
            *(["PROMPT_INJECTION_REJECTED"] if findings["prompt_injection"] else []),
            *(["UNAUTHORIZED_MUTATION_REJECTED"] if findings["mutations"] else []),
            *(["GLOBAL_INSTALLER_REJECTED"] if findings["global_installers"] else []),
        ]),
        gate("framework-conflict", "block" if findings["competing"] else "pass", ["COMPETING_BOOT_ROUTER_OR_MEMORY"] if findings["competing"] else []),
        gate("portfolio-overlap", "warn" if overlap["conflict"] else "pass", ["CAPABILITY_OVERLAP"] if overlap["conflict"] else []),
        gate("shadow-routing", "pass" if shadow["status"] == "passing" else "block", [] if shadow["status"] == "passing" else [f"SHADOW_EVAL_{shadow['status'].upper()}"]),
    ]

    blocking_codes = {code for item in gates if item["status"] == "block" for code in item["reason_codes"]}
    quarantined = any(item["status"] == "quarantine" for item in gates)
    security_reject = bool(blocking_codes & {
        "OPAQUE_ARCHIVE_REJECTED", "UNSAFE_SYMLINK_REJECTED", "PROMPT_INJECTION_REJECTED",
        "UNAUTHORIZED_MUTATION_REJECTED", "GLOBAL_INSTALLER_REJECTED", "SKILL_MD_MISSING",
    })
    competing = "COMPETING_BOOT_ROUTER_OR_MEMORY" in blocking_codes
    if security_reject:
        recommendation, state = "reject", "rejected"
    elif competing:
        recommendation, state = "adapt-local-principles", "recommended"
    elif quarantined:
        recommendation, state = "research-only", "quarantined"
    elif "FULL_COMMIT_REQUIRED" in blocking_codes or "LICENSE_NOT_VENDOR_ALLOWED" in blocking_codes:
        recommendation, state = "research-only", "blocked"
    elif shadow["status"] != "passing":
        recommendation, state = "pending", "evaluating"
    elif overlap["conflict"]:
        recommendation, state = "adapt-local-skill", "recommended"
    else:
        recommendation, state = "vendor-pin", "recommended"

    discovered_at = args.discovered_at or utc_now()
    history_states = {
        "recommended": ["discovered", "pinned", "evaluating", "recommended"],
        "evaluating": ["discovered", "pinned", "evaluating"],
    }.get(state, ["discovered", state])
    candidate = {
        "schema_version": 1,
        "id": args.candidate_id,
        "state": state,
        "source": {
            "connector": args.connector,
            "repository": args.repository,
            "commit": commit,
            "license": license_value,
            "snapshot_sha256": inventory.pop("snapshot_sha256"),
        },
        "discovered_at": discovered_at,
        "evidence": [
            {"kind": "frontmatter", "name": name, "description": description, "raw_body_stored": False},
            {"kind": "static-findings", "findings": findings},
        ],
        "inventory": inventory,
        "gate_results": gates,
        "overlap": overlap,
        "shadow_eval": shadow,
        "recommendation": recommendation,
        "decision_history": [
            {"state": history_state, "at": discovered_at, "actor": "research-engine"}
            for history_state in history_states
        ],
    }
    return {"ok": True, "zero_execution": True, "candidate": candidate}


def validate_candidate(candidate: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(candidate, dict):
        return [{"code": "CANDIDATE_INVALID"}]
    if candidate.get("schema_version") != 1 or not SAFE_ID.fullmatch(str(candidate.get("id", ""))):
        errors.append({"code": "CANDIDATE_ID_OR_SCHEMA_INVALID", "id": candidate.get("id")})
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    commit = source.get("commit")
    if commit is not None and not FULL_COMMIT.fullmatch(str(commit)):
        errors.append({"code": "CANDIDATE_COMMIT_INVALID", "id": candidate.get("id")})
    history = candidate.get("decision_history") if isinstance(candidate.get("decision_history"), list) else []
    for before, after in zip(history, history[1:]):
        old_state, new_state = before.get("state"), after.get("state")
        if old_state != new_state and new_state not in TRANSITIONS.get(str(old_state), set()):
            errors.append({"code": "CANDIDATE_TRANSITION_INVALID", "id": candidate.get("id"), "from": old_state, "to": new_state})
    if history and history[-1].get("state") != candidate.get("state"):
        errors.append({"code": "CANDIDATE_HISTORY_STATE_MISMATCH", "id": candidate.get("id")})
    return errors


def validate_registry() -> dict[str, Any]:
    connectors = load_json(CONNECTORS_PATH, {})
    registry = load_json(REGISTRY_PATH, {})
    decisions = load_json(DECISIONS_PATH, {})
    policy = load_json(POLICY_PATH, {})
    errors: list[dict[str, Any]] = []
    expected_connectors = {"github", "notebooklm", "local", "mcp-skill-index"}
    records = connectors.get("connectors", []) if isinstance(connectors, dict) else []
    ids = {item.get("id") for item in records if isinstance(item, dict)}
    if connectors.get("schema_version") != 1 or ids != expected_connectors:
        errors.append({"code": "RESEARCH_CONNECTORS_INVALID"})
    for item in records:
        if item.get("optional") is not True or item.get("authority") != "research-signal-only" or item.get("failure_mode") != "isolated":
            errors.append({"code": "CONNECTOR_TRUST_BOUNDARY_INVALID", "id": item.get("id")})
    candidates = registry.get("candidates", []) if isinstance(registry, dict) else []
    if registry.get("schema_version") != 1 or registry.get("authority") != "research-candidates-only" or not isinstance(candidates, list):
        errors.append({"code": "CANDIDATE_REGISTRY_INVALID"})
        candidates = []
    candidate_ids = [item.get("id") for item in candidates if isinstance(item, dict)]
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append({"code": "CANDIDATE_ID_DUPLICATED"})
    for candidate in candidates:
        errors.extend(validate_candidate(candidate))
    receipts = decisions.get("receipts", []) if isinstance(decisions, dict) else []
    seen_receipts: set[str] = set()
    for receipt in receipts if isinstance(receipts, list) else []:
        receipt_id = receipt.get("id") if isinstance(receipt, dict) else None
        if not receipt_id or receipt_id in seen_receipts or receipt.get("content_sha256") != normalized_receipt_hash(receipt):
            errors.append({"code": "RESEARCH_DECISION_RECEIPT_INVALID", "id": receipt_id})
        supersedes = receipt.get("supersedes") if isinstance(receipt, dict) else None
        if supersedes is not None and supersedes not in seen_receipts:
            errors.append({"code": "RESEARCH_DECISION_SUPERSEDES_UNKNOWN", "id": receipt_id})
        if receipt_id:
            seen_receipts.add(receipt_id)
    if policy.get("execution", {}).get("upstream_code_allowed") is not False or policy.get("activation", {}).get("human_approval_required") is not True:
        errors.append({"code": "RESEARCH_POLICY_UNSAFE"})
    return {
        "ok": not errors,
        "connectors": len(records),
        "candidates": len(candidates),
        "decision_receipts": len(receipts) if isinstance(receipts, list) else 0,
        "errors": errors,
    }


def status() -> dict[str, Any]:
    validation = validate_registry()
    connectors = load_json(CONNECTORS_PATH, {}).get("connectors", [])
    runtime_candidates = load_json(RUNTIME_CANDIDATES_PATH, {}).get("candidates", [])
    return {
        "ok": validation["ok"],
        "boot_dependency": False,
        "network_contacted": False,
        "connector_health": [
            {"id": item.get("id"), "enabled": item.get("enabled"), "status": "not-probed", "failure_mode": "isolated"}
            for item in connectors
        ],
        "registry": validation,
        "runtime_candidates": len(runtime_candidates) if isinstance(runtime_candidates, list) else 0,
    }


def compare_record(path: Path) -> dict[str, Any]:
    candidate = load_json(path, None)
    errors = validate_candidate(candidate)
    if errors:
        return {"ok": False, "errors": errors}
    evidence = next((item for item in candidate.get("evidence", []) if item.get("kind") == "frontmatter"), {})
    overlap = overlap_analysis(str(evidence.get("name", candidate.get("id", ""))), str(evidence.get("description", "")))
    return {"ok": True, "candidate_id": candidate.get("id"), "overlap": overlap, "active_portfolio_changed": overlap != candidate.get("overlap")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-execution Agent OS skill research engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("validate-registry")
    discover = sub.add_parser("discover")
    discover.add_argument("--connector", choices=["github", "notebooklm", "local", "mcp-skill-index"], required=True)
    discover.add_argument("--source", required=True)
    discover.add_argument("--candidate-id", required=True)
    discover.add_argument("--repository", required=True)
    discover.add_argument("--commit", default="")
    discover.add_argument("--license", default="")
    discover.add_argument("--positive", action="append", default=[])
    discover.add_argument("--negative", action="append", default=[])
    discover.add_argument("--discovered-at")
    compare = sub.add_parser("compare")
    compare.add_argument("--candidate-file", required=True)
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status()
        elif args.command == "validate-registry":
            result = validate_registry()
        elif args.command == "discover":
            result = inspect_candidate(args)
            if result.get("ok") is True and isinstance(result.get("candidate"), dict):
                result["runtime_persistence"] = persist_candidate(result["candidate"])
                result["persisted"] = result["runtime_persistence"].get("ok") is True
        elif args.command == "compare":
            result = compare_record(Path(args.candidate_file).expanduser().resolve())
        else:
            result = {"ok": False, "error": {"code": "COMMAND_NOT_IMPLEMENTED"}}
    except Exception as exc:
        result = {"ok": False, "error": {"code": exc.__class__.__name__, "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ok") else 2)


if __name__ == "__main__":
    main()
