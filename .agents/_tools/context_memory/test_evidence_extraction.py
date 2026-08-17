#!/usr/bin/env python3
"""BR3b0 focused parity shard for extracted Git evidence helpers."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

import agent_os_context_memory as facade
from context_memory import evidence

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


class FakeService:
    def __init__(self, root: Path):
        self.project_root = root
        self._legacy_evidence_cache: dict[tuple[str, str, str], str | None] = {}
        self.git_calls: list[tuple[str, ...]] = []
        self.blob_calls: list[tuple[str, str]] = []

    def evidence_path(self, relative: str) -> Path:
        return self.project_root / relative

    def git(self, *arguments: str) -> str | None:
        self.git_calls.append(arguments)
        return None

    def head(self) -> str | None:
        return COMMIT

    def commit_exists(self, commit: str) -> bool:
        return commit == COMMIT

    def commit_is_ancestor(self, commit: str) -> bool:
        return commit in {COMMIT, OTHER_COMMIT}

    def git_blob_bytes(self, commit: str, relative: str) -> bytes | None:
        self.blob_calls.append((commit, relative))
        return b"payload"

    def git_path_is_clean(self, relative: str) -> bool:
        del relative
        return True

    def binding(self) -> dict[str, Any]:
        return {"repository": {"remote_aliases": ["Owner/Repo.git"]}}

    @staticmethod
    def normalize_remote(value: str) -> str:
        return evidence.normalize_remote(value)


def case_facade_core_delegates(base: Path) -> bool:
    del base
    service = object.__new__(facade.ContextMemoryService)
    originals = (
        evidence.git,
        evidence.head,
        evidence.commit_is_ancestor,
        evidence.commit_exists,
        evidence.git_blob_bytes,
        evidence.git_path_is_clean,
    )
    evidence.git = lambda received, *args: (
        "git" if received is service and args == ("status",) else None
    )
    evidence.head = lambda received: COMMIT if received is service else None
    evidence.commit_is_ancestor = lambda received, commit: (
        received is service and commit == COMMIT
    )
    evidence.commit_exists = lambda received, commit: (
        received is service and commit == COMMIT
    )
    evidence.git_blob_bytes = lambda received, commit, path: (
        b"blob" if received is service and (commit, path) == (COMMIT, "a") else None
    )
    evidence.git_path_is_clean = lambda received, path: (
        received is service and path == "a"
    )
    try:
        return (
            service.git("status") == "git"
            and service.head() == COMMIT
            and service.commit_is_ancestor(COMMIT)
            and service.commit_exists(COMMIT)
            and service.git_blob_bytes(COMMIT, "a") == b"blob"
            and service.git_path_is_clean("a")
        )
    finally:
        (
            evidence.git,
            evidence.head,
            evidence.commit_is_ancestor,
            evidence.commit_exists,
            evidence.git_blob_bytes,
            evidence.git_path_is_clean,
        ) = originals


def case_facade_reference_delegates(base: Path) -> bool:
    del base
    service = object.__new__(facade.ContextMemoryService)
    originals = (
        evidence.committed_evidence_ref,
        evidence.validate_git_evidence_ref,
        evidence.find_reachable_evidence_commit,
        evidence.current_remote_aliases,
    )
    evidence.committed_evidence_ref = lambda received, path: (
        ({"path": path}, []) if received is service else (None, [])
    )
    evidence.validate_git_evidence_ref = lambda received, ref, *, require_current: (
        []
        if received is service and ref == {"x": 1} and require_current
        else [{"code": "BAD"}]
    )
    evidence.find_reachable_evidence_commit = (
        lambda received, path, digest, preferred=None: (
            preferred if received is service and path == "a" and digest == "d" else None
        )
    )
    evidence.current_remote_aliases = lambda received: (
        {"owner/repo"} if received is service else set()
    )
    try:
        return (
            service.committed_evidence_ref("a") == ({"path": "a"}, [])
            and service.validate_git_evidence_ref({"x": 1}, require_current=True) == []
            and service.find_reachable_evidence_commit("a", "d", COMMIT) == COMMIT
            and service.current_remote_aliases() == {"owner/repo"}
            and service.normalize_remote("git@github.com:Owner/Repo.git")
            == "owner/repo"
        )
    finally:
        (
            evidence.committed_evidence_ref,
            evidence.validate_git_evidence_ref,
            evidence.find_reachable_evidence_commit,
            evidence.current_remote_aliases,
        ) = originals


def case_git_command_contract(base: Path) -> bool:
    service = FakeService(base)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    original = evidence.subprocess.run
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout=" value \n"),
            SimpleNamespace(returncode=1, stdout="ignored"),
        ]
    )

    def fake_run(command: list[str], **options: Any) -> Any:
        calls.append((command, options))
        return next(responses)

    evidence.subprocess.run = fake_run
    try:
        return (
            evidence.git(service, "rev-parse", "HEAD") == "value"
            and evidence.git(service, "bad") is None
            and calls[0][0] == ["git", "rev-parse", "HEAD"]
            and calls[0][1]["timeout"] == 10
            and calls[0][1]["cwd"] == base
        )
    finally:
        evidence.subprocess.run = original


def case_head_contract(base: Path) -> bool:
    service = FakeService(base)
    service.git = lambda *args: COMMIT if args == ("rev-parse", "HEAD") else None
    valid = evidence.head(service) == COMMIT
    service.git = lambda *args: "short"
    return valid and evidence.head(service) is None


def case_commit_command_contract(base: Path) -> bool:
    service = FakeService(base)
    calls: list[list[str]] = []
    original = evidence.subprocess.run

    def fake_run(command: list[str], **options: Any) -> Any:
        del options
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b"")

    evidence.subprocess.run = fake_run
    try:
        return (
            not evidence.commit_exists(service, "bad")
            and not evidence.commit_is_ancestor(service, "bad")
            and evidence.commit_exists(service, COMMIT)
            and evidence.commit_is_ancestor(service, COMMIT)
            and calls
            == [
                ["git", "cat-file", "-e", f"{COMMIT}^{{commit}}"],
                ["git", "merge-base", "--is-ancestor", COMMIT, "HEAD"],
            ]
        )
    finally:
        evidence.subprocess.run = original


def case_blob_contract(base: Path) -> bool:
    service = FakeService(base)
    original = evidence.subprocess.run
    captured: list[str] = []

    def fake_run(command: list[str], **options: Any) -> Any:
        del options
        captured.extend(command)
        return SimpleNamespace(returncode=0, stdout=b"blob")

    evidence.subprocess.run = fake_run
    try:
        return evidence.git_blob_bytes(
            service, COMMIT, "docs/a.md"
        ) == b"blob" and captured == ["git", "cat-file", "blob", f"{COMMIT}:docs/a.md"]
    finally:
        evidence.subprocess.run = original


def case_clean_checks_both_indexes(base: Path) -> bool:
    service = FakeService(base)
    original = evidence.subprocess.run
    commands: list[list[str]] = []

    def fake_run(command: list[str], **options: Any) -> Any:
        del options
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=b"")

    evidence.subprocess.run = fake_run
    try:
        return evidence.git_path_is_clean(service, "docs/a.md") and commands == [
            ["git", "diff", "--quiet", "--no-ext-diff", "--", "docs/a.md"],
            ["git", "diff", "--cached", "--quiet", "--no-ext-diff", "--", "docs/a.md"],
        ]
    finally:
        evidence.subprocess.run = original


def case_committed_ref_contract(base: Path) -> bool:
    service = FakeService(base)
    path = base / "docs" / "a.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"working-copy")
    ref, errors = evidence.committed_evidence_ref(service, "docs/a.md")
    return errors == [] and ref == {
        "path": "docs/a.md",
        "sha256": facade.sha256_bytes(b"payload"),
        "git_commit": COMMIT,
    }


def case_validate_ref_contract(base: Path) -> bool:
    service = FakeService(base)
    path = base / "docs" / "a.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"payload")
    expected = facade.sha256_bytes(b"payload")
    valid = {"path": "docs/a.md", "sha256": expected, "git_commit": COMMIT}
    mismatch = {"path": "docs/a.md", "sha256": "0" * 64, "git_commit": COMMIT}
    return (
        evidence.validate_git_evidence_ref(service, valid, require_current=True) == []
        and evidence.validate_git_evidence_ref(
            service, mismatch, require_current=False
        )[0]["code"]
        == "CONTEXT_EVIDENCE_GIT_HASH_MISMATCH"
    )


def case_reachable_cache_and_remotes(base: Path) -> bool:
    service = FakeService(base)
    expected = facade.sha256_bytes(b"payload")
    service.git = lambda *args: (
        f"{OTHER_COMMIT}\n{COMMIT}"
        if args[0] == "log"
        else "origin git@github.com:Owner/Repo.git (fetch)"
    )
    first = evidence.find_reachable_evidence_commit(
        service, "docs/a.md", expected, OTHER_COMMIT
    )
    blob_count = len(service.blob_calls)
    second = evidence.find_reachable_evidence_commit(
        service, "docs/a.md", expected, OTHER_COMMIT
    )
    aliases = evidence.current_remote_aliases(service)
    return (
        first == OTHER_COMMIT
        and second == OTHER_COMMIT
        and len(service.blob_calls) == blob_count
        and aliases == {"owner/repo"}
    )


CASES = [
    ("facade-core-delegation", case_facade_core_delegates),
    ("facade-reference-delegation", case_facade_reference_delegates),
    ("git-command", case_git_command_contract),
    ("head", case_head_contract),
    ("commit-commands", case_commit_command_contract),
    ("blob", case_blob_contract),
    ("clean-indexes", case_clean_checks_both_indexes),
    ("committed-ref", case_committed_ref_contract),
    ("validate-ref", case_validate_ref_contract),
    ("reachable-cache-remotes", case_reachable_cache_and_remotes),
]


def main() -> None:
    results = []
    with tempfile.TemporaryDirectory(prefix="aos15-br3b0-") as temporary:
        for index, (name, check) in enumerate(CASES):
            try:
                passed, error = bool(check(Path(temporary) / str(index))), None
            except Exception as exc:  # noqa: BLE001 - bounded case diagnostics
                passed, error = False, str(exc)
            results.append(
                {"id": name, "passed": passed, **({"error": error} if error else {})}
            )
    output = {
        "ok": all(item["passed"] for item in results),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
