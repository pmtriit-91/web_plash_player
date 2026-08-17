"""Git evidence and repository-reference helpers for Context Memory."""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from context_memory.git_batch import GitBatchObjectReader

_ACTIVE_READER: ContextVar[tuple[Any, GitBatchObjectReader] | None] = ContextVar(
    "context_memory_active_git_reader", default=None,
)


def _engine() -> Any:
    import agent_os_context_memory as engine

    return engine


def git(service: Any, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments], cwd=service.project_root, capture_output=True,
            text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _reader_for(service: Any) -> GitBatchObjectReader | None:
    active = _ACTIVE_READER.get()
    return active[1] if active is not None and active[0] is service else None


@contextmanager
def deep_batch_reader(service: Any) -> Any:
    """Bind one reader to one deep traversal and always release its process."""
    reader = GitBatchObjectReader(service)
    token = _ACTIVE_READER.set((service, reader))
    try:
        yield reader
    finally:
        _ACTIVE_READER.reset(token)
        reader.close()


def head(service: Any) -> str | None:
    reader = _reader_for(service)
    if reader is not None:
        return reader.head()
    engine = _engine()
    value = service.git("rev-parse", "HEAD")
    return value if isinstance(value, str) and engine.FULL_COMMIT.fullmatch(value) else None


def commit_is_ancestor(service: Any, commit: str) -> bool:
    engine = _engine()
    if not engine.FULL_COMMIT.fullmatch(commit):
        return False
    reader = _reader_for(service)
    if reader is not None:
        return reader.commit_is_ancestor(commit)
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=service.project_root, capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def commit_exists(service: Any, commit: str) -> bool:
    engine = _engine()
    if not engine.FULL_COMMIT.fullmatch(commit):
        return False
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=service.project_root, capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def git_blob_bytes(service: Any, commit: str, relative: str) -> bytes | None:
    engine = _engine()
    if not engine.FULL_COMMIT.fullmatch(commit):
        return None
    reader = _reader_for(service)
    if reader is not None:
        return reader.blob_bytes(commit, relative)
    try:
        path = service.evidence_path(relative)
        canonical = path.relative_to(service.project_root).as_posix()
        result = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{canonical}"],
            cwd=service.project_root, capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return result.stdout if result.returncode == 0 else None


def git_path_is_clean(service: Any, relative: str) -> bool:
    try:
        path = service.evidence_path(relative)
        canonical = path.relative_to(service.project_root).as_posix()
        checks = (
            ["git", "diff", "--quiet", "--no-ext-diff", "--", canonical],
            ["git", "diff", "--cached", "--quiet", "--no-ext-diff", "--", canonical],
        )
        for command in checks:
            result = subprocess.run(
                command, cwd=service.project_root, capture_output=True, timeout=10, check=False,
            )
            if result.returncode != 0:
                return False
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False
    return True


def committed_evidence_ref(service: Any, relative: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    engine = _engine()
    try:
        path = service.evidence_path(relative)
        canonical = path.relative_to(service.project_root).as_posix()
    except ValueError:
        return None, [{"code": "CONTEXT_EVIDENCE_PATH_UNSAFE", "path": relative}]
    if not path.is_file() or path.is_symlink():
        return None, [{"code": "CONTEXT_EVIDENCE_MISSING", "path": canonical}]
    current_head = service.head()
    if not current_head:
        return None, [{"code": "CONTEXT_EVIDENCE_COMMIT_UNAVAILABLE", "path": canonical}]
    blob = service.git_blob_bytes(current_head, canonical)
    if blob is None:
        return None, [{"code": "CONTEXT_EVIDENCE_NOT_COMMITTED", "path": canonical, "git_commit": current_head}]
    if not service.git_path_is_clean(canonical):
        return None, [{"code": "CONTEXT_EVIDENCE_UNCOMMITTED", "path": canonical, "git_commit": current_head}]
    return {"path": canonical, "sha256": engine.sha256_bytes(blob), "git_commit": current_head}, []


def validate_git_evidence_ref(
    service: Any,
    ref: dict[str, Any],
    *,
    require_current: bool,
) -> list[dict[str, Any]]:
    engine = _engine()
    relative = str(ref.get("path", ""))
    expected = str(ref.get("sha256", ""))
    commit = ref.get("git_commit")
    try:
        path = service.evidence_path(relative)
        canonical = path.relative_to(service.project_root).as_posix()
    except ValueError:
        return [{"code": "CONTEXT_EVIDENCE_PATH_UNSAFE", "path": relative}]
    if not engine.SHA256.fullmatch(expected):
        return [{"code": "CONTEXT_EVIDENCE_HASH_INVALID", "path": canonical}]
    if not isinstance(commit, str) or not engine.FULL_COMMIT.fullmatch(commit):
        return [{"code": "CONTEXT_EVIDENCE_COMMIT_REQUIRED", "path": canonical}]
    if not service.commit_exists(commit):
        return [{"code": "CONTEXT_EVIDENCE_COMMIT_MISSING", "path": canonical, "git_commit": commit}]
    if not service.commit_is_ancestor(commit):
        return [{"code": "CONTEXT_EVIDENCE_COMMIT_UNREACHABLE", "path": canonical, "git_commit": commit}]
    blob = service.git_blob_bytes(commit, canonical)
    if blob is None:
        return [{"code": "CONTEXT_EVIDENCE_PATH_NOT_IN_COMMIT", "path": canonical, "git_commit": commit}]
    actual = engine.sha256_bytes(blob)
    if actual != expected:
        return [{
            "code": "CONTEXT_EVIDENCE_GIT_HASH_MISMATCH",
            "path": canonical,
            "git_commit": commit,
            "expected": expected,
            "actual": actual,
        }]
    if not require_current:
        return []
    current_head = service.head()
    head_blob = service.git_blob_bytes(current_head, canonical) if current_head else None
    if head_blob is None or not path.is_file() or path.is_symlink():
        return [{"code": "CONTEXT_EVIDENCE_MISSING", "path": canonical}]
    if not service.git_path_is_clean(canonical):
        return [{"code": "CONTEXT_EVIDENCE_UNCOMMITTED", "path": canonical, "git_commit": current_head}]
    current = engine.sha256_bytes(head_blob)
    if current != expected:
        return [{
            "code": "CONTEXT_EVIDENCE_STALE",
            "path": canonical,
            "git_commit": commit,
            "expected": expected,
            "actual": current,
        }]
    return []


def find_reachable_evidence_commit(
    service: Any,
    relative: str,
    expected_sha256: str,
    preferred_commit: str | None = None,
) -> str | None:
    engine = _engine()
    try:
        path = service.evidence_path(relative)
        canonical = path.relative_to(service.project_root).as_posix()
    except ValueError:
        return None
    current_head = service.head()
    if not current_head or not engine.SHA256.fullmatch(expected_sha256):
        return None
    cache_key = (canonical, expected_sha256, current_head)
    if cache_key in service._legacy_evidence_cache:
        return service._legacy_evidence_cache[cache_key]
    candidates: list[str] = []
    if (
        isinstance(preferred_commit, str)
        and engine.FULL_COMMIT.fullmatch(preferred_commit)
        and service.commit_is_ancestor(preferred_commit)
    ):
        candidates.append(preferred_commit)
    history = service.git("log", "--format=%H", "HEAD", "--", canonical) or ""
    candidates.extend(commit for commit in history.splitlines() if commit not in candidates)
    for commit in candidates:
        blob = service.git_blob_bytes(commit, canonical)
        if blob is not None and engine.sha256_bytes(blob) == expected_sha256:
            service._legacy_evidence_cache[cache_key] = commit
            return commit
    service._legacy_evidence_cache[cache_key] = None
    return None


def normalize_remote(value: str) -> str:
    normalized = value.strip().lower().removesuffix(".git")
    if normalized.startswith("git@github.com:"):
        return normalized.split(":", 1)[1]
    if "github.com/" in normalized:
        return normalized.split("github.com/", 1)[1]
    return normalized


def current_remote_aliases(service: Any) -> set[str]:
    aliases = {
        service.normalize_remote(str(item))
        for item in service.binding().get("repository", {}).get("remote_aliases", [])
        if isinstance(item, str) and item
    }
    remotes = service.git("remote", "-v") or ""
    for line in remotes.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            aliases.add(service.normalize_remote(parts[1]))
    return aliases
