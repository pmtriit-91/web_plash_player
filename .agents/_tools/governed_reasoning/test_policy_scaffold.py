#!/usr/bin/env python3
"""Focused acceptance for the release-owned governed-reasoning policy scaffold."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
AGENT_ROOT = PACKAGE.parents[1]
sys.path.insert(0, str(PACKAGE.parent))

from governed_reasoning.authority import inspect_authority  # noqa: E402
from governed_reasoning.contracts import validate_artifact  # noqa: E402

TEMPLATE = AGENT_ROOT / "project-template/reasoning/policy.json"
MANIFEST = AGENT_ROOT / "_manifest/base-release-manifest.json"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def main() -> None:
    policy = load_json(TEMPLATE)
    manifest = load_json(MANIFEST)
    snapshot = inspect_authority(AGENT_ROOT)
    entries = {
        item.get("path"): item
        for item in manifest.get("entries", [])
        if isinstance(item, dict)
    } if isinstance(manifest, dict) else {}
    template_entry = entries.get("project-template/reasoning/policy.json", {})
    cases: list[dict[str, Any]] = []
    check = lambda identifier, passed: cases.append(
        {"id": identifier, "passed": bool(passed)}
    )

    check("template-is-regular-non-symlink-json", TEMPLATE.is_file() and not TEMPLATE.is_symlink() and isinstance(policy, dict))
    check("template-policy-schema-and-self-hash-valid", isinstance(policy, dict) and validate_artifact("policy", policy) == [])
    check("template-is-unbound-not-current-project-authority", isinstance(policy, dict) and policy.get("project_id") == "unbound-consumer" and policy.get("project_id") != snapshot.get("project_id"))
    check("template-is-restrict-only-and-fail-closed", isinstance(policy, dict) and policy.get("overlay_mode") == "restrict-only" and policy.get("fail_closed") is True and all(policy.get("authority", {}).values()))
    check("template-cannot-let-scores-override-authority", isinstance(policy, dict) and policy.get("authority", {}).get("scores_cannot_override") is True and policy.get("risk", {}).get("unknown_reversibility") == "escalate" and policy.get("risk", {}).get("irreversible_without_approval") == "block")
    check("release-manifest-binds-exact-template-bytes", TEMPLATE.is_file() and template_entry.get("sha256") == hashlib.sha256(TEMPLATE.read_bytes()).hexdigest())

    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
