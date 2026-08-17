#!/usr/bin/env python3
"""Package only manifest-owned Agent OS bytes and the thin root bridge."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from agent_os_clients import load_registry, validate as validate_clients
from agent_os_lifecycle import verify_core
from agent_os_paths import safe_join

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "_manifest" / "base-release-manifest.json"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def safe_path(root: Path, relative: str) -> Path:
    return safe_join(root, relative, canonical=True)


def copy_entry(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise ValueError(f"release entry is missing: {source}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Universal Agent OS release bytes")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--client", action="append", default=[], help="Add a governed optional client shim by registry ID")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}, indent=2))
        raise SystemExit(2)

    verification = verify_core()
    if not verification.get("ok"):
        print(
            json.dumps(
                {"ok": False, "reason_codes": ["CORE_VERIFICATION_FAILED"], "verification": verification},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2)

    destination = Path(args.destination).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        print(json.dumps({"ok": False, "reason_codes": ["DESTINATION_NOT_EMPTY"]}, indent=2))
        raise SystemExit(2)
    destination.mkdir(parents=True, exist_ok=True)

    manifest = load_json(MANIFEST)
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        print(json.dumps({"ok": False, "reason_codes": ["MANIFEST_INVALID"]}, indent=2))
        raise SystemExit(2)

    client_registry = load_registry()
    client_validation = validate_clients(client_registry)
    if not client_validation.get("ok"):
        print(json.dumps({"ok": False, "reason_codes": ["CLIENT_BRIDGE_REGISTRY_INVALID"], "validation": client_validation}, indent=2))
        raise SystemExit(2)
    by_id = {item["id"]: item for item in client_registry["bridges"]}
    requested = ["codex", *args.client]
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        print(json.dumps({"ok": False, "reason_codes": ["CLIENT_BRIDGE_UNKNOWN"], "clients": unknown}, indent=2))
        raise SystemExit(2)

    release_root = destination / ".agents"
    copied = 0
    try:
        for entry in entries:
            relative = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(relative, str):
                raise ValueError("manifest entry path is invalid")
            copy_entry(safe_path(ROOT, relative), safe_path(release_root, relative))
            copied += 1
        copy_entry(MANIFEST, release_root / "_manifest" / "base-release-manifest.json")
        installed: dict[str, str] = {}
        for identifier in requested:
            bridge = by_id[identifier]
            root_file = bridge["root_file"]
            template = safe_path(ROOT, bridge["template"])
            target = safe_path(destination, root_file)
            if root_file not in installed:
                copy_entry(template, target)
                installed[root_file] = identifier
            elif target.read_bytes() != template.read_bytes():
                raise ValueError(f"client bridge root conflict: {root_file}")
    except Exception as exc:
        print(json.dumps({"ok": False, "reason_codes": ["PACKAGE_FAILED"], "error": str(exc)}, indent=2))
        raise SystemExit(2)

    output = {
        "ok": True,
        "destination": str(destination),
        "release_id": manifest.get("release_id"),
        "manifest_entries": len(entries),
        "copied_entries": copied,
        "root_bridge": "AGENTS.md",
        "client_bridges": sorted(installed),
        "requested_clients": sorted(set(requested)),
        "application_scopes_included": False,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
