#!/usr/bin/env python3
"""Audit public-release readiness without publishing or changing state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


AGENT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = AGENT_ROOT.parent
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ACTION_USE = re.compile(r"^\s*-\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
SECRET_PATTERNS = (
    ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("GITHUB_PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OPENAI_API_KEY", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)
MAX_SCAN_BYTES = 2 * 1024 * 1024


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_files(root: Path) -> list[Path]:
    try:
        process = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        process = None
    if process is not None and process.returncode == 0:
        paths = [
            root / item.decode("utf-8", errors="surrogateescape")
            for item in process.stdout.split(b"\0")
            if item
        ]
        return [path for path in paths if path.is_file() and not path.is_symlink()]
    excluded = {".git", "_runtime", "__pycache__"}
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and not any(part in excluded for part in path.parts)
    ]


def secret_signature_paths(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in tracked_files(root):
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for identifier, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append({"path": relative, "rule": identifier})
    return sorted(findings, key=lambda item: (item["path"], item["rule"]))


def workflow_action_refs(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    workflow_root = root / ".github" / "workflows"
    actions: list[dict[str, Any]] = []
    blockers: list[str] = []
    if not workflow_root.is_dir():
        return actions, ["WORKFLOW_DIRECTORY_MISSING"]
    workflow_files = sorted([*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")])
    if not workflow_files:
        return actions, ["WORKFLOW_FILE_MISSING"]
    for path in workflow_files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            blockers.append("WORKFLOW_UNREADABLE")
            continue
        for match in ACTION_USE.finditer(content):
            action, reference = match.groups()
            local = action.startswith("./")
            immutable = local or FULL_SHA.fullmatch(reference) is not None
            actions.append(
                {
                    "workflow": path.relative_to(root).as_posix(),
                    "action": action,
                    "reference": reference,
                    "immutable": immutable,
                }
            )
            if not immutable:
                blockers.append("WORKFLOW_ACTION_REF_MUTABLE")
    return actions, sorted(set(blockers))


def vendor_governance(root: Path, notice_text: str) -> tuple[dict[str, Any], list[str]]:
    lock_path = root / ".agents" / "vendor" / "vendor-lock.json"
    lock = load_json(lock_path, {})
    packages = lock.get("packages") if isinstance(lock.get("packages"), list) else []
    research = lock.get("research_sources") if isinstance(lock.get("research_sources"), list) else []
    blockers: list[str] = []
    governed: list[str] = []
    for package in packages:
        if not isinstance(package, dict):
            blockers.append("VENDOR_RECORD_INVALID")
            continue
        identifier = str(package.get("id", ""))
        governed.append(identifier)
        commit = str(package.get("commit", ""))
        license_name = str(package.get("license", ""))
        license_path = root / ".agents" / str(package.get("license_path", ""))
        files = package.get("files") if isinstance(package.get("files"), dict) else {}
        relative_license = str(package.get("license_path", ""))
        if not identifier or not FULL_SHA.fullmatch(commit) or not license_name:
            blockers.append("VENDOR_PROVENANCE_INCOMPLETE")
        if not license_path.is_file() or relative_license not in files:
            blockers.append("VENDOR_LICENSE_MISSING")
        elif files.get(relative_license) != sha256(license_path):
            blockers.append("VENDOR_LICENSE_HASH_MISMATCH")
        if identifier and identifier not in notice_text:
            blockers.append("THIRD_PARTY_NOTICE_INCOMPLETE")
    for source in research:
        if not isinstance(source, dict):
            blockers.append("RESEARCH_SOURCE_INVALID")
            continue
        identifier = str(source.get("id", ""))
        governed.append(identifier)
        if not identifier or not FULL_SHA.fullmatch(str(source.get("commit", ""))) or not source.get("license"):
            blockers.append("RESEARCH_PROVENANCE_INCOMPLETE")
        if identifier and identifier not in notice_text:
            blockers.append("THIRD_PARTY_NOTICE_INCOMPLETE")
    return {
        "vendor_packages": len(packages),
        "research_sources": len(research),
        "governed_ids": governed,
    }, sorted(set(blockers))


def client_evidence(root: Path) -> list[str]:
    registry = load_json(root / ".agents" / "project-template" / "client-bridges.json", {})
    bridges = registry.get("bridges") if isinstance(registry.get("bridges"), list) else []
    return sorted(
        str(item.get("id"))
        for item in bridges
        if isinstance(item, dict) and item.get("discovery") != "verified-by-fresh-session"
    )


def check(identifier: str, status: str, evidence: Any) -> dict[str, Any]:
    return {"id": identifier, "status": status, "evidence": evidence}


def audit(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    license_path = next((root / name for name in LICENSE_NAMES if (root / name).is_file()), None)
    security_path = root / "SECURITY.md"
    notice_path = root / ".agents" / "THIRD_PARTY_NOTICES.md"
    notice_text = notice_path.read_text(encoding="utf-8") if notice_path.is_file() else ""
    action_refs, action_blockers = workflow_action_refs(root)
    vendor_summary, vendor_blockers = vendor_governance(root, notice_text)
    secret_findings = secret_signature_paths(root)
    unverified_clients = client_evidence(root)

    blockers: list[str] = []
    checks: list[dict[str, Any]] = []
    if license_path is None:
        blockers.append("PROJECT_LICENSE_MISSING")
        checks.append(check("project-license", "block", {"reason": "PROJECT_LICENSE_MISSING"}))
    else:
        checks.append(check("project-license", "pass", {"path": license_path.relative_to(root).as_posix()}))
    if security_path.is_file():
        checks.append(check("security-policy", "pass", {"path": "SECURITY.md"}))
    else:
        blockers.append("SECURITY_POLICY_MISSING")
        checks.append(check("security-policy", "block", {"reason": "SECURITY_POLICY_MISSING"}))
    if notice_path.is_file():
        checks.append(check("third-party-notices", "pass", {"path": ".agents/THIRD_PARTY_NOTICES.md"}))
    else:
        blockers.append("THIRD_PARTY_NOTICE_MISSING")
        checks.append(check("third-party-notices", "block", {"reason": "THIRD_PARTY_NOTICE_MISSING"}))
    blockers.extend(action_blockers)
    checks.append(check("workflow-action-pins", "pass" if not action_blockers else "block", action_refs))
    blockers.extend(vendor_blockers)
    checks.append(check("vendor-and-research-provenance", "pass" if not vendor_blockers else "block", vendor_summary))
    if secret_findings:
        blockers.append("TRACKED_SECRET_SIGNATURE_DETECTED")
    checks.append(
        check(
            "tracked-secret-signatures",
            "block" if secret_findings else "pass",
            {"findings": secret_findings, "values_reported": False},
        )
    )
    checks.append(
        check(
            "non-codex-client-evidence",
            "warn" if unverified_clients else "pass",
            {"client_ids": unverified_clients},
        )
    )
    manual_gates = [
        "HOST_VISIBILITY_REVERIFY_REQUIRED",
        "HOST_SECURITY_SETTINGS_REVIEW_REQUIRED",
        "OWNER_PUBLICATION_APPROVAL_REQUIRED",
    ]
    unique_blockers = sorted(set(blockers))
    engineering_ready = not unique_blockers
    return {
        "ok": True,
        "state": "PENDING_MANUAL_APPROVAL" if engineering_ready else "BLOCKED",
        "publication_ready": False,
        "engineering_ready": engineering_ready,
        "project_root": str(root),
        "blockers": unique_blockers,
        "manual_gates": manual_gates,
        "warnings": ["NON_CODEX_CLIENT_EVIDENCE_INCOMPLETE"] if unverified_clients else [],
        "checks": checks,
        "network_contacted": False,
        "state_changed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Agent OS public-release readiness")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("audit")
    command.add_argument("--root", default=str(PROJECT_ROOT))
    args = parser.parse_args()
    result = audit(Path(args.root))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
