"""Release-tree inventory, manifest validation, and provenance contracts."""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Any

from agent_os_paths import portable_relative
from lifecycle.shared import (
    FORBIDDEN_UPDATE_SCOPES,
    FULL_COMMIT,
    FULL_SHA256,
    git_output,
    load_json,
    sha256_bytes,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.parent


# fmt: off
def ownership_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = load_json(root / "core" / "contracts" / "ownership-policy.json", {})
    if not isinstance(policy, dict):
        return {}
    return policy


def matches_scope(relative: str, scope: str) -> bool:
    if scope.endswith("/**"):
        prefix = scope[:-3].rstrip("/")
        return relative == prefix or relative.startswith(prefix + "/")
    return fnmatch.fnmatch(relative, scope)


def classify(relative: str, policy: dict[str, Any]) -> str:
    if relative == policy.get("manifest_self"):
        return "manifest"
    for scope in policy.get("application_owned_scopes", []):
        if matches_scope(relative, scope):
            return "application"
    for scope in policy.get("runtime_scopes", []):
        if matches_scope(relative, scope):
            return "runtime"
    top = relative.split("/", 1)[0]
    if top in set(policy.get("release_owned_roots", [])):
        return "release"
    return "unclassified"


def symlink_within_release(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
        return resolved == root.resolve() or root.resolve() in resolved.parents
    except OSError:
        return False


def collect_release_entries(root: Path = ROOT) -> tuple[dict[str, dict[str, Any]], list[str]]:
    policy = ownership_policy(root)
    entries: dict[str, dict[str, Any]] = {}
    unclassified: list[str] = []
    if not policy:
        return entries, ["OWNERSHIP_POLICY_UNREADABLE"]

    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        owner = classify(relative, policy)
        if owner == "unclassified" and (path.is_file() or path.is_symlink()):
            unclassified.append(relative)
            continue
        if owner != "release":
            continue
        if path.is_symlink():
            target = os.readlink(path)
            entries[relative] = {
                "path": relative,
                "type": "symlink",
                "sha256": sha256_bytes(target.encode("utf-8")),
                "target": target,
                "target_within_release": symlink_within_release(path, root),
            }
        elif path.is_file():
            entries[relative] = {
                "path": relative,
                "type": "file",
                "sha256": sha256_file(path),
            }
    return entries, sorted(unclassified)


def collect_release_entries_at_commit(
    commit: str,
    root: Path = ROOT,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read release-owned bytes from an exact Git commit without checking it out."""
    policy = ownership_policy(root)
    if not policy:
        raise ValueError("OWNERSHIP_POLICY_UNREADABLE")
    try:
        root_prefix = root.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        tree_process = subprocess.run(
            ["git", "ls-tree", "-rz", "--full-tree", commit, "--", root_prefix],
            cwd=PROJECT_ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError("SOURCE_COMMIT_TREE_UNAVAILABLE") from exc
    if tree_process.returncode != 0:
        raise ValueError("SOURCE_COMMIT_TREE_UNAVAILABLE")

    entries: dict[str, dict[str, Any]] = {}
    unclassified: list[str] = []
    blob_candidates: list[tuple[str, str, str]] = []
    tree_prefix = root_prefix.rstrip("/") + "/"
    try:
        for record in tree_process.stdout.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
            if not path.startswith(tree_prefix):
                continue
            relative = path[len(tree_prefix) :]
            owner = classify(relative, policy)
            if owner == "unclassified":
                unclassified.append(relative)
                continue
            if owner != "release":
                continue
            if object_type != "blob" or not (mode.startswith("100") or mode == "120000"):
                raise ValueError("SOURCE_COMMIT_ENTRY_UNSUPPORTED")
            blob_candidates.append((relative, mode, object_id))
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("SOURCE_COMMIT_"):
            raise
        raise ValueError("SOURCE_COMMIT_TREE_UNREADABLE") from exc

    try:
        blob_process = subprocess.run(
            ["git", "cat-file", "--batch"],
            cwd=PROJECT_ROOT,
            input="".join(f"{object_id}\n" for _, _, object_id in blob_candidates).encode(
                "ascii"
            ),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("SOURCE_COMMIT_BLOB_UNAVAILABLE") from exc
    if blob_process.returncode != 0:
        raise ValueError("SOURCE_COMMIT_BLOB_UNAVAILABLE")

    cursor = 0
    try:
        for relative, mode, expected_object_id in blob_candidates:
            header_end = blob_process.stdout.index(b"\n", cursor)
            header = blob_process.stdout[cursor:header_end].decode("ascii").split()
            cursor = header_end + 1
            if (
                len(header) != 3
                or header[0] != expected_object_id
                or header[1] != "blob"
            ):
                raise ValueError("SOURCE_COMMIT_BLOB_UNREADABLE")
            size = int(header[2])
            content = blob_process.stdout[cursor : cursor + size]
            cursor += size
            if len(content) != size or blob_process.stdout[cursor : cursor + 1] != b"\n":
                raise ValueError("SOURCE_COMMIT_BLOB_UNREADABLE")
            cursor += 1
            if mode == "120000":
                target = content.decode("utf-8")
                entries[relative] = {
                    "path": relative,
                    "type": "symlink",
                    "sha256": sha256_bytes(content),
                    "target": target,
                }
            else:
                entries[relative] = {
                    "path": relative,
                    "type": "file",
                    "sha256": sha256_bytes(content),
                }
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("SOURCE_COMMIT_"):
            raise
        raise ValueError("SOURCE_COMMIT_BLOB_UNREADABLE") from exc
    return entries, sorted(unclassified)


def configured_remote_urls() -> list[str]:
    remote_output = git_output("remote")
    if remote_output is None:
        return []
    urls: set[str] = set()
    for remote in remote_output.splitlines():
        name = remote.strip()
        if not name:
            continue
        for arguments in (
            ("remote", "get-url", "--all", name),
            ("remote", "get-url", "--push", "--all", name),
        ):
            output = git_output(*arguments)
            if output:
                urls.update(line.strip() for line in output.splitlines() if line.strip())
    return sorted(urls)


def verified_release_provenance(
    source_locator: str,
    source_commit: str,
    current_entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Prove that verified-release provenance names the exact local Git snapshot."""
    reasons: list[str] = []
    repository_head = git_output("rev-parse", "--verify", "HEAD^{commit}")
    resolved_commit = git_output("rev-parse", "--verify", f"{source_commit}^{{commit}}")
    remotes = configured_remote_urls()

    if repository_head is None or FULL_COMMIT.fullmatch(repository_head) is None:
        reasons.append("REPOSITORY_HEAD_UNAVAILABLE")
    if resolved_commit is None or resolved_commit != source_commit:
        reasons.append("SOURCE_COMMIT_NOT_FOUND")
    elif repository_head is not None and source_commit != repository_head:
        reasons.append("SOURCE_COMMIT_NOT_HEAD")
    if source_locator not in remotes:
        reasons.append("SOURCE_LOCATOR_NOT_CONFIGURED_REMOTE")

    missing: list[str] = []
    extra: list[str] = []
    changed: list[str] = []
    committed_unclassified: list[str] = []
    if not reasons:
        try:
            committed_entries, committed_unclassified = collect_release_entries_at_commit(
                source_commit
            )
        except ValueError as exc:
            reasons.append(str(exc))
        else:
            missing = sorted(set(committed_entries) - set(current_entries))
            extra = sorted(set(current_entries) - set(committed_entries))
            changed = sorted(
                path
                for path in set(committed_entries) & set(current_entries)
                if committed_entries[path].get("type") != current_entries[path].get("type")
                or committed_entries[path].get("sha256") != current_entries[path].get("sha256")
                or committed_entries[path].get("target") != current_entries[path].get("target")
            )
            if committed_unclassified:
                reasons.append("SOURCE_COMMIT_UNCLASSIFIED_STABLE_PATH")
            if missing or extra or changed:
                reasons.append("RELEASE_TREE_NOT_EXACT_HEAD")

    return {
        "ok": not reasons,
        "repository_head": repository_head,
        "configured_remote_count": len(remotes),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "committed_unclassified": committed_unclassified,
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def manifest_entries(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        return {}, ["MANIFEST_ENTRIES_INVALID"]
    parsed: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            errors.append(f"MANIFEST_ENTRY_INVALID:{index}")
            continue
        path = entry.get("path")
        digest = entry.get("sha256")
        entry_type = entry.get("type")
        try:
            normalized = portable_relative(path, canonical=True)
        except (TypeError, ValueError):
            normalized = None
        if not isinstance(path, str) or normalized != path or path in parsed:
            errors.append(f"MANIFEST_ENTRY_PATH_INVALID:{index}")
            continue
        if entry_type not in {"file", "symlink"} or not isinstance(digest, str) or not FULL_SHA256.fullmatch(digest):
            errors.append(f"MANIFEST_ENTRY_METADATA_INVALID:{path}")
            continue
        parsed[path] = entry
    return parsed, errors


def verify_release_tree(root: Path) -> dict[str, Any]:
    try:
        release_root = root.expanduser().resolve(strict=True)
    except OSError:
        return {"ok": False, "reason_codes": ["SOURCE_RELEASE_MISSING"]}
    if not release_root.is_dir():
        return {"ok": False, "reason_codes": ["SOURCE_RELEASE_NOT_DIRECTORY"]}

    manifest_path = release_root / "_manifest" / "base-release-manifest.json"
    manifest = load_json(manifest_path, None)
    policy = ownership_policy(release_root)
    reasons: list[str] = []
    if not isinstance(manifest, dict):
        return {"ok": False, "reason_codes": ["SOURCE_MANIFEST_MISSING"]}
    if not policy:
        return {"ok": False, "reason_codes": ["SOURCE_OWNERSHIP_POLICY_MISSING"]}

    expected, schema_errors = manifest_entries(manifest)
    current, unclassified = collect_release_entries(release_root)
    missing = sorted(set(expected) - set(current))
    extra = sorted(set(current) - set(expected))
    changed = sorted(
        path
        for path in set(expected) & set(current)
        if expected[path].get("type") != current[path].get("type")
        or expected[path].get("sha256") != current[path].get("sha256")
        or expected[path].get("target") != current[path].get("target")
    )
    protected = sorted(
        path
        for path in expected
        if any(matches_scope(path, scope) for scope in FORBIDDEN_UPDATE_SCOPES)
    )
    unsafe_symlinks = sorted(
        path
        for path, entry in current.items()
        if entry.get("type") == "symlink" and entry.get("target_within_release") is not True
    )
    if manifest.get("schema_version") != 1 or manifest.get("hash_algorithm") != "sha256":
        reasons.append("SOURCE_MANIFEST_SCHEMA_INVALID")
    if not isinstance(manifest.get("agent_os_version"), str) or not manifest.get("agent_os_version"):
        reasons.append("SOURCE_VERSION_INVALID")
    if not isinstance(manifest.get("release_id"), str) or not manifest.get("release_id"):
        reasons.append("SOURCE_RELEASE_ID_INVALID")
    if schema_errors:
        reasons.append("SOURCE_MANIFEST_ENTRIES_INVALID")
    if unclassified:
        reasons.append("SOURCE_UNCLASSIFIED_STABLE_PATH")
    if missing or extra or changed:
        reasons.append("SOURCE_MANIFEST_MISMATCH")
    if protected:
        reasons.append("SOURCE_PROTECTED_SCOPE_DECLARED")
    if unsafe_symlinks:
        reasons.append("SOURCE_SYMLINK_OUTSIDE_RELEASE")

    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    trusted_for_apply = (
        provenance.get("status") == "verified-release"
        and isinstance(provenance.get("source_locator"), str)
        and bool(provenance.get("source_locator"))
        and isinstance(provenance.get("source_commit"), str)
        and FULL_COMMIT.fullmatch(provenance.get("source_commit")) is not None
        and provenance.get("created_from_repository_head") == provenance.get("source_commit")
    )
    if provenance.get("status") == "verified-release" and not trusted_for_apply:
        reasons.append("SOURCE_PROVENANCE_INVALID")
    return {
        "ok": not reasons,
        "root": str(release_root),
        "agent_os_version": manifest.get("agent_os_version"),
        "release_id": manifest.get("release_id"),
        "provenance_status": provenance.get("status"),
        "trusted_for_apply": trusted_for_apply,
        "entries": len(expected),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "protected": protected,
        "unsafe_symlinks": unsafe_symlinks,
        "unclassified": unclassified,
        "schema_errors": schema_errors,
        "reason_codes": list(dict.fromkeys(reasons)),
        "manifest_entries": expected,
    }
# fmt: on
