#!/usr/bin/env python3
"""Focused W6 proof for clean-clone recovery from reachable Git evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CATALOG = Path(".agents/project/context/continuity.json")
PROJECTION = Path(".agents/project/context/continuity-projection.json")
CONTINUITY_CLI = Path(".agents/_tools/agent_os_continuity_transactions.py")
CONTEXT_MEMORY_CLI = Path(".agents/_tools/agent_os_context_memory.py")
EXPECTED_CRITICAL_SET = {
    "active-task-ledger",
    "agent-os-release",
    "context-manifest",
    "current-status",
    "project-binding",
    "project-genesis",
    "roadmap",
}
EXPECTED_BOOT_REFERENCES = {
    "active-task-ledger",
    "agent-os-release",
    "context-manifest",
    "current-status",
    "project-binding",
}


def run(
    root: Path,
    *command: str,
    timeout: int = 90,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_json(root: Path, *command: str, timeout: int = 90) -> dict[str, Any]:
    completed = run(root, *command, timeout=timeout, check=False)
    start = completed.stdout.find("{")
    if start < 0:
        raise ValueError(
            f"JSON payload missing from {' '.join(command)}: "
            f"exit={completed.returncode} stderr={completed.stderr[-400:]}"
        )
    payload = json.loads(completed.stdout[start:])
    if not isinstance(payload, dict):
        raise TypeError("JSON payload must be an object")
    return payload


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def decoded_target(plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    change = next(
        item
        for item in plan.get("changes", [])
        if str(item.get("path", "")).endswith(suffix)
    )
    payload = json.loads(base64.b64decode(change["after_base64"]))
    if not isinstance(payload, dict):
        raise TypeError(f"decoded target must be an object: {suffix}")
    return payload


def committed_bytes(clone: Path, commit: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=clone,
        check=False,
        capture_output=True,
        timeout=15,
    )
    return completed.stdout if completed.returncode == 0 else None


def main() -> None:
    cases: list[tuple[str, bool]] = []
    canonical_before = {
        CATALOG: (ROOT / CATALOG).read_bytes(),
        PROJECTION: (ROOT / PROJECTION).read_bytes(),
    }

    with tempfile.TemporaryDirectory(prefix="aos15-p2c-clean-clone-") as temporary:
        clone = Path(temporary) / "repo"
        run(
            ROOT,
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            str(ROOT),
            str(clone),
            timeout=30,
        )
        canonical_head = run(ROOT, "git", "rev-parse", "HEAD").stdout.strip()
        clone_head = run(clone, "git", "rev-parse", "HEAD").stdout.strip()
        clean_before = run(
            clone, "git", "status", "--porcelain", "--untracked-files=all"
        ).stdout

        planned = run_json(
            clone,
            sys.executable,
            str(CONTINUITY_CLI),
            "plan-refresh",
            timeout=110,
        )
        plan = planned.get("plan", {})
        metadata = plan.get("metadata", {})
        catalog = decoded_target(plan, "continuity.json")
        projection = decoded_target(plan, "continuity-projection.json")
        references = {
            item.get("reference_id"): item
            for item in catalog.get("references", [])
            if isinstance(item, dict)
        }
        required = [
            item
            for item in references.values()
            if item.get("requirement") == "required"
        ]
        reachable_required = []
        for reference in required:
            source = reference.get("source", {})
            content = committed_bytes(
                clone,
                str(source.get("git_commit", "")),
                str(source.get("path", "")),
            )
            reachable_required.append(
                source.get("git_commit") == clone_head
                and content is not None
                and digest(content) == source.get("sha256")
            )
        genesis = references.get("project-genesis", {})
        genesis_source = genesis.get("source", {})
        genesis_content = committed_bytes(
            clone,
            clone_head,
            str(genesis_source.get("path", "")),
        )
        boot = {
            item.get("reference_id"): item.get("readiness")
            for item in projection.get("boot_references", [])
            if isinstance(item, dict)
        }
        context = run_json(
            clone,
            sys.executable,
            str(CONTEXT_MEMORY_CLI),
            "load",
            "--tier",
            "hot",
            timeout=30,
        )
        clean_after = run(
            clone, "git", "status", "--porcelain", "--untracked-files=all"
        ).stdout

        cases.extend(
            [
                (
                    "clone-binds-exact-reachable-head",
                    clone_head == canonical_head == plan.get("git_head"),
                ),
                (
                    "clone-starts-and-remains-tracked-clean",
                    clean_before == "" and clean_after == "",
                ),
                (
                    "refresh-plan-is-generation-two-and-plan-only",
                    planned.get("ok") is True
                    and plan.get("operation") == "refresh"
                    and metadata.get("source_generation") == 2
                    and metadata.get("target_generation") == 2
                    and plan.get("commit_created") is False
                    and plan.get("push_performed") is False,
                ),
                (
                    "critical-set-is-restored-seven-of-seven",
                    set(metadata.get("critical_set_before", []))
                    == EXPECTED_CRITICAL_SET
                    and metadata.get("critical_set_before")
                    == metadata.get("critical_set_after"),
                ),
                (
                    "refresh-target-is-exactly-catalog-and-projection",
                    {
                        str(item.get("path"))
                        for item in plan.get("changes", [])
                    }
                    == {
                        "project/context/continuity.json",
                        "project/context/continuity-projection.json",
                    },
                ),
                (
                    "all-six-required-sources-are-byte-reachable",
                    len(required) == 6 and all(reachable_required),
                ),
                (
                    "all-five-boot-references-are-available",
                    set(boot) == EXPECTED_BOOT_REFERENCES
                    and set(boot.values()) == {"available"},
                ),
                (
                    "roadmap-remains-reachable-just-in-time-authority",
                    references.get("roadmap", {}).get("load_policy")
                    == "just-in-time"
                    and references.get("roadmap", {}).get("requirement")
                    == "required",
                ),
                (
                    "genesis-remains-explicit-state-aware-missing",
                    genesis.get("requirement") == "state-aware"
                    and genesis_source.get("sha256") is None
                    and genesis_source.get("git_commit") is None
                    and genesis_content is None
                    and "project-genesis" not in boot,
                ),
                (
                    "privacy-and-canonical-workspace-remain-unchanged",
                    context.get("raw_conversation_stored") is False
                    and all(
                        (ROOT / path).read_bytes() == content
                        for path, content in canonical_before.items()
                    ),
                ),
            ]
        )

    failed = [case_id for case_id, passed in cases if not passed]
    print(
        json.dumps(
            {
                "ok": not failed,
                "passed": len(cases) - len(failed),
                "total": len(cases),
                "cases": [
                    {"id": case_id, "passed": passed}
                    for case_id, passed in cases
                ],
                "failed": failed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if not failed else 2)


if __name__ == "__main__":
    main()
