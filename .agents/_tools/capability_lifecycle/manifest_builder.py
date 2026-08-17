"""Release overlay and working-manifest construction contracts."""

from __future__ import annotations

import json
import os
from typing import Any

from capability_lifecycle.shared import (
    MANIFEST,
    REGISTRY,
    VENDOR_LOCK,
    json_bytes,
    sha256_bytes,
)


# fmt: off
class ManifestBuilderMixin:
    def release_entries_with_overlay(self, desired: dict[str, bytes | None]) -> tuple[list[dict[str, Any]], list[str]]:
        entries: dict[str, dict[str, Any]] = {}
        unclassified: list[str] = []
        overlay = set(desired)
        for path in sorted(self.root.rglob("*"), key=lambda item: item.as_posix()):
            if not (path.is_file() or path.is_symlink()):
                continue
            relative = path.relative_to(self.root).as_posix()
            if relative in overlay:
                continue
            owner = self.owner(relative)
            if owner == "unclassified":
                unclassified.append(relative)
                continue
            if owner != "release":
                continue
            if path.is_symlink():
                target = os.readlink(path)
                resolved = path.resolve(strict=False)
                within = resolved == self.root or self.root in resolved.parents
                entries[relative] = {
                    "path": relative,
                    "type": "symlink",
                    "sha256": sha256_bytes(target.encode("utf-8")),
                    "target": target,
                    "target_within_release": within,
                }
            else:
                entries[relative] = {"path": relative, "type": "file", "sha256": sha256_bytes(path.read_bytes())}
        for relative, content in desired.items():
            owner = self.owner(relative)
            if owner == "unclassified" and content is not None:
                unclassified.append(relative)
            elif owner == "release" and content is not None:
                entries[relative] = {"path": relative, "type": "file", "sha256": sha256_bytes(content)}
        return [entries[path] for path in sorted(entries)], sorted(set(unclassified))

    def render_working_manifest(self, desired: dict[str, bytes | None], created_at: str, release_key: str) -> bytes:
        entries, unclassified = self.release_entries_with_overlay(desired)
        if unclassified:
            raise ValueError(f"unclassified stable paths: {', '.join(unclassified)}")
        unsafe = [item["path"] for item in entries if item.get("type") == "symlink" and item.get("target_within_release") is not True]
        if unsafe:
            raise ValueError(f"unsafe release symlinks: {', '.join(unsafe)}")
        policy = self.ownership()
        registry = json.loads(desired.get(REGISTRY, self.read_bytes(REGISTRY) or b"{}"))
        source_locator = self.git("remote", "get-url", "origin")
        manifest = {
            "schema_version": 1,
            "agent_os_version": registry.get("version"),
            "release_id": f"aos10-working-{release_key[:16]}",
            "created_at": created_at,
            "hash_algorithm": "sha256",
            "provenance": {
                "status": "working-baseline",
                "source_locator": source_locator,
                "source_commit": None,
                "created_from_repository_head": self.git("rev-parse", "HEAD"),
            },
            "excluded_scopes": [*policy.get("application_owned_scopes", []), *policy.get("runtime_scopes", [])],
            "vendor_lock": VENDOR_LOCK,
            "entries": entries,
        }
        return json_bytes(manifest)

    def verify_working_manifest(self) -> bool:
        manifest = self.document(MANIFEST, {})
        current_entries, unclassified = self.release_entries_with_overlay({})
        expected = manifest.get("entries") if isinstance(manifest, dict) else None
        return (
            isinstance(expected, list)
            and expected == current_entries
            and not unclassified
            and manifest.get("provenance", {}).get("status") == "working-baseline"
            and manifest.get("provenance", {}).get("source_commit") is None
        )
# fmt: on
