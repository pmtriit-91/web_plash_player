#!/usr/bin/env python3
"""Portable path validation shared by Agent OS release and transaction tools."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath

WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:($|[/\\])")
WINDOWS_INVALID_COMPONENT_CHARACTERS = frozenset('<>:"|?*')
WINDOWS_RESERVED_COMPONENT_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{suffix}" for suffix in (*range(1, 10), "¹", "²", "³")),
        *(f"LPT{suffix}" for suffix in (*range(1, 10), "¹", "²", "³")),
    }
)


def _validate_windows_component(component: str, value: str) -> None:
    if any(
        ord(character) < 32
        or character in WINDOWS_INVALID_COMPONENT_CHARACTERS
        for character in component
    ):
        raise ValueError(f"path contains a Windows-invalid character: {value}")
    if component.startswith(" ") or component.endswith((".", " ")):
        raise ValueError(f"path component has unsafe boundary space or period: {value}")
    device_name = component.split(".", 1)[0].rstrip(" ").upper()
    if device_name in WINDOWS_RESERVED_COMPONENT_NAMES:
        raise ValueError(f"path contains a Windows-reserved name: {value}")


def portable_relative(value: str, *, canonical: bool = False) -> str:
    """Return a normalized repository-relative path or reject it on every OS."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("path is empty or contains NUL")
    if value.startswith(("/", "\\", "~")) or WINDOWS_DRIVE.match(value):
        raise ValueError(f"absolute or home-relative path is forbidden: {value}")
    normalized = value.replace("\\", "/")
    if canonical and normalized != value:
        raise ValueError(f"path must use canonical forward slashes: {value}")
    raw_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"unsafe relative path: {value}")
    for part in raw_parts:
        _validate_windows_component(part, value)
    candidate = PurePosixPath(normalized)
    if not candidate.parts:
        raise ValueError(f"unsafe relative path: {value}")
    return candidate.as_posix()


def portable_collision_key(value: str, *, canonical: bool = False) -> str:
    """Return a host-independent key for conservative portable-path admission."""
    relative = portable_relative(value, canonical=canonical)
    return "/".join(
        unicodedata.normalize("NFC", component).casefold()
        for component in PurePosixPath(relative).parts
    )


def safe_join(root: Path, value: str, *, canonical: bool = False) -> Path:
    """Join a portable relative path while defending against symlink-parent escape."""
    relative = portable_relative(value, canonical=canonical)
    resolved_root = root.resolve()
    destination = root.joinpath(*PurePosixPath(relative).parts)
    resolved_parent = destination.parent.resolve()
    if resolved_parent != resolved_root and resolved_root not in resolved_parent.parents:
        raise ValueError(f"path escapes root: {value}")
    return destination
