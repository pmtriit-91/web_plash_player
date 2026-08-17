#!/usr/bin/env python3
"""Activation, snapshot, path and vendor lifecycle acceptance tests."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_capability_lifecycle import VENDOR_LOCK, sha256_bytes
from capability_lifecycle.test_support import (
    FULL_COMMIT,
    assembly,
    candidate,
    fixture,
    reason,
)


def vendor_candidate() -> tuple[dict, str, str]:
    skill = "---\nname: vendor-widget\ndescription: Review vendor widget contracts with bounded instructions.\n---\n\n# Vendor Widget\n"
    license_text = "MIT License\n\nPermission is hereby granted for fixture use.\n"
    files = [
        {
            "path": "LICENSE",
            "type": "file",
            "bytes": len(license_text.encode()),
            "sha256": sha256_bytes(license_text.encode()),
        },
        {
            "path": "SKILL.md",
            "type": "file",
            "bytes": len(skill.encode()),
            "sha256": sha256_bytes(skill.encode()),
        },
    ]
    snapshot = sha256_bytes(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
    value, _ = candidate("vendor-widget")
    value["source"].update(
        {
            "repository": "https://example.invalid/vendor-widget",
            "snapshot_sha256": snapshot,
        }
    )
    value["inventory"] = {
        "file_count": 2,
        "total_bytes": len(skill.encode()) + len(license_text.encode()),
        "files": files,
    }
    value["recommendation"] = "vendor-pin"
    return value, skill, license_text


def vendor_assembly(candidate_value: dict, skill: str, license_text: str) -> dict:
    return {
        "schema_version": 1,
        "candidate_id": candidate_value["id"],
        "capability_id": "vendor-widget",
        "integration_mode": "vendor-pin",
        "files": [
            {
                "source_path": "LICENSE",
                "target": "vendor/vendor-widget/LICENSE",
                "content": license_text,
            },
            {
                "source_path": "SKILL.md",
                "target": "vendor/vendor-widget/SKILL.md",
                "content": skill,
            },
        ],
        "descriptor": {
            "version": "1.0.0",
            "summary": "Review vendor widget contracts with a pinned instruction-only workflow.",
            "when_to_use": ["A task explicitly requests a vendor widget contract review."],
            "not_for": ["Unrelated feature implementation or general architecture work."],
            "risk": {"level": "low", "notes": "Pinned instruction-only content."},
            "permissions": {
                "filesystem": "read-only",
                "shell": "none",
                "git": "none",
                "network": "none",
                "secrets": "none",
                "external_state": "none",
            },
            "dependencies": [],
            "conflicts": [],
            "token_profile": {"metadata_budget": "tiny", "activation_budget": "small"},
        },
        "route": {
            "path": "vendor/vendor-widget",
            "group": "engineering",
            "role": "primary",
            "high_triggers": ["vendor widget review"],
        },
        "routing": {
            "positive": ["Perform a vendor widget review for this contract."],
            "negative": ["Write a bedtime story about a fox."],
        },
        "rationale": "Vendor the small MIT instruction set byte-for-byte because provenance, license, safety, and shadow routing all pass.",
        "excluded_upstream_components": ["scripts", "hooks"],
    }


def main() -> None:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-capability-lifecycle-") as temporary:
        base = Path(temporary)

        _project, agent, service = fixture(base, "unsafe-candidate")
        candidate_value, content = candidate()
        candidate_value["gate_results"][0]["status"] = "block"
        candidate_value["gate_results"][0]["reason_codes"] = ["FULL_COMMIT_REQUIRED"]
        blocked = service.plan_integration(candidate_value, assembly(candidate_value, content))
        results.append(
            {
                "id": "blocking-gate-cannot-activate",
                "passed": reason(blocked, "INTEGRATION_VALIDATION_FAILED"),
            }
        )

        _project, agent, service = fixture(base, "snapshot-tamper")
        candidate_value, content = candidate()
        candidate_value["source"]["snapshot_sha256"] = "0" * 64
        blocked = service.plan_integration(candidate_value, assembly(candidate_value, content))
        results.append(
            {
                "id": "snapshot-tamper-blocked",
                "passed": reason(blocked, "INTEGRATION_VALIDATION_FAILED"),
            }
        )

        _project, agent, service = fixture(base, "path-traversal")
        candidate_value, content = candidate()
        traversal = assembly(candidate_value, content)
        traversal["files"][0]["target"] = "skills/widget-helper/../../project/skill-config.json"
        blocked = service.plan_integration(candidate_value, traversal)
        results.append(
            {
                "id": "path-traversal-blocked",
                "passed": reason(blocked, "INTEGRATION_VALIDATION_FAILED"),
            }
        )

        _project, agent, service = fixture(base, "vendor-pin")
        vendor_value, vendor_skill, vendor_license = vendor_candidate()
        vendor_plan = service.plan_integration(vendor_value, vendor_assembly(vendor_value, vendor_skill, vendor_license))
        vendor_apply = service.apply(vendor_plan.get("plan", {}).get("plan_id", ""), True)
        vendor_lock = json.loads((agent / VENDOR_LOCK).read_text())
        package = next(item for item in vendor_lock["packages"] if item["id"] == "vendor-widget")
        results.append(
            {
                "id": "vendor-pin-is-byte-exact-and-locked",
                "passed": bool(vendor_plan.get("ok") and vendor_apply.get("ok") and (agent / "vendor/vendor-widget/SKILL.md").read_text() == vendor_skill and package["commit"] == FULL_COMMIT and package["files"]["vendor/vendor-widget/SKILL.md"] == sha256_bytes(vendor_skill.encode())),
            }
        )

        _project, agent, service = fixture(base, "vendor-byte-drift")
        vendor_value, vendor_skill, vendor_license = vendor_candidate()
        drifted = vendor_assembly(vendor_value, vendor_skill + "tampered\n", vendor_license)
        blocked = service.plan_integration(vendor_value, drifted)
        results.append(
            {
                "id": "vendor-byte-drift-blocked",
                "passed": reason(blocked, "INTEGRATION_VALIDATION_FAILED"),
            }
        )

        _project, agent, service = fixture(base, "principles-only")
        principles_candidate, upstream_content = candidate("competing-framework")
        principles_candidate["recommendation"] = "adapt-local-principles"
        framework_gate = next(item for item in principles_candidate["gate_results"] if item["gate"] == "framework-conflict")
        framework_gate["status"] = "block"
        framework_gate["reason_codes"] = ["COMPETING_BOOT_ROUTER_OR_MEMORY"]
        local_content = "---\nname: widget-helper\ndescription: Apply locally derived widget review principles safely.\n---\n\n# Local Principles\n\nVerify outcomes before completion.\n"
        proposal = assembly(principles_candidate, local_content)
        proposal["integration_mode"] = "adapt-local-principles"
        proposal["derived_principles"] = ["Verify observable outcomes before making a completion claim."]
        principle_plan = service.plan_integration(principles_candidate, proposal)
        principle_apply = service.apply(principle_plan.get("plan", {}).get("plan_id", ""), True)
        local_bytes = (agent / "skills/widget-helper/SKILL.md").read_text()
        results.append(
            {
                "id": "competing-framework-is-principles-only",
                "passed": bool(principle_plan.get("ok") and principle_apply.get("ok") and local_bytes == local_content and local_bytes != upstream_content and not (agent / "vendor/competing-framework").exists()),
            }
        )

    passed = sum(1 for item in results if item.get("passed"))
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
