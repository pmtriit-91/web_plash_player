#!/usr/bin/env python3
"""Fail-closed direct-file cardinality check for a repository directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

GIT_TIMEOUT_SECONDS = 10
EXCEPTION_CONTRACT_MAX_BYTES = 65_536
EXCEPTION_ROLES = {"stable-public-entrypoint", "global-runner"}


def _blocked(code: str, path: str | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "BLOCKED",
        "reason_codes": [code],
        "offending_paths": [path] if path else [],
    }


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=root,
        stderr=subprocess.DEVNULL,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def _safe_directory(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and path.parts not in {(), (".",)}
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
        and "\\" not in value
        and not any(ord(character) < 32 for character in value)
    )


def _safe_direct_name(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith(".py"):
        return False
    path = PurePosixPath(value)
    stem = path.stem.lower()
    return (
        path.parts == (value,)
        and value not in {".", ".."}
        and "\\" not in value
        and not any(ord(character) < 32 for character in value)
        and not stem.startswith("test")
        and "support" not in stem
    )


def _names_hash(names: set[str]) -> str:
    payload = "".join(f"{name}\n" for name in sorted(names)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _baseline_names(root: Path, commit: str, directory: str) -> set[str]:
    treeish = f"{commit}:{directory}"
    if _git(root, "cat-file", "-t", treeish).strip() != b"tree":
        raise ValueError("baseline directory is not a tree")
    names: set[str] = set()
    for record in _git(root, "ls-tree", "-z", treeish).split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        if metadata.split()[1] != b"tree":
            names.add(raw_name.decode("utf-8"))
    return names


def _worktree_names(root: Path, directory: str) -> set[str]:
    target_directory = root / directory
    if target_directory.is_symlink() or not target_directory.is_dir():
        raise ValueError("worktree directory is not a real directory")
    prefix = f"{directory}/"
    names: set[str] = set()
    raw_paths = _git(
        root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        directory,
    )
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8")
        if not relative.startswith(prefix):
            continue
        name = relative[len(prefix) :]
        candidate = root / relative
        if "/" not in name and (candidate.is_file() or candidate.is_symlink()):
            names.add(name)
    return names


def _base_exception_names(
    root: Path,
    commit: str,
    directory: str,
    contract_path: str,
) -> set[str]:
    if not _safe_directory(contract_path):
        raise ValueError("unsafe exception contract path")
    treeish = f"{commit}:{contract_path}"
    if _git(root, "cat-file", "-t", treeish).strip() != b"blob":
        raise ValueError("exception contract is not a blob")
    raw_size = _git(root, "cat-file", "-s", treeish).strip()
    if not raw_size.isdigit() or int(raw_size) > EXCEPTION_CONTRACT_MAX_BYTES:
        raise ValueError("exception contract is oversized")
    try:
        contract = json.loads(_git(root, "cat-file", "blob", treeish).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("exception contract is malformed") from error
    entries = (
        contract.get("direct_root_exceptions")
        if isinstance(contract, dict)
        else None
    )
    if not isinstance(entries, list) or len(entries) > 64:
        raise ValueError("exception contract entries are missing or invalid")
    allowed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "name",
            "owner",
            "role",
            "caller_path",
        }:
            raise ValueError("exception entry shape is invalid")
        name = entry.get("name")
        owner = entry.get("owner")
        role = entry.get("role")
        caller_path = entry.get("caller_path")
        if (
            not _safe_direct_name(name)
            or not isinstance(owner, str)
            or not 1 <= len(owner) <= 128
            or owner.strip() != owner
            or any(ord(character) < 32 for character in owner)
            or role not in EXCEPTION_ROLES
            or not isinstance(caller_path, str)
            or not _safe_directory(caller_path)
            or "/" not in caller_path
            or not caller_path.endswith(".py")
            or name in allowed
        ):
            raise ValueError("exception entry values are invalid")
        caller_treeish = f"{commit}:{directory}/{caller_path}"
        if _git(root, "cat-file", "-t", caller_treeish).strip() != b"blob":
            raise ValueError("exception caller is not a committed blob")
        allowed.add(name)
    return allowed


def check_root_cardinality(
    repository: Path,
    base_commit: str,
    directory: str,
    *,
    exception_contract: str | None = None,
) -> dict[str, Any]:
    """Compare direct file names at ``base_commit`` with the current worktree."""
    if not _safe_directory(directory):
        return _blocked("ROOT_CARDINALITY_DIRECTORY_UNSAFE", directory)
    try:
        root = Path(_git(repository, "rev-parse", "--show-toplevel").decode().strip())
    except (FileNotFoundError, subprocess.SubprocessError, UnicodeDecodeError):
        return _blocked("ROOT_CARDINALITY_GIT_UNAVAILABLE")
    try:
        resolved = (
            _git(
                root,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{base_commit}^{{commit}}",
            )
            .decode()
            .strip()
        )
    except (subprocess.SubprocessError, UnicodeDecodeError):
        return _blocked("ROOT_CARDINALITY_BASE_COMMIT_INVALID", base_commit)
    try:
        baseline = _baseline_names(root, resolved, directory)
        current = _worktree_names(root, directory)
    except UnicodeDecodeError:
        return _blocked("ROOT_CARDINALITY_PATH_ENCODING_INVALID", directory)
    except (ValueError, subprocess.SubprocessError):
        return _blocked("ROOT_CARDINALITY_DIRECTORY_INVALID", directory)

    added = sorted(current - baseline)
    removed = sorted(baseline - current)
    approved: list[str] = []
    if added and exception_contract is not None:
        try:
            allowed = _base_exception_names(
                root, resolved, directory, exception_contract
            )
        except (ValueError, subprocess.SubprocessError):
            return {
                "ok": False,
                "state": "BLOCKED",
                "base_commit": resolved,
                "directory": directory,
                "exception_contract": exception_contract,
                "baseline_direct_files": len(baseline),
                "current_direct_files": len(current),
                "baseline_names_sha256": _names_hash(baseline),
                "current_names_sha256": _names_hash(current),
                "added_direct_files": added,
                "removed_direct_files": removed,
                "approved_direct_files": [],
                "unapproved_direct_files": added,
                "reason_codes": ["ROOT_CARDINALITY_EXCEPTION_CONTRACT_INVALID"],
                "offending_paths": [f"{directory}/{name}" for name in added],
            }
        approved = sorted(set(added) & allowed)
    unapproved = sorted(set(added) - set(approved))
    reasons: list[str] = []
    if unapproved:
        reasons.append("ROOT_DIRECT_FILE_ADDED")
    if len(current - set(approved)) > len(baseline):
        reasons.append("ROOT_DIRECT_FILE_CARDINALITY_GROWTH")
    return {
        "ok": not reasons,
        "state": "ADMITTED" if not reasons else "BLOCKED",
        "base_commit": resolved,
        "directory": directory,
        "exception_contract": exception_contract,
        "baseline_direct_files": len(baseline),
        "current_direct_files": len(current),
        "baseline_names_sha256": _names_hash(baseline),
        "current_names_sha256": _names_hash(current),
        "added_direct_files": added,
        "removed_direct_files": removed,
        "approved_direct_files": approved,
        "unapproved_direct_files": unapproved,
        "reason_codes": reasons,
        "offending_paths": [f"{directory}/{name}" for name in unapproved],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--root", type=Path, default=Path.cwd())
    check.add_argument("--base-commit", required=True)
    check.add_argument("--directory", default=".agents/_tools")
    check.add_argument("--exception-contract")
    arguments = parser.parse_args()
    result = check_root_cardinality(
        arguments.root,
        arguments.base_commit,
        arguments.directory,
        exception_contract=arguments.exception_contract,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
