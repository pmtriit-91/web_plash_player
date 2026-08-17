#!/usr/bin/env python3
"""Fail closed on whitespace errors committed in the current CI change range."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
ZERO_COMMIT = "0" * 40
MAX_DIAGNOSTIC_BYTES = 65536


def run_git(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        timeout=30,
        check=False,
    )


def diagnostic(result: subprocess.CompletedProcess[bytes]) -> str:
    content = result.stdout + result.stderr
    if len(content) > MAX_DIAGNOSTIC_BYTES:
        content = content[:MAX_DIAGNOSTIC_BYTES] + b"\n[diagnostic truncated]\n"
    return content.decode("utf-8", errors="replace")


def resolve_base(explicit: str | None) -> str | None:
    candidates = (
        explicit,
        os.environ.get("AGENT_OS_CI_PR_BASE"),
        os.environ.get("AGENT_OS_CI_PUSH_BASE"),
    )
    return next((item.strip().lower() for item in candidates if isinstance(item, str) and item.strip()), None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=".")
    parser.add_argument("--base")
    args = parser.parse_args()

    repository = Path(args.repository).resolve()
    head_result = run_git(repository, ["rev-parse", "--verify", "HEAD"])
    if head_result.returncode != 0:
        print("Committed whitespace check failed: Git HEAD is unavailable.")
        print(diagnostic(head_result), end="")
        raise SystemExit(2)
    head = head_result.stdout.decode("ascii", errors="replace").strip().lower()
    if FULL_COMMIT.fullmatch(head) is None:
        print("Committed whitespace check failed: Git HEAD is not a full commit.")
        raise SystemExit(2)

    base = resolve_base(args.base)
    if base == ZERO_COMMIT:
        base = None
    if base is not None:
        if FULL_COMMIT.fullmatch(base) is None:
            print("Committed whitespace check failed: CI base is not a full commit.")
            raise SystemExit(2)
        exists = run_git(repository, ["cat-file", "-e", f"{base}^{{commit}}"])
        if exists.returncode != 0:
            print("Committed whitespace check failed: CI base commit is unavailable; use a full-history checkout.")
            print(diagnostic(exists), end="")
            raise SystemExit(2)
        committed = run_git(repository, ["diff", "--check", f"{base}..{head}", "--"])
        mode = f"range:{base[:12]}..{head[:12]}"
    else:
        committed = run_git(repository, ["diff-tree", "--check", "--root", "-m", "-r", head])
        mode = f"head:{head[:12]}"

    working = run_git(repository, ["diff", "--check", "--"])
    staged = run_git(repository, ["diff", "--cached", "--check", "--"])
    failures = [
        (label, result)
        for label, result in (("committed", committed), ("working-tree", working), ("staged", staged))
        if result.returncode != 0
    ]
    if failures:
        print(f"Whitespace check failed ({mode}).")
        for label, result in failures:
            print(f"[{label}]")
            print(diagnostic(result), end="")
        raise SystemExit(1)

    print(f"Whitespace check passed ({mode}); committed, working-tree and staged diffs are clean.")


if __name__ == "__main__":
    main()
