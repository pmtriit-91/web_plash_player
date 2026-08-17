#!/usr/bin/env python3
"""Regression tests for the read-only publication readiness audit."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

audit = importlib.import_module("agent_os_publication").audit


PIN = "a" * 40


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ready_fixture(root: Path) -> None:
    write(root / "LICENSE", "Fixture license\n")
    write(root / "SECURITY.md", "Fixture security policy\n")
    write(root / ".agents" / "THIRD_PARTY_NOTICES.md", "# Third-party notices\n")
    write(
        root / ".agents" / "vendor" / "vendor-lock.json",
        json.dumps({"schema_version": 1, "packages": [], "research_sources": []}),
    )
    write(
        root / ".agents" / "project-template" / "client-bridges.json",
        json.dumps(
            {
                "schema_version": 1,
                "primary_client": "codex",
                "bridges": [
                    {
                        "id": "codex",
                        "discovery": "verified-by-fresh-session",
                    }
                ],
            }
        ),
    )
    write(
        root / ".github" / "workflows" / "ci.yml",
        f"steps:\n  - uses: actions/checkout@{PIN}\n",
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    actual = audit(project_root)
    results = [
        {
            "id": "canonical-private-beta-remains-publication-blocked",
            "passed": (
                actual.get("ok") is True
                and actual.get("state") == "BLOCKED"
                and actual.get("blockers") == ["PROJECT_LICENSE_MISSING"]
                and actual.get("network_contacted") is False
                and actual.get("state_changed") is False
            ),
        }
    ]
    with tempfile.TemporaryDirectory(prefix="agent-os-publication-") as temporary:
        root = Path(temporary)
        ready_fixture(root)
        pending = audit(root)
        results.append(
            {
                "id": "engineering-ready-still-requires-manual-publication-gates",
                "passed": (
                    pending.get("engineering_ready") is True
                    and pending.get("publication_ready") is False
                    and pending.get("state") == "PENDING_MANUAL_APPROVAL"
                    and "OWNER_PUBLICATION_APPROVAL_REQUIRED" in pending.get("manual_gates", [])
                ),
            }
        )
        write(root / ".github" / "workflows" / "ci.yml", "steps:\n  - uses: actions/checkout@v5\n")
        mutable = audit(root)
        results.append(
            {
                "id": "mutable-workflow-action-ref-is-blocked",
                "passed": "WORKFLOW_ACTION_REF_MUTABLE" in mutable.get("blockers", []),
            }
        )
        write(root / ".github" / "workflows" / "ci.yml", f"steps:\n  - uses: actions/checkout@{PIN}\n")
        write(root / "credential.txt", "github_pat_" + "A" * 40 + "\n")
        secret = audit(root)
        secret_check = next(
            (item for item in secret.get("checks", []) if item.get("id") == "tracked-secret-signatures"),
            {},
        )
        results.append(
            {
                "id": "secret-audit-reports-path-and-rule-not-value",
                "passed": (
                    "TRACKED_SECRET_SIGNATURE_DETECTED" in secret.get("blockers", [])
                    and secret_check.get("evidence", {}).get("values_reported") is False
                    and secret_check.get("evidence", {}).get("findings")
                    == [{"path": "credential.txt", "rule": "GITHUB_PAT"}]
                ),
            }
        )
    passed = sum(1 for item in results if item["passed"])
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
