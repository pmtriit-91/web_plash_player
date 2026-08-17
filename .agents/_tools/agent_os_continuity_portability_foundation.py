#!/usr/bin/env python3
"""Shared portability primitives behind the canonical W5 facade.

This internal module owns bounded regular-file IO, lexical path checks, shared
artifact identifiers, and the constants needed by the portability foundation.
It does not expose a CLI or create a second service authority.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_context_memory import canonical_hash, sha256_bytes
from agent_os_paths import portable_relative, safe_join

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ABSOLUTE_MAX_FILE_BYTES = 67108864
NO_EXPECTED_CONTENT = object()
RESTORE_BACKUP_DIR_AGENT_REL = "project/context/continuity-restore-backups"
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_regular(path: Path) -> bytes | None:
    content, _error = read_regular_bounded(path, ABSOLUTE_MAX_FILE_BYTES)
    return content


def stat_is_link_like(details: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & reparse_flag
    )


def link_like_path(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat_is_link_like(details):
        return True
    junction = getattr(path, "is_junction", None)
    if junction is not None:
        try:
            return bool(junction())
        except OSError:
            return True
    return False


def read_regular_bounded(path: Path, maximum: int) -> tuple[bytes | None, str | None]:
    if type(maximum) is not int or maximum < 0:
        return None, "PORTABILITY_FILE_BOUND_EXCEEDED"
    if link_like_path(path) or not path.is_file():
        return None, "PORTABILITY_FILE_NOT_REGULAR"
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                return None, "PORTABILITY_FILE_NOT_REGULAR"
            if before.st_size > maximum:
                return None, "PORTABILITY_FILE_BOUND_EXCEEDED"
            content = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
        final = path.lstat()
    except OSError:
        return None, "PORTABILITY_FILE_UNREADABLE"
    if len(content) > maximum:
        return None, "PORTABILITY_FILE_BOUND_EXCEEDED"
    if (
        not stat.S_ISREG(final.st_mode)
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or after.st_dev != final.st_dev
        or after.st_ino != final.st_ino
        or after.st_size != final.st_size
        or after.st_mtime_ns != final.st_mtime_ns
        or len(content) != after.st_size
    ):
        return None, "PORTABILITY_FILE_CHANGED_DURING_READ"
    return content, None


def lexical_absolute(path: Path, base: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return Path(os.path.abspath(os.fspath(candidate)))


def has_symlink_component(path: Path) -> bool:
    absolute = lexical_absolute(path, Path.cwd())
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if link_like_path(current):
            return True
    return False


def scan_tree_bounded(
    root: Path,
    maximum_entries: int,
) -> tuple[list[Path], int, str | None, Path | None]:
    """Traverse without allowing one directory or deep tree to bypass a visit bound."""
    files: list[Path] = []
    pending = [root]
    visited = 0
    while pending:
        current = pending.pop()
        directories: list[Path] = []
        try:
            with os.scandir(current) as iterator:
                for item in iterator:
                    visited += 1
                    path = Path(item.path)
                    if visited > maximum_entries:
                        return [], visited, "bound", path
                    try:
                        item_details = item.stat(follow_symlinks=False)
                    except OSError:
                        return [], visited, "unreadable", path
                    if stat_is_link_like(item_details):
                        return [], visited, "symlink", path
                    if item.is_dir(follow_symlinks=False):
                        directories.append(path)
                    elif item.is_file(follow_symlinks=False):
                        files.append(path)
                    else:
                        return [], visited, "irregular", path
        except OSError:
            return [], visited, "unreadable", current
        pending.extend(
            reversed(sorted(directories, key=lambda candidate: candidate.as_posix()))
        )
    return files, visited, None, None


def project_relative_from_agent(relative: str) -> str:
    return f".agents/{portable_relative(relative, canonical=True)}"


def artifact_entry_id(path: str, present: bool, digest: str | None) -> str:
    basis = {"canonical_path": path, "present": present, "sha256": digest}
    return f"continuity-entry-{canonical_hash(basis)[:24]}"


def artifact_id(document: dict[str, Any], prefix: str, field: str) -> str:
    basis = {
        key: value
        for key, value in document.items()
        if key not in {field, "content_sha256"}
    }
    return f"{prefix}{canonical_hash(basis)[:24]}"


class ContinuityPortabilityFoundation:
    """Bounded filesystem and Git primitives shared by portability domains."""

    def __init__(
        self,
        agent_root: Path = DEFAULT_ROOT,
        now: Callable[[], datetime] = now_utc,
    ):
        self.root = agent_root.resolve()
        self.project_root = self.root.parent
        self.runtime = self.root / "_runtime" / "continuity-portability"
        self.plans = self.runtime / "plans"
        self.staging = self.runtime / "staging"
        self.backups = self.root.joinpath(
            *RESTORE_BACKUP_DIR_AGENT_REL.split("/")
        )
        self.portability_lock = self.runtime / "apply.lock"
        self.context_lock = self.root / "_runtime" / "context-memory" / "apply.lock"
        self.continuity_lock = self.root / "_runtime" / "continuity" / "apply.lock"
        self.now = now

    def agent_path(self, relative: str) -> Path:
        return safe_join(self.root, relative, canonical=True)

    def project_path(self, relative: str) -> Path:
        return safe_join(self.project_root, relative, canonical=True)

    @staticmethod
    def _stat_is_link_like(details: os.stat_result) -> bool:
        """Treat every symlink, junction, or Windows reparse point as unsafe."""
        return stat_is_link_like(details)

    def path_is_link_like(self, path: Path) -> bool:
        """Fail closed for link-like objects across POSIX and Windows."""
        return link_like_path(path)

    @staticmethod
    def _same_entry(left: os.stat_result, right: os.stat_result) -> bool:
        return (
            left.st_dev == right.st_dev
            and left.st_ino == right.st_ino
            and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
            and getattr(left, "st_file_attributes", 0)
            == getattr(right, "st_file_attributes", 0)
        )

    def _descriptor_scope_is_current(self, descriptor: int, path: Path) -> bool:
        try:
            lexical = path.lstat()
            opened = os.fstat(descriptor)
        except OSError:
            return False
        return (
            not self._stat_is_link_like(lexical)
            and stat.S_ISDIR(lexical.st_mode)
            and self._same_entry(lexical, opened)
        )

    def _safe_directory_stat(self, path: Path) -> os.stat_result | None:
        try:
            details = path.lstat()
            if (
                self._stat_is_link_like(details)
                or not stat.S_ISDIR(details.st_mode)
                or self.path_is_link_like(path)
                or os.path.normcase(str(path.resolve(strict=True)))
                != os.path.normcase(str(path.absolute()))
            ):
                return None
            return details
        except OSError:
            return None

    @staticmethod
    def _descriptor_scoping_available() -> bool:
        return all(
            function in os.supports_dir_fd
            for function in (os.open, os.stat, os.mkdir, os.unlink, os.rename)
        ) and bool(getattr(os, "O_DIRECTORY", 0))

    def _open_scoped_directory(
        self,
        base: Path,
        relative: str,
        *,
        create: bool = False,
    ) -> tuple[int | None, Path] | None:
        """Open a directory without following a mutable pathname component.

        POSIX traversal stays bound to directory descriptors. Platforms without
        ``dir_fd`` support use identity snapshots plus reparse-point checks; every
        caller revalidates that snapshot immediately before its mutation.
        """
        try:
            canonical = (
                portable_relative(relative, canonical=True)
                if relative
                else ""
            )
        except ValueError:
            return None
        base = Path(os.path.abspath(os.fspath(base)))
        base_details = self._safe_directory_stat(base)
        if base_details is None:
            return None
        parts = tuple(Path(canonical).parts) if canonical else ()
        current = base
        if self._descriptor_scoping_available():
            flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(base, flags)
            except OSError:
                return None
            try:
                if not self._same_entry(base_details, os.fstat(descriptor)):
                    raise OSError("scoped base changed")
                for part in parts:
                    try:
                        child = os.open(part, flags, dir_fd=descriptor)
                    except FileNotFoundError:
                        if not create:
                            raise
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                        child = os.open(part, flags, dir_fd=descriptor)
                    child_details = os.fstat(child)
                    if (
                        self._stat_is_link_like(child_details)
                        or not stat.S_ISDIR(child_details.st_mode)
                    ):
                        os.close(child)
                        raise OSError("unsafe scoped directory")
                    os.close(descriptor)
                    descriptor = child
                    current = current / part
                    if not self._descriptor_scope_is_current(descriptor, current):
                        raise OSError("scoped directory changed during traversal")
                if not self._descriptor_scope_is_current(descriptor, current):
                    raise OSError("scoped directory changed before use")
                return descriptor, current
            except OSError:
                os.close(descriptor)
                return None

        for part in parts:
            parent_details = self._safe_directory_stat(current)
            if parent_details is None:
                return None
            child = current / part
            try:
                child_details = child.lstat()
            except FileNotFoundError:
                if not create:
                    return None
                try:
                    child.mkdir(mode=0o700, exist_ok=False)
                    parent_after = self._safe_directory_stat(current)
                    child_details = child.lstat()
                except OSError:
                    return None
                if (
                    parent_after is None
                    or not self._same_entry(parent_details, parent_after)
                ):
                    return None
            except OSError:
                return None
            if (
                self._stat_is_link_like(child_details)
                or self.path_is_link_like(child)
                or not stat.S_ISDIR(child_details.st_mode)
                or self._safe_directory_stat(child) is None
            ):
                return None
            current = child
        return None, current

    def _atomic_scoped_bytes(
        self,
        base: Path,
        relative: str,
        content: bytes,
        *,
        create_parents: bool = False,
        expected_before_sha256: str | None | object = NO_EXPECTED_CONTENT,
    ) -> Path:
        """Atomically replace one regular file while bound to its scoped parent."""
        canonical = portable_relative(relative, canonical=True)
        relative_path = Path(canonical)
        opened = self._open_scoped_directory(
            base,
            relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
            create=create_parents,
        )
        if opened is None:
            raise OSError("unsafe scoped parent")
        descriptor, parent = opened
        name = relative_path.name
        temporary_name = f".{name}.{secrets.token_hex(12)}.tmp"
        target = parent / name
        if descriptor is not None:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            temporary_descriptor: int | None = None
            try:
                if not self._descriptor_scope_is_current(descriptor, parent):
                    raise OSError("scoped parent changed before write")
                try:
                    existing = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    existing = None
                if existing is not None and (
                    self._stat_is_link_like(existing)
                    or not stat.S_ISREG(existing.st_mode)
                ):
                    raise OSError("scoped target is not a regular file")
                if expected_before_sha256 is not NO_EXPECTED_CONTENT:
                    if expected_before_sha256 is None:
                        if existing is not None:
                            raise OSError("scoped target changed before write")
                    else:
                        if existing is None:
                            raise OSError("scoped target changed before write")
                        source_descriptor = os.open(
                            name,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=descriptor,
                        )
                        try:
                            source_details = os.fstat(source_descriptor)
                            if (
                                not stat.S_ISREG(source_details.st_mode)
                                or source_details.st_size > ABSOLUTE_MAX_FILE_BYTES
                            ):
                                raise OSError("scoped target changed before write")
                            chunks: list[bytes] = []
                            remaining = ABSOLUTE_MAX_FILE_BYTES + 1
                            while remaining > 0:
                                chunk = os.read(
                                    source_descriptor,
                                    min(65536, remaining),
                                )
                                if not chunk:
                                    break
                                chunks.append(chunk)
                                remaining -= len(chunk)
                            source_content = b"".join(chunks)
                            source_after = os.fstat(source_descriptor)
                            if (
                                len(source_content) != source_after.st_size
                                or not self._same_entry(
                                    source_details,
                                    source_after,
                                )
                                or source_details.st_size
                                != source_after.st_size
                                or source_details.st_mtime_ns
                                != source_after.st_mtime_ns
                                or sha256_bytes(source_content)
                                != expected_before_sha256
                            ):
                                raise OSError("scoped target changed before write")
                        finally:
                            os.close(source_descriptor)
                temporary_descriptor = os.open(
                    temporary_name,
                    flags,
                    0o600,
                    dir_fd=descriptor,
                )
                view = memoryview(content)
                while view:
                    written = os.write(temporary_descriptor, view)
                    if written <= 0:
                        raise OSError("short scoped write")
                    view = view[written:]
                os.fsync(temporary_descriptor)
                temporary_details = os.fstat(temporary_descriptor)
                if (
                    not stat.S_ISREG(temporary_details.st_mode)
                    or temporary_details.st_size != len(content)
                ):
                    raise OSError("scoped temporary verification failed")
                os.close(temporary_descriptor)
                temporary_descriptor = None
                if not self._descriptor_scope_is_current(descriptor, parent):
                    raise OSError("scoped parent changed before replace")
                os.replace(
                    temporary_name,
                    name,
                    src_dir_fd=descriptor,
                    dst_dir_fd=descriptor,
                )
                os.fsync(descriptor)
                if not self._descriptor_scope_is_current(descriptor, parent):
                    raise OSError("scoped parent changed during replace")
                final = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (
                    self._stat_is_link_like(final)
                    or not stat.S_ISREG(final.st_mode)
                    or final.st_size != len(content)
                ):
                    raise OSError("scoped target verification failed")
                return target
            finally:
                if temporary_descriptor is not None:
                    os.close(temporary_descriptor)
                try:
                    os.unlink(temporary_name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
                os.close(descriptor)

        parent_before = self._safe_directory_stat(parent)
        if parent_before is None:
            raise OSError("unsafe scoped parent")
        if expected_before_sha256 is not NO_EXPECTED_CONTENT:
            before_content, _before_error = read_regular_bounded(
                target,
                ABSOLUTE_MAX_FILE_BYTES,
            )
            before_hash = (
                sha256_bytes(before_content)
                if before_content is not None
                else None
            )
            if before_hash != expected_before_sha256:
                raise OSError("scoped target changed before write")
        temporary = parent / temporary_name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        temporary_descriptor = os.open(temporary, flags, 0o600)
        try:
            parent_after_create = self._safe_directory_stat(parent)
            if (
                parent_after_create is None
                or not self._same_entry(parent_before, parent_after_create)
            ):
                raise OSError("scoped parent changed before write")
            view = memoryview(content)
            while view:
                written = os.write(temporary_descriptor, view)
                if written <= 0:
                    raise OSError("short scoped write")
                view = view[written:]
            os.fsync(temporary_descriptor)
        finally:
            os.close(temporary_descriptor)
        parent_before_replace = self._safe_directory_stat(parent)
        if (
            parent_before_replace is None
            or not self._same_entry(parent_before, parent_before_replace)
            or self.path_is_link_like(target)
            or (target.exists() and not target.is_file())
        ):
            raise OSError("scoped parent changed before replace")
        os.replace(temporary, target)
        parent_final = self._safe_directory_stat(parent)
        if (
            parent_final is None
            or not self._same_entry(parent_before, parent_final)
            or self.path_is_link_like(target)
            or not target.is_file()
        ):
            raise OSError("scoped parent changed during replace")
        return target

    def _read_scoped_regular(
        self,
        base: Path,
        relative: str,
        maximum: int,
    ) -> tuple[bytes | None, str | None]:
        if type(maximum) is not int or maximum < 0:
            return None, "PORTABILITY_FILE_BOUND_EXCEEDED"
        try:
            canonical = portable_relative(relative, canonical=True)
        except ValueError:
            return None, "PORTABILITY_FILE_NOT_REGULAR"
        relative_path = Path(canonical)
        opened = self._open_scoped_directory(
            base,
            relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
            create=False,
        )
        if opened is None:
            return None, "PORTABILITY_FILE_UNREADABLE"
        descriptor, parent = opened
        name = relative_path.name
        if descriptor is not None:
            file_descriptor: int | None = None
            try:
                if not self._descriptor_scope_is_current(descriptor, parent):
                    return None, "PORTABILITY_FILE_CHANGED_DURING_READ"
                file_descriptor = os.open(
                    name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                before = os.fstat(file_descriptor)
                if not stat.S_ISREG(before.st_mode):
                    return None, "PORTABILITY_FILE_NOT_REGULAR"
                if before.st_size > maximum:
                    return None, "PORTABILITY_FILE_BOUND_EXCEEDED"
                chunks: list[bytes] = []
                remaining = maximum + 1
                while remaining > 0:
                    chunk = os.read(file_descriptor, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b"".join(chunks)
                after = os.fstat(file_descriptor)
                if (
                    len(content) > maximum
                    or len(content) != after.st_size
                    or not self._same_entry(before, after)
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or not self._descriptor_scope_is_current(descriptor, parent)
                ):
                    return None, "PORTABILITY_FILE_CHANGED_DURING_READ"
                return content, None
            except FileNotFoundError:
                return None, "PORTABILITY_FILE_NOT_FOUND"
            except OSError:
                return None, "PORTABILITY_FILE_UNREADABLE"
            finally:
                if file_descriptor is not None:
                    os.close(file_descriptor)
                os.close(descriptor)
        parent_before = self._safe_directory_stat(parent)
        if parent_before is None:
            return None, "PORTABILITY_FILE_UNREADABLE"
        target = parent / name
        if not target.exists() and not self.path_is_link_like(target):
            return None, "PORTABILITY_FILE_NOT_FOUND"
        content, error = read_regular_bounded(target, maximum)
        parent_after = self._safe_directory_stat(parent)
        if (
            parent_after is None
            or not self._same_entry(parent_before, parent_after)
        ):
            return None, "PORTABILITY_FILE_CHANGED_DURING_READ"
        return content, error

    def _commit_scoped_bytes(
        self,
        base: Path,
        relative: str,
        content: bytes,
        *,
        create_parents: bool = False,
    ) -> Path:
        """Make the final receipt write idempotent at its durable commit point."""
        try:
            return self._atomic_scoped_bytes(
                base,
                relative,
                content,
                create_parents=create_parents,
            )
        except OSError:
            current, _error = self._read_scoped_regular(
                base,
                relative,
                len(content),
            )
            if current == content:
                canonical = portable_relative(relative, canonical=True)
                return Path(base).joinpath(*canonical.split("/"))
            raise

    def _unlink_scoped_file(
        self,
        base: Path,
        relative: str,
        *,
        expected_before_sha256: str | None | object = NO_EXPECTED_CONTENT,
    ) -> bool:
        canonical = portable_relative(relative, canonical=True)
        relative_path = Path(canonical)
        opened = self._open_scoped_directory(
            base,
            relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
            create=False,
        )
        if opened is None:
            return False
        descriptor, parent = opened
        name = relative_path.name
        if descriptor is not None:
            try:
                try:
                    details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    return expected_before_sha256 in {
                        NO_EXPECTED_CONTENT,
                        None,
                    }
                if self._stat_is_link_like(details) or not stat.S_ISREG(details.st_mode):
                    return False
                if expected_before_sha256 is not NO_EXPECTED_CONTENT:
                    if expected_before_sha256 is None:
                        return False
                    file_descriptor = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=descriptor,
                    )
                    try:
                        opened_details = os.fstat(file_descriptor)
                        if opened_details.st_size > ABSOLUTE_MAX_FILE_BYTES:
                            return False
                        chunks: list[bytes] = []
                        remaining = ABSOLUTE_MAX_FILE_BYTES + 1
                        while remaining > 0:
                            chunk = os.read(
                                file_descriptor,
                                min(65536, remaining),
                            )
                            if not chunk:
                                break
                            chunks.append(chunk)
                            remaining -= len(chunk)
                        final_details = os.fstat(file_descriptor)
                        if (
                            not self._same_entry(opened_details, final_details)
                            or opened_details.st_size != final_details.st_size
                            or opened_details.st_mtime_ns
                            != final_details.st_mtime_ns
                            or sha256_bytes(b"".join(chunks))
                            != expected_before_sha256
                        ):
                            return False
                    finally:
                        os.close(file_descriptor)
                if not self._descriptor_scope_is_current(descriptor, parent):
                    return False
                os.unlink(name, dir_fd=descriptor)
                return True
            except OSError:
                return False
            finally:
                os.close(descriptor)
        before = self._safe_directory_stat(parent)
        target = parent / name
        if before is None or self.path_is_link_like(target):
            return False
        try:
            if not target.exists():
                return expected_before_sha256 in {
                    NO_EXPECTED_CONTENT,
                    None,
                }
            if not target.is_file():
                return False
            if expected_before_sha256 is not NO_EXPECTED_CONTENT:
                if expected_before_sha256 is None:
                    return False
                current, _current_error = read_regular_bounded(
                    target,
                    ABSOLUTE_MAX_FILE_BYTES,
                )
                if (
                    current is None
                    or sha256_bytes(current) != expected_before_sha256
                ):
                    return False
            target.unlink()
        except OSError:
            return False
        after = self._safe_directory_stat(parent)
        return after is not None and self._same_entry(before, after) and not target.exists()

    def _create_scoped_directory(
        self,
        base: Path,
        relative: str,
        *,
        create_parents: bool = False,
    ) -> Path | None:
        canonical = portable_relative(relative, canonical=True)
        relative_path = Path(canonical)
        opened = self._open_scoped_directory(
            base,
            relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
            create=create_parents,
        )
        if opened is None:
            return None
        descriptor, parent = opened
        name = relative_path.name
        target = parent / name
        if descriptor is not None:
            try:
                try:
                    os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    return None
                except FileNotFoundError:
                    os.mkdir(name, 0o700, dir_fd=descriptor)
                child = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if self._stat_is_link_like(child) or not stat.S_ISDIR(child.st_mode):
                    return None
                return target
            except OSError:
                return None
            finally:
                os.close(descriptor)
        before = self._safe_directory_stat(parent)
        if before is None or target.exists() or self.path_is_link_like(target):
            return None
        try:
            target.mkdir(mode=0o700, exist_ok=False)
        except OSError:
            return None
        after = self._safe_directory_stat(parent)
        if (
            after is None
            or not self._same_entry(before, after)
            or self._safe_directory_stat(target) is None
        ):
            return None
        return target

    def _create_scoped_temp_directory(
        self,
        base: Path,
        parent_relative: str,
        *,
        prefix: str,
        suffix: str,
    ) -> Path | None:
        if any(
            not value or "/" in value or "\\" in value or "\x00" in value
            for value in (prefix, suffix)
        ):
            return None
        for _attempt in range(128):
            name = f"{prefix}{secrets.token_hex(12)}{suffix}"
            relative = f"{parent_relative}/{name}" if parent_relative else name
            created = self._create_scoped_directory(
                base,
                relative,
                create_parents=False,
            )
            if created is not None:
                return created
        return None

    def _rename_scoped_directory(
        self,
        base: Path,
        parent_relative: str,
        source_name: str,
        destination_name: str,
    ) -> bool:
        if any(
            not value or "/" in value or "\\" in value or "\x00" in value
            for value in (source_name, destination_name)
        ):
            return False
        opened = self._open_scoped_directory(
            base,
            parent_relative,
            create=False,
        )
        if opened is None:
            return False
        descriptor, parent = opened
        source = parent / source_name
        destination = parent / destination_name
        if descriptor is not None:
            try:
                try:
                    source_details = os.stat(
                        source_name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    return False
                try:
                    os.stat(
                        destination_name,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    return False
                except FileNotFoundError:
                    pass
                if (
                    self._stat_is_link_like(source_details)
                    or not stat.S_ISDIR(source_details.st_mode)
                ):
                    return False
                os.rename(
                    source_name,
                    destination_name,
                    src_dir_fd=descriptor,
                    dst_dir_fd=descriptor,
                )
                final = os.stat(
                    destination_name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
                return (
                    not self._stat_is_link_like(final)
                    and stat.S_ISDIR(final.st_mode)
                )
            except OSError:
                return False
            finally:
                os.close(descriptor)
        before = self._safe_directory_stat(parent)
        if (
            before is None
            or self._safe_directory_stat(source) is None
            or destination.exists()
            or self.path_is_link_like(destination)
        ):
            return False
        try:
            source.replace(destination)
        except OSError:
            return False
        after = self._safe_directory_stat(parent)
        return (
            after is not None
            and self._same_entry(before, after)
            and self._safe_directory_stat(destination) is not None
        )

    def _remove_scoped_tree(self, base: Path, relative: str) -> bool:
        canonical = portable_relative(relative, canonical=True)
        relative_path = Path(canonical)
        opened = self._open_scoped_directory(
            base,
            relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
            create=False,
        )
        if opened is None:
            return False
        descriptor, parent = opened
        name = relative_path.name
        target = parent / name
        if descriptor is not None:
            try:
                try:
                    details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:
                    return True
                if self._stat_is_link_like(details) or not stat.S_ISDIR(details.st_mode):
                    return False
                shutil.rmtree(name, dir_fd=descriptor)
                return True
            except OSError:
                return False
            finally:
                os.close(descriptor)
        before = self._safe_directory_stat(parent)
        if before is None:
            return False
        try:
            if not target.exists():
                return True
            if self._safe_directory_stat(target) is None:
                return False
            shutil.rmtree(target)
        except OSError:
            return False
        after = self._safe_directory_stat(parent)
        return after is not None and self._same_entry(before, after) and not target.exists()

    def _create_scoped_lock(
        self,
        relative: str,
    ) -> tuple[int, Path] | None:
        canonical = portable_relative(relative, canonical=True)
        relative_path = Path(canonical)
        opened = self._open_scoped_directory(
            self.root,
            relative_path.parent.as_posix() if relative_path.parent != Path(".") else "",
            create=True,
        )
        if opened is None:
            return None
        directory_descriptor, parent = opened
        name = relative_path.name
        path = parent / name
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        if directory_descriptor is not None:
            try:
                descriptor = os.open(
                    name,
                    flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                return descriptor, path
            finally:
                os.close(directory_descriptor)
        before = self._safe_directory_stat(parent)
        if before is None:
            return None
        descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0), 0o600)
        after = self._safe_directory_stat(parent)
        if after is None or not self._same_entry(before, after):
            os.close(descriptor)
            return None
        return descriptor, path

    def verified_owned_directory(
        self,
        relative: str,
        *,
        create: bool = False,
    ) -> Path | None:
        """Return a fixed Agent OS directory with descriptor-bound traversal."""
        opened = self._open_scoped_directory(self.root, relative, create=create)
        if opened is None:
            return None
        descriptor, expected = opened
        if descriptor is not None:
            os.close(descriptor)
        return expected

    def verified_restore_backup_root(
        self,
        *,
        create: bool = False,
    ) -> Path | None:
        """Return the backup root through the same junction-safe owned guard."""
        return self.verified_owned_directory(
            RESTORE_BACKUP_DIR_AGENT_REL,
            create=create,
        )

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def git_bytes(self, *arguments: str) -> subprocess.CompletedProcess[bytes] | None:
        try:
            return subprocess.run(
                ["git", *arguments],
                cwd=self.project_root,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def git_bytes_bounded(
        self,
        *arguments: str,
        maximum: int,
    ) -> tuple[bytes | None, str | None]:
        """Read Git stdout with a hard byte ceiling and kill-on-timeout."""
        if maximum < 0:
            return None, "PORTABILITY_SOURCE_GIT_OUTPUT_BOUND_EXCEEDED"
        try:
            process = subprocess.Popen(
                ["git", *arguments],
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return None, "PORTABILITY_SOURCE_GIT_COMMAND_UNAVAILABLE"
        timed_out = threading.Event()

        def terminate() -> None:
            timed_out.set()
            try:
                process.kill()
            except OSError:
                pass

        timer = threading.Timer(30, terminate)
        timer.daemon = True
        timer.start()
        try:
            if process.stdout is None:
                terminate()
                return None, "PORTABILITY_SOURCE_GIT_COMMAND_UNAVAILABLE"
            content = process.stdout.read(maximum + 1)
            if len(content) > maximum:
                terminate()
                process.wait()
                return (
                    None,
                    "PORTABILITY_SOURCE_GIT_OUTPUT_BOUND_EXCEEDED",
                )
            return_code = process.wait()
            timer.cancel()
            if timed_out.is_set():
                return None, "PORTABILITY_SOURCE_GIT_COMMAND_TIMEOUT"
            if return_code != 0:
                return None, "PORTABILITY_SOURCE_GIT_COMMAND_UNAVAILABLE"
            return content, None
        finally:
            timer.cancel()
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
                process.wait()

    def git_tree(self, commit: str) -> dict[str, tuple[str, str]] | None:
        if FULL_COMMIT.fullmatch(commit) is None:
            return None
        ancestry = self.git("merge-base", "--is-ancestor", commit, "HEAD")
        if ancestry is None or ancestry.returncode != 0:
            return None
        return {}

    def populate_git_tree_prefixes(
        self,
        commit: str,
        prefixes: list[str],
        tree: dict[str, tuple[str, str]],
        *,
        maximum_entries: int,
        maximum_output_bytes: int,
    ) -> str | None:
        """Populate only approved Git subtrees under hard entry/output bounds."""
        visited = 0
        output_bytes = 0
        for prefix in sorted(set(prefixes)):
            try:
                canonical = portable_relative(prefix.rstrip("/"), canonical=True)
            except ValueError:
                return "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
            if len(canonical) > 512:
                return "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
            remaining = maximum_output_bytes - output_bytes
            if remaining < 0:
                return "PORTABILITY_SOURCE_GIT_TREE_BOUND_EXCEEDED"
            content, error = self.git_bytes_bounded(
                "--literal-pathspecs",
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                commit,
                "--",
                canonical,
                maximum=remaining,
            )
            if content is None:
                return (
                    "PORTABILITY_SOURCE_GIT_TREE_BOUND_EXCEEDED"
                    if error == "PORTABILITY_SOURCE_GIT_OUTPUT_BOUND_EXCEEDED"
                    else "PORTABILITY_SOURCE_GIT_TREE_UNAVAILABLE"
                )
            output_bytes += len(content)
            for record in content.split(b"\0"):
                if not record:
                    continue
                visited += 1
                if visited > maximum_entries:
                    return "PORTABILITY_SOURCE_GIT_TREE_BOUND_EXCEEDED"
                try:
                    raw_metadata, raw_path = record.split(b"\t", 1)
                    mode, object_type, _object_id = raw_metadata.decode(
                        "ascii"
                    ).split(" ", 2)
                    path = raw_path.decode("utf-8")
                except (UnicodeDecodeError, ValueError):
                    return "PORTABILITY_SOURCE_GIT_TREE_UNAVAILABLE"
                if (
                    len(path) > 512
                    or not (
                        path == canonical
                        or path.startswith(f"{canonical}/")
                    )
                ):
                    return "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
                if path not in tree and len(tree) >= maximum_entries:
                    return "PORTABILITY_SOURCE_GIT_TREE_BOUND_EXCEEDED"
                tree[path] = (mode, object_type)
        return None

    def git_blob_at(
        self,
        commit: str,
        path: str,
        tree: dict[str, tuple[str, str]],
        maximum: int = 8388608,
    ) -> tuple[bytes | None, str | None]:
        metadata = tree.get(path)
        if metadata is None:
            if (
                not isinstance(path, str)
                or not 1 <= len(path) <= 4096
                or "\x00" in path
            ):
                return None, "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
            listing, listing_error = self.git_bytes_bounded(
                "--literal-pathspecs",
                "ls-tree",
                "-z",
                "--full-tree",
                commit,
                "--",
                path,
                maximum=len(path.encode("utf-8")) + 160,
            )
            if listing is None:
                return (
                    None,
                    (
                        "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
                        if listing_error
                        == "PORTABILITY_SOURCE_GIT_OUTPUT_BOUND_EXCEEDED"
                        else "PORTABILITY_SOURCE_GIT_BLOB_UNAVAILABLE"
                    ),
                )
            records = [record for record in listing.split(b"\0") if record]
            if not records:
                return None, None
            if len(records) != 1:
                return None, "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
            try:
                raw_metadata, raw_path = records[0].split(b"\t", 1)
                mode, object_type, _object_id = raw_metadata.decode("ascii").split(
                    " ", 2
                )
                listed_path = raw_path.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                return None, "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
            if listed_path != path:
                return None, "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
            metadata = (mode, object_type)
            tree[path] = metadata
        mode, object_type = metadata
        if object_type != "blob" or mode not in {"100644", "100755"}:
            return None, "PORTABILITY_SOURCE_GIT_PATH_UNSAFE"
        size_result = self.git("cat-file", "-s", f"{commit}:{path}")
        if (
            size_result is None
            or size_result.returncode != 0
            or not size_result.stdout.strip().isdigit()
        ):
            return None, "PORTABILITY_SOURCE_GIT_BLOB_UNAVAILABLE"
        if int(size_result.stdout.strip()) > maximum:
            return None, "PORTABILITY_SOURCE_GIT_BLOB_BOUND_EXCEEDED"
        result = self.git_bytes("cat-file", "blob", f"{commit}:{path}")
        if result is None or result.returncode != 0:
            return None, "PORTABILITY_SOURCE_GIT_BLOB_UNAVAILABLE"
        return result.stdout, None

    def head(self) -> str | None:
        result = self.git("rev-parse", "HEAD")
        value = (
            result.stdout.strip()
            if result is not None and result.returncode == 0
            else ""
        )
        return value if FULL_COMMIT.fullmatch(value) else None


__all__ = [
    "ABSOLUTE_MAX_FILE_BYTES",
    "ContinuityPortabilityFoundation",
    "DEFAULT_ROOT",
    "FULL_COMMIT",
    "NO_EXPECTED_CONTENT",
    "RESTORE_BACKUP_DIR_AGENT_REL",
    "artifact_entry_id",
    "artifact_id",
    "has_symlink_component",
    "lexical_absolute",
    "link_like_path",
    "now_utc",
    "project_relative_from_agent",
    "read_regular",
    "read_regular_bounded",
    "scan_tree_bounded",
    "stat_is_link_like",
]
