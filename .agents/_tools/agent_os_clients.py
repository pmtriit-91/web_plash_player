#!/usr/bin/env python3
"""Render and inspect client bridges from one machine-readable registry."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from agent_os_paths import safe_join


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "project-template" / "client-bridges.json"
README = ROOT / "project-template" / "clients" / "README.md"
ALLOWED_STATUS = {"reference-client", "thin-shim"}
ALLOWED_DISCOVERY = {"verified-by-fresh-session", "client-dependent", "evidence-required"}


def load_registry() -> dict[str, Any]:
    try:
        value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def validate(value: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = value or load_registry()
    errors: list[dict[str, Any]] = []
    bridges = registry.get("bridges") if isinstance(registry.get("bridges"), list) else []
    seen_ids: set[str] = set()
    by_root: dict[str, str] = {}
    required = {"id", "label", "status", "root_file", "template", "discovery", "role"}
    for index, bridge in enumerate(bridges):
        if not isinstance(bridge, dict) or set(bridge) != required:
            errors.append({"code": "CLIENT_BRIDGE_FIELDS_INVALID", "index": index})
            continue
        identifier = str(bridge["id"])
        if identifier in seen_ids:
            errors.append({"code": "CLIENT_BRIDGE_ID_DUPLICATED", "id": identifier})
        seen_ids.add(identifier)
        if bridge["status"] not in ALLOWED_STATUS or bridge["discovery"] not in ALLOWED_DISCOVERY:
            errors.append({"code": "CLIENT_BRIDGE_POLICY_INVALID", "id": identifier})
        try:
            template = safe_join(ROOT, str(bridge["template"]), canonical=True)
            root_file = str(bridge["root_file"])
            safe_join(ROOT.parent, root_file, canonical=True)
        except ValueError as exc:
            errors.append({"code": "CLIENT_BRIDGE_PATH_INVALID", "id": identifier, "error": str(exc)})
            continue
        if not template.is_file() or template.is_symlink():
            errors.append({"code": "CLIENT_BRIDGE_TEMPLATE_MISSING", "id": identifier})
            continue
        digest = template.read_bytes().hex()
        if root_file in by_root and by_root[root_file] != digest:
            errors.append({"code": "CLIENT_ROOT_TEMPLATE_CONFLICT", "root_file": root_file})
        by_root[root_file] = digest
        text = template.read_text(encoding="utf-8")
        if root_file != "AGENTS.md" and ("AGENTS.md" not in text or ".agents/AGENTS.md" not in text):
            errors.append({"code": "CLIENT_SHIM_NOT_THIN", "id": identifier})
    if registry.get("schema_version") != 1 or registry.get("primary_client") not in seen_ids:
        errors.append({"code": "CLIENT_BRIDGE_REGISTRY_INVALID"})
    return {"ok": not errors, "bridges": len(bridges), "errors": errors}


def render_readme(registry: dict[str, Any]) -> str:
    lines = [
        "# Generated client bridge catalog",
        "",
        "Generated from `project-template/client-bridges.json`. Do not maintain a",
        "second client-support table by hand.",
        "",
        "| Client | Status | Root file | Discovery evidence | Role |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in registry.get("bridges", []):
        lines.append(
            f"| {item['label']} | `{item['status']}` | `{item['root_file']}` | "
            f"`{item['discovery']}` | {item['role']} |"
        )
    lines.extend([
        "",
        "Codex is the reference client. Other files are deliberately thin redirects;",
        "their presence is not proof that a particular client version auto-discovers them.",
        "",
    ])
    return "\n".join(lines)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Universal Agent OS client bridge registry")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    commands.add_parser("validate")
    render = commands.add_parser("render-readme")
    render.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    registry = load_registry()
    result = validate(registry)
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    if args.command == "list":
        output = {"ok": True, "primary_client": registry["primary_client"], "bridges": registry["bridges"]}
    elif args.command == "validate":
        output = result
    elif not args.confirm:
        output = {"ok": False, "reason_codes": ["WRITE_CONFIRMATION_REQUIRED"]}
    else:
        atomic_text(README, render_readme(registry))
        output = {"ok": True, "output": "project-template/clients/README.md", "generated_from": "project-template/client-bridges.json"}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output.get("ok") else 2)


if __name__ == "__main__":
    main()
