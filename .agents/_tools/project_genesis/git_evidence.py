"""Git-canonical and immutable evidence primitives for Project Genesis."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def _git(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_canonical_bytes(project_root: Path, path: Path) -> bytes | None:
    """Return the HEAD blob for a tracked path whose Git-clean content is unchanged."""
    try:
        canonical = path.relative_to(project_root).as_posix()
        if path.is_symlink() or not path.is_file():
            return None
        for arguments in (
            ("diff", "--quiet", "--no-ext-diff", "--", canonical),
            ("diff", "--cached", "--quiet", "--no-ext-diff", "--", canonical),
        ):
            result = _git(project_root, *arguments)
            if result is None or result.returncode != 0:
                return None
    except ValueError:
        return None
    result = _git(project_root, "cat-file", "blob", f"HEAD:{canonical}")
    return result.stdout if result is not None and result.returncode == 0 else None


def sha256_project_file(project_root: Path, path: Path) -> str:
    """Hash Git-canonical bytes when safe, otherwise hash the transaction bytes."""
    canonical = git_canonical_bytes(project_root, path)
    if canonical is not None:
        return hashlib.sha256(canonical).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pinned_evidence_error(
    project_root: Path,
    commit: str,
    ref: str,
    expected_sha256: str,
) -> str | None:
    """Validate an immutable evidence blob at a commit reachable from current HEAD."""
    exists = _git(project_root, "cat-file", "-e", f"{commit}^{{commit}}")
    if exists is None or exists.returncode != 0:
        return "commit missing"
    ancestor = _git(project_root, "merge-base", "--is-ancestor", commit, "HEAD")
    if ancestor is None or ancestor.returncode != 0:
        return "commit unreachable"
    tree = _git(project_root, "ls-tree", "-z", commit, "--", ref)
    entries = [] if tree is None or tree.returncode != 0 else tree.stdout.rstrip(b"\0").split(b"\0")
    exact = [entry for entry in entries if entry.partition(b"\t")[2] == ref.encode()]
    if not exact:
        return "path absent at commit"
    if exact[0].partition(b" ")[0] == b"120000":
        return "symlink at commit"
    blob = _git(project_root, "cat-file", "blob", f"{commit}:{ref}")
    if blob is None or blob.returncode != 0:
        return "path absent at commit"
    if hashlib.sha256(blob.stdout).hexdigest() != expected_sha256:
        return "Git hash drift"
    return None
