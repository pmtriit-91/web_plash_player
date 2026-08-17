#!/usr/bin/env python3
"""Twelve focused checks for the direct-root cardinality primitive."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from root_cardinality import check_root_cardinality

TOOL = Path(__file__).with_name("root_cardinality.py")
CONTRACT_PATH = "tools/tooling_topology/topology.json"
MISSING_CONTRACT = object()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=root, text=True, timeout=10
    ).strip()


def _write(root: Path, relative: str, content: str = "x\n") -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _exception(
    *,
    name: str = "approved.py",
    role: str = "stable-public-entrypoint",
    caller_path: str = "group/caller.py",
) -> dict[str, str]:
    return {
        "name": name,
        "owner": "fixture-owner",
        "role": role,
        "caller_path": caller_path,
    }


def _repository(
    parent: Path,
    identifier: str,
    exception_entries: Any = MISSING_CONTRACT,
) -> tuple[Path, str]:
    root = parent / identifier
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Agent OS Test")
    _git(root, "config", "user.email", "agent-os@example.invalid")
    _write(root, ".gitignore", "*.cache\n")
    _write(root, "tools/a.py")
    _write(root, "tools/group/old.py")
    if exception_entries is not MISSING_CONTRACT:
        _write(root, "tools/group/caller.py")
        _write(
            root,
            CONTRACT_PATH,
            json.dumps({"direct_root_exceptions": exception_entries}) + "\n",
        )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root, _git(root, "rev-parse", "HEAD")


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": bool(passed)})

    with tempfile.TemporaryDirectory() as temporary:
        parent = Path(temporary)

        root, base = _repository(parent, "clean")
        result = check_root_cardinality(root, base, "tools")
        check(
            "clean-baseline-is-admitted",
            result["ok"] and result["baseline_direct_files"] == 1,
        )

        root, base = _repository(parent, "nested")
        _write(root, "tools/group/new.py")
        _write(root, "tools/ignored.cache")
        result = check_root_cardinality(root, base, "tools")
        check(
            "nested-and-ignored-additions-do-not-grow-root",
            result["ok"] and result["current_direct_files"] == 1,
        )

        root, base = _repository(parent, "addition")
        _write(root, "tools/new.py")
        result = check_root_cardinality(root, base, "tools")
        check(
            "direct-addition-blocks-with-exact-path",
            result["reason_codes"]
            == ["ROOT_DIRECT_FILE_ADDED", "ROOT_DIRECT_FILE_CARDINALITY_GROWTH"]
            and result["offending_paths"] == ["tools/new.py"],
        )

        root, base = _repository(parent, "replacement")
        (root / "tools/a.py").unlink()
        _write(root, "tools/new.py")
        result = check_root_cardinality(root, base, "tools")
        check(
            "one-for-one-replacement-still-blocks-new-name",
            result["reason_codes"] == ["ROOT_DIRECT_FILE_ADDED"]
            and result["removed_direct_files"] == ["a.py"],
        )

        root, base = _repository(parent, "removal")
        (root / "tools/a.py").unlink()
        result = check_root_cardinality(root, base, "tools")
        check(
            "direct-removal-is-admitted",
            result["ok"] and result["removed_direct_files"] == ["a.py"],
        )

        root, _ = _repository(parent, "bad-base")
        result = check_root_cardinality(root, "not-a-commit", "tools")
        check(
            "invalid-base-fails-closed",
            result["reason_codes"] == ["ROOT_CARDINALITY_BASE_COMMIT_INVALID"],
        )

        root, base = _repository(parent, "bad-directory")
        unsafe = check_root_cardinality(root, base, "../tools")
        noncanonical = check_root_cardinality(root, base, "tools/")
        (root / "tools/a.py").unlink()
        (root / "tools/group/old.py").unlink()
        (root / "tools/group").rmdir()
        (root / "tools").rmdir()
        missing = check_root_cardinality(root, base, "tools")
        check(
            "unsafe-and-missing-directories-fail-closed",
            unsafe["reason_codes"] == ["ROOT_CARDINALITY_DIRECTORY_UNSAFE"]
            and noncanonical["reason_codes"] == ["ROOT_CARDINALITY_DIRECTORY_UNSAFE"]
            and missing["reason_codes"] == ["ROOT_CARDINALITY_DIRECTORY_INVALID"],
        )

        root, base = _repository(parent, "cli")
        cli = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "check",
                "--root",
                str(root),
                "--base-commit",
                base,
                "--directory",
                "tools",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        check(
            "cli-preserves-result-and-exit-contract",
            cli.returncode == 0 and json.loads(cli.stdout)["state"] == "ADMITTED",
        )

        root, base = _repository(parent, "approved", [_exception()])
        _write(root, "tools/approved.py")
        result = check_root_cardinality(
            root, base, "tools", exception_contract=CONTRACT_PATH
        )
        check(
            "base-approved-stable-entrypoint-is-admitted",
            result["ok"] and result["approved_direct_files"] == ["approved.py"],
        )

        root, base = _repository(parent, "exact-name", [_exception()])
        _write(root, "tools/approved-v2.py")
        exact = check_root_cardinality(
            root, base, "tools", exception_contract=CONTRACT_PATH
        )
        root, base = _repository(parent, "self-authorized", [])
        _write(
            root,
            CONTRACT_PATH,
            json.dumps({"direct_root_exceptions": [_exception()]}) + "\n",
        )
        _write(root, "tools/approved.py")
        self_authorized = check_root_cardinality(
            root, base, "tools", exception_contract=CONTRACT_PATH
        )
        check(
            "matching-is-exact-and-worktree-cannot-self-authorize",
            exact["reason_codes"]
            == ["ROOT_DIRECT_FILE_ADDED", "ROOT_DIRECT_FILE_CARDINALITY_GROWTH"]
            and self_authorized["reason_codes"]
            == ["ROOT_DIRECT_FILE_ADDED", "ROOT_DIRECT_FILE_CARDINALITY_GROWTH"],
        )

        root, base = _repository(
            parent,
            "invalid-taxonomy",
            [_exception(role="internal-implementation")],
        )
        _write(root, "tools/approved.py")
        invalid_taxonomy = check_root_cardinality(
            root, base, "tools", exception_contract=CONTRACT_PATH
        )
        check(
            "internal-role-contract-fails-closed",
            invalid_taxonomy["reason_codes"]
            == ["ROOT_CARDINALITY_EXCEPTION_CONTRACT_INVALID"],
        )

        root, base = _repository(parent, "missing-contract")
        _write(root, "tools/approved.py")
        missing_contract = check_root_cardinality(
            root, base, "tools", exception_contract=CONTRACT_PATH
        )
        root, base = _repository(parent, "malformed-contract", {})
        _write(root, "tools/approved.py")
        malformed_contract = check_root_cardinality(
            root, base, "tools", exception_contract=CONTRACT_PATH
        )
        check(
            "missing-and-malformed-contracts-fail-closed",
            missing_contract["reason_codes"]
            == ["ROOT_CARDINALITY_EXCEPTION_CONTRACT_INVALID"]
            and malformed_contract["reason_codes"]
            == ["ROOT_CARDINALITY_EXCEPTION_CONTRACT_INVALID"],
        )

    passed = sum(1 for item in cases if item["passed"])
    output = {
        "ok": passed == len(cases),
        "passed": passed,
        "total": len(cases),
        "results": cases,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
