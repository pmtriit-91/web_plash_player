#!/usr/bin/env python3
"""BR3c1 focused shard for deep-doctor batch-reader integration."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools"))

from context_memory import evidence, handoff_validation

COMMIT = "a" * 40


class Service:
    def __init__(self, root: Path):
        self.project_root = root
        self.git_calls = 0

    def git(self, *_arguments: str) -> str:
        self.git_calls += 1
        return COMMIT

    def evidence_path(self, relative: str) -> Path:
        path = (self.project_root / relative).resolve()
        path.relative_to(self.project_root.resolve())
        return path


class Reader:
    instances: ClassVar[list[Reader]] = []

    def __init__(self, service: Service):
        self.service = service
        self.closed = False
        self.calls: list[tuple[str, str]] = []
        self.instances.append(self)

    def head(self) -> str:
        self.calls.append(("head", ""))
        return COMMIT

    def commit_is_ancestor(self, commit: str) -> bool:
        self.calls.append(("ancestor", commit))
        return True

    def blob_bytes(self, commit: str, relative: str) -> bytes:
        self.calls.append((commit, relative))
        return b"payload"

    def close(self) -> None:
        self.closed = True


def with_reader(check: Callable[[], bool]) -> bool:
    original = evidence.GitBatchObjectReader
    Reader.instances = []
    evidence.GitBatchObjectReader = Reader  # type: ignore[assignment]
    try:
        return check()
    finally:
        evidence.GitBatchObjectReader = original


def case_outside_scope_preserves_legacy(root: Path) -> bool:
    service = Service(root)
    return (
        evidence._reader_for(service) is None
        and evidence.head(service) == COMMIT
        and service.git_calls == 1
    )


def case_scope_routes_helpers(root: Path) -> bool:
    service = Service(root)

    def check() -> bool:
        with evidence.deep_batch_reader(service) as reader:
            valid = (
                evidence.head(service) == COMMIT
                and evidence.commit_is_ancestor(service, COMMIT)
                and evidence.git_blob_bytes(service, COMMIT, "proof") == b"payload"
            )
        return (
            valid
            and service.git_calls == 0
            and reader.closed
            and len(Reader.instances) == 1
        )

    return with_reader(check)


def case_exception_closes_and_resets(root: Path) -> bool:
    service = Service(root)

    def check() -> bool:
        try:
            with evidence.deep_batch_reader(service) as reader:
                raise RuntimeError("bounded fixture")
        except RuntimeError:
            return reader.closed and evidence._reader_for(service) is None
        return False

    return with_reader(check)


def case_service_identity_isolated(root: Path) -> bool:
    first, second = Service(root), Service(root)

    def check() -> bool:
        with evidence.deep_batch_reader(first):
            return (
                evidence._reader_for(first) is not None
                and evidence._reader_for(second) is None
                and evidence.head(second) == COMMIT
                and second.git_calls == 1
            )

    return with_reader(check)


def case_sequential_runs_do_not_reuse(root: Path) -> bool:
    service = Service(root)

    def check() -> bool:
        with evidence.deep_batch_reader(service) as first:
            pass
        with evidence.deep_batch_reader(service) as second:
            pass
        return (
            first is not second
            and first.closed
            and second.closed
            and len(Reader.instances) == 2
        )

    return with_reader(check)


def case_handoff_enters_batch_scope(root: Path) -> bool:
    service, observed = Service(root), []
    original = handoff_validation._validate_handoffs

    def traversal(received: Service) -> dict[str, Any]:
        observed.append(evidence._reader_for(received))
        return {"ok": True}

    def check() -> bool:
        handoff_validation._validate_handoffs = traversal
        try:
            result = handoff_validation.validate_handoffs(service)
            return (
                result == {"ok": True}
                and observed == Reader.instances
                and Reader.instances[0].closed
                and evidence._reader_for(service) is None
            )
        finally:
            handoff_validation._validate_handoffs = original

    return with_reader(check)


def case_nested_scope_restores_outer(root: Path) -> bool:
    service = Service(root)

    def check() -> bool:
        with evidence.deep_batch_reader(service) as outer:
            with evidence.deep_batch_reader(service) as inner:
                valid = evidence._reader_for(service) is inner
            return valid and inner.closed and evidence._reader_for(service) is outer

    return with_reader(check)


def case_deep_subprocess_ceiling(root: Path) -> bool:
    service = Service(root)
    original = handoff_validation._validate_handoffs

    def traversal(received: Service) -> dict[str, Any]:
        for index in range(40):
            assert evidence.head(received) == COMMIT
            assert evidence.commit_is_ancestor(received, COMMIT)
            assert (
                evidence.git_blob_bytes(received, COMMIT, f"proof-{index}")
                == b"payload"
            )
        return {"ok": True}

    def check() -> bool:
        handoff_validation._validate_handoffs = traversal
        try:
            return (
                handoff_validation.validate_handoffs(service) == {"ok": True}
                and len(Reader.instances) == 1
                and service.git_calls == 0
            )
        finally:
            handoff_validation._validate_handoffs = original

    return with_reader(check)


CASES = [
    ("legacy-outside-scope", case_outside_scope_preserves_legacy),
    ("scope-routes-helpers", case_scope_routes_helpers),
    ("exception-close-reset", case_exception_closes_and_resets),
    ("service-identity", case_service_identity_isolated),
    ("reader-per-run", case_sequential_runs_do_not_reuse),
    ("handoff-scope", case_handoff_enters_batch_scope),
    ("nested-restore", case_nested_scope_restores_outer),
    ("deep-subprocess-ceiling", case_deep_subprocess_ceiling),
]


def main() -> None:
    results = []
    for name, check in CASES:
        try:
            passed, error = bool(check(ROOT)), None
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
