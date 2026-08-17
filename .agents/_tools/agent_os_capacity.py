#!/usr/bin/env python3
"""Dependency-free task file-growth ratchet derived from Git and worktree bytes."""

from __future__ import annotations

import argparse
import json
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from tooling_topology.root_cardinality import check_root_cardinality

ARTIFACT_CLASSES = {"source-test", "documentation", "data", "generated"}
INPUT_MAX_BYTES = 1_048_576
FULL_COMMIT_LENGTH = 40
TOOLS_ROOT = ".agents/_tools"
TOOLS_ROOT_EXCEPTION_CONTRACT = ".agents/_tools/tooling_topology/topology.json"


class CapacityError(ValueError):
    def __init__(self, reason_code: str, path: str | None = None) -> None:
        self.reason_code = reason_code
        self.path = path
        super().__init__(reason_code)


def _git(
    root: Path, arguments: list[str], *, binary: bool = False
) -> bytes | str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=not binary,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout
    return output if isinstance(output, bytes) else output.strip()


def _relative(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise CapacityError("CAPACITY_PATH_UNSAFE")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise CapacityError("CAPACITY_PATH_UNSAFE", value)
    return parsed.as_posix()


def _positive_int(value: Any, *, allow_zero: bool = True) -> bool:
    return type(value) is int and value >= (0 if allow_zero else 1)


def _parse_envelope(value: Any) -> tuple[str, dict[str, int], dict[str, str]]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "base_commit",
        "budgets",
        "paths",
    }:
        raise CapacityError("CAPACITY_ENVELOPE_INVALID")
    budgets = value.get("budgets")
    required_budgets = {
        "oversized_source_test_lines",
        "source_test_growth_lines",
        "documentation_growth_lines",
        "data_growth_bytes",
        "max_file_bytes",
    }
    if (
        value.get("schema_version") != 1
        or not isinstance(value.get("base_commit"), str)
        or not isinstance(budgets, dict)
        or set(budgets) != required_budgets
        or not all(
            _positive_int(budgets.get(key), allow_zero=key != "max_file_bytes")
            for key in required_budgets
        )
    ):
        raise CapacityError("CAPACITY_ENVELOPE_INVALID")
    raw_paths = value.get("paths")
    if not isinstance(raw_paths, list) or not 1 <= len(raw_paths) <= 64:
        raise CapacityError("CAPACITY_ENVELOPE_INVALID")
    rules: dict[str, str] = {}
    for entry in raw_paths:
        if not isinstance(entry, dict) or set(entry) != {"path", "artifact_class"}:
            raise CapacityError("CAPACITY_ENVELOPE_INVALID")
        relative = _relative(entry.get("path"))
        artifact_class = entry.get("artifact_class")
        if artifact_class not in ARTIFACT_CLASSES or relative in rules:
            raise CapacityError("CAPACITY_ENVELOPE_INVALID", relative)
        rules[relative] = str(artifact_class)
    return str(value["base_commit"]), budgets, rules


def _repository_root(candidate: Path) -> Path:
    resolved = _git(candidate.resolve(), ["rev-parse", "--show-toplevel"])
    if not isinstance(resolved, str) or not resolved:
        raise CapacityError("CAPACITY_GIT_UNAVAILABLE")
    return Path(resolved).resolve()


def _base_commit(root: Path, value: str) -> str:
    resolved = _git(root, ["rev-parse", "--verify", f"{value}^{{commit}}"])
    if not isinstance(resolved, str) or len(resolved) != FULL_COMMIT_LENGTH:
        raise CapacityError("CAPACITY_BASE_COMMIT_INVALID")
    return resolved


def _changed_paths(root: Path, base: str) -> set[str]:
    tracked = _git(
        root, ["diff", "--name-only", "--no-renames", "-z", base, "--"], binary=True
    )
    untracked = _git(
        root, ["ls-files", "--others", "--exclude-standard", "-z"], binary=True
    )
    if not isinstance(tracked, bytes) or not isinstance(untracked, bytes):
        raise CapacityError("CAPACITY_GIT_UNAVAILABLE")
    try:
        return {
            _relative(item.decode("utf-8"))
            for item in [*tracked.split(b"\0"), *untracked.split(b"\0")]
            if item
        }
    except UnicodeDecodeError as error:
        raise CapacityError("CAPACITY_PATH_UNSAFE") from error


def _base_bytes(root: Path, base: str, relative: str, maximum: int) -> bytes | None:
    listing = _git(root, ["ls-tree", "-z", base, "--", relative], binary=True)
    if not isinstance(listing, bytes):
        raise CapacityError("CAPACITY_GIT_UNAVAILABLE", relative)
    if not listing:
        return None
    mode = listing.split(b" ", 1)[0]
    if mode not in {b"100644", b"100755"}:
        raise CapacityError("CAPACITY_PATH_NOT_REGULAR", relative)
    size = _git(root, ["cat-file", "-s", f"{base}:{relative}"])
    if not isinstance(size, str) or not size.isdigit():
        raise CapacityError("CAPACITY_GIT_UNAVAILABLE", relative)
    if int(size) > maximum:
        raise CapacityError("CAPACITY_FILE_BYTE_LIMIT_EXCEEDED", relative)
    content = _git(root, ["cat-file", "blob", f"{base}:{relative}"], binary=True)
    if not isinstance(content, bytes):
        raise CapacityError("CAPACITY_GIT_UNAVAILABLE", relative)
    return content


def _current_bytes(root: Path, relative: str, maximum: int) -> bytes | None:
    source = root / relative
    try:
        before = source.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode):
        raise CapacityError("CAPACITY_PATH_NOT_REGULAR", relative)
    if before.st_size > maximum:
        raise CapacityError("CAPACITY_FILE_BYTE_LIMIT_EXCEEDED", relative)
    try:
        content = source.read_bytes()
        after = source.lstat()
    except OSError as error:
        raise CapacityError("CAPACITY_PATH_NOT_REGULAR", relative) from error
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or len(content) != after.st_size:
        raise CapacityError("CAPACITY_PATH_CHANGED_DURING_READ", relative)
    return content


def _line_count(content: bytes | None, relative: str) -> int:
    if content is None:
        return 0
    try:
        return len(content.decode("utf-8").splitlines())
    except UnicodeDecodeError as error:
        raise CapacityError("CAPACITY_TEXT_INVALID", relative) from error


def _failure(error: CapacityError) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "BLOCKED",
        "reason_codes": [error.reason_code],
        "offending_paths": [error.path] if error.path else [],
        "measurements": [],
        "generated": [],
    }


def _touches_tools_root(rules: dict[str, str]) -> bool:
    prefix = f"{TOOLS_ROOT}/"
    return any(path == TOOLS_ROOT or path.startswith(prefix) for path in rules)


def check_growth(repository: Path, envelope: Any) -> dict[str, Any]:
    try:
        root = _repository_root(repository)
        requested_base, budgets, rules = _parse_envelope(envelope)
        base = _base_commit(root, requested_base)
        root_cardinality: dict[str, Any] | None = None
        if _touches_tools_root(rules):
            root_cardinality = check_root_cardinality(
                root,
                base,
                TOOLS_ROOT,
                exception_contract=TOOLS_ROOT_EXCEPTION_CONTRACT,
            )
            if not root_cardinality["ok"]:
                return {
                    **root_cardinality,
                    "state": "STOP_AND_SPLIT",
                    "measurements": [],
                    "generated": [],
                    "root_cardinality": root_cardinality,
                }
        undeclared = sorted(_changed_paths(root, base) - set(rules))
        if undeclared:
            return {
                **_failure(CapacityError("CAPACITY_UNDECLARED_PATH_CHANGED")),
                "state": "STOP_AND_SPLIT",
                "offending_paths": undeclared,
                "base_commit": base,
            }
        measurements: list[dict[str, Any]] = []
        generated: list[dict[str, Any]] = []
        totals = {
            "source_test_growth_lines": 0,
            "documentation_growth_lines": 0,
            "data_growth_bytes": 0,
        }
        reasons: list[str] = []
        offending: set[str] = set()
        for relative, artifact_class in rules.items():
            before = _base_bytes(root, base, relative, budgets["max_file_bytes"])
            current = _current_bytes(root, relative, budgets["max_file_bytes"])
            item: dict[str, Any] = {
                "path": relative,
                "artifact_class": artifact_class,
                "base_bytes": len(before or b""),
                "current_bytes": len(current or b""),
            }
            if artifact_class in {"source-test", "documentation"}:
                base_lines = _line_count(before, relative)
                current_lines = _line_count(current, relative)
                growth = max(0, current_lines - base_lines)
                item.update(
                    base_lines=base_lines,
                    current_lines=current_lines,
                    growth_lines=growth,
                )
                total_key = (
                    "source_test_growth_lines"
                    if artifact_class == "source-test"
                    else "documentation_growth_lines"
                )
                totals[total_key] += growth
                if (
                    artifact_class == "source-test"
                    and max(base_lines, current_lines)
                    > budgets["oversized_source_test_lines"]
                    and current_lines > base_lines
                ):
                    reasons.append("CAPACITY_OVERSIZED_SOURCE_TEST_GROWTH")
                    offending.add(relative)
            elif artifact_class == "data":
                growth = max(0, len(current or b"") - len(before or b""))
                item["growth_bytes"] = growth
                totals["data_growth_bytes"] += growth
            else:
                generated.append(item)
                continue
            measurements.append(item)
        limits = (
            (
                "source_test_growth_lines",
                "CAPACITY_SOURCE_TEST_GROWTH_BUDGET_EXCEEDED",
                "source-test",
            ),
            (
                "documentation_growth_lines",
                "CAPACITY_DOCUMENTATION_GROWTH_BUDGET_EXCEEDED",
                "documentation",
            ),
            ("data_growth_bytes", "CAPACITY_DATA_GROWTH_BUDGET_EXCEEDED", "data"),
        )
        for key, reason, artifact_class in limits:
            if totals[key] > budgets[key]:
                reasons.append(reason)
                offending.update(
                    item["path"]
                    for item in measurements
                    if item["artifact_class"] == artifact_class
                )
        result = {
            "ok": not reasons,
            "state": "ADMITTED" if not reasons else "STOP_AND_SPLIT",
            "base_commit": base,
            "reason_codes": list(dict.fromkeys(reasons)),
            "offending_paths": sorted(offending),
            "totals": totals,
            "measurements": measurements,
            "generated": generated,
        }
        if root_cardinality is not None:
            result["root_cardinality"] = root_cardinality
        return result
    except CapacityError as error:
        return _failure(error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent OS task file-growth ratchet")
    parser.add_argument("check_growth", choices=["check-growth"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    source = Path(args.input).expanduser()
    try:
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > INPUT_MAX_BYTES:
            raise OSError("input must be a bounded regular file")
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        result = _failure(CapacityError("CAPACITY_ENVELOPE_INVALID"))
        result["error"] = str(error)
    else:
        result = check_growth(Path(args.root), envelope)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
