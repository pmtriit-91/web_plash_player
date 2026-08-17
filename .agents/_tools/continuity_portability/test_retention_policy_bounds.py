#!/usr/bin/env python3
"""AOS-15 W5 focused shard: retention policy and traversal bounds."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity_portability import (
    POLICY_AGENT_REL,
    POLICY_FIELDS,
    ContinuityPortabilityService,
)
from continuity_portability.test_support import (
    SOURCE_ROOT,
    prepare_fixture,
    write_json,
)

SHARD_ID = "retention-policy-bounds"
GROUPS = ("retention-archive",)
TIMEOUT_SECONDS = 120


def scenario_retention_policy_contract(cases: list[tuple[str, bool]]) -> None:
    policy = json.loads((SOURCE_ROOT / POLICY_AGENT_REL).read_text(encoding="utf-8"))

    policy_schema = json.loads(
        (
            SOURCE_ROOT / "core/contracts/continuity-retention-policy.schema.json"
        ).read_text(encoding="utf-8")
    )

    cases.append(
        (
            "retention-policy-is-exact-and-privacy-safe",
            set(policy) == POLICY_FIELDS
            and set(policy_schema["required"]) == POLICY_FIELDS
            and {item["retention_class"] for item in policy["classes"]}
            == {
                "critical-active",
                "critical-history",
                "evidence",
                "operational",
                "advisory",
            }
            and policy["archive_original_required"] is True
            and policy["explicit_confirmation_required"] is True
            and policy["raw_conversation_allowed"] is False,
        )
    )


def scenario_retention_baseline_and_git_bounds(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-baseline-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        preflight = service.preflight()
        retention = service.inspect_retention()
        head = service.head()
        tree = service.git_tree(head or "")
        with patch.object(
            service,
            "git_bytes_bounded",
            wraps=service.git_bytes_bounded,
        ) as git_bytes:
            binding_blob, binding_error = service.git_blob_at(
                head or "",
                ".agents/project/project-binding.json",
                tree if tree is not None else {},
            )
        ls_tree_calls = [
            call.args for call in git_bytes.call_args_list if "ls-tree" in call.args
        ]
        prefix_bound = service.populate_git_tree_prefixes(
            head or "",
            [".agents/project"],
            {},
            maximum_entries=1,
            maximum_output_bytes=1,
        )
        binding = next(
            item
            for item in retention["candidates"]
            if item["reference_id"] == "binding"
        )
        cases.extend(
            [
                (
                    "state-aware-missing-genesis-does-not-block-export-preflight",
                    preflight.get("ok") is True
                    and preflight["continuity_health"]["topology_state"] == "complete"
                    and preflight["continuity_health"]["authority_state"] == "partial",
                ),
                (
                    "critical-active-and-live-required-records-are-held",
                    binding["archive_eligible"] is False
                    and "RETENTION_CRITICAL_ACTIVE_HOLD" in binding["hold_reasons"]
                    and "RETENTION_ACTIVE_AUTHORITY_HOLD" in binding["hold_reasons"]
                    and binding["prune_eligible"] is False,
                ),
                (
                    "critical-active-selection-cannot-create-archive-plan",
                    service.plan_archive(["binding"]).get("reason_codes")
                    == ["RETENTION_SELECTION_HELD"],
                ),
                (
                    "malformed-archive-selection-fails-without-exception",
                    service.plan_archive([{}]).get("reason_codes")
                    == ["RETENTION_SELECTION_INVALID"]
                    and service.plan_archive(["binding", 7]).get("reason_codes")
                    == ["RETENTION_SELECTION_INVALID"],
                ),
                (
                    "Git-provenance-uses-bounded-literal-path-lookup",
                    binding_error is None
                    and binding_blob is not None
                    and len(ls_tree_calls) == 1
                    and ls_tree_calls[0][:5]
                    == (
                        "--literal-pathspecs",
                        "ls-tree",
                        "-z",
                        "--full-tree",
                        head,
                    )
                    and ls_tree_calls[0][-2:]
                    == ("--", ".agents/project/project-binding.json")
                    and "-r" not in ls_tree_calls[0],
                ),
                (
                    "scoped-Git-prefix-enumeration-has-output-and-entry-bounds",
                    prefix_bound == "PORTABILITY_SOURCE_GIT_TREE_BOUND_EXCEEDED",
                ),
            ]
        )


def scenario_retention_traversal_bounds(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-traversal-bounds-") as temporary:
        root = prepare_fixture(Path(temporary))
        service = ContinuityPortabilityService(root)
        policy_path = root / POLICY_AGENT_REL
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["bounds"]["max_entries"] = 2
        write_json(policy_path, policy)

        handoff_root = root / "project/context/bounded-handoffs"
        handoff_root.mkdir()
        for index in range(3):
            (handoff_root / f"noise-{index}.tmp").write_bytes(b"noise")
        context_manifest_path = root / "project/context/context-manifest.json"
        context_manifest = json.loads(context_manifest_path.read_text(encoding="utf-8"))
        context_manifest["handoff_directory"] = "project/context/bounded-handoffs"
        write_json(context_manifest_path, context_manifest)
        context_issues = service.context_closure({}, "context-manifest")

        receipt_root = root / "project/context/continuity-portability-receipts"
        receipt_root.mkdir(parents=True, exist_ok=True)
        for index in range(3):
            (receipt_root / f"noise-{index}.tmp").write_bytes(b"noise")
        receipt_listing = service.list_receipts()

        recovery_root = root / "project/context/continuity-archives"
        recovery_root.mkdir(parents=True, exist_ok=True)
        for index in range(19):
            (recovery_root / f"empty-{index:02d}").mkdir()
        recovery_issues = service.recovery_closure({}, 1)
        cases.extend(
            [
                (
                    "handoff-and-receipt-scans-count-non-JSON-entries",
                    any(
                        issue.get("code") == "PORTABILITY_ENTRY_BOUND_EXCEEDED"
                        for issue in context_issues
                    )
                    and receipt_listing.get("errors")
                    == [{"code": "PORTABILITY_RECEIPT_BOUND_EXCEEDED"}],
                ),
                (
                    "recovery-traversal-counts-empty-directories",
                    any(
                        issue.get("code") == "PORTABILITY_ENTRY_BOUND_EXCEEDED"
                        for issue in recovery_issues
                    ),
                ),
            ]
        )


SCENARIOS = (
    (
        "retention-policy-contract",
        ("retention-policy-is-exact-and-privacy-safe",),
        scenario_retention_policy_contract,
    ),
    (
        "retention-baseline-and-git-bounds",
        (
            "state-aware-missing-genesis-does-not-block-export-preflight",
            "critical-active-and-live-required-records-are-held",
            "critical-active-selection-cannot-create-archive-plan",
            "malformed-archive-selection-fails-without-exception",
            "Git-provenance-uses-bounded-literal-path-lookup",
            "scoped-Git-prefix-enumeration-has-output-and-entry-bounds",
        ),
        scenario_retention_baseline_and_git_bounds,
    ),
    (
        "retention-traversal-bounds",
        (
            "handoff-and-receipt-scans-count-non-JSON-entries",
            "recovery-traversal-counts-empty-directories",
        ),
        scenario_retention_traversal_bounds,
    ),
)


if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                str(TOOLS_DIR / "test-continuity-portability.py"),
                "--shard",
                SHARD_ID,
                *sys.argv[1:],
            ]
        )
    )
