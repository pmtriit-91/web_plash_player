#!/usr/bin/env python3
"""Focused RS1 checks for restore target-analysis extraction and topology."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_continuity_portability_restore import ContinuityRestoreMixin
from continuity_portability_restore.target_analysis import RestoreTargetAnalysisMixin

SOURCE_ROOT = TOOLS_DIR.parent


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": passed, **details})

    topology_index = json.loads(
        (SOURCE_ROOT / "_tools/module-topology-index.json").read_text(encoding="utf-8")
    )
    domains = {item["domain"]: item for item in topology_index["domains"]}
    check(
        "root-index-routes-each-domain-one-hop",
        {
            "context-memory",
            "continuity-portability-restore",
            "continuity-transactions",
            "migration",
            "publication",
            "release-packaging",
            "tooling-topology",
        }
        <= set(domains)
        and domains["context-memory"]["topology"] == "_tools/context_memory/topology.json"
        and domains["continuity-portability-restore"]["topology"]
        == "_tools/continuity_portability_restore/topology.json"
        and domains["continuity-transactions"]["topology"]
        == "_tools/continuity_transactions/topology.json"
        and domains["migration"]["topology"] == "_tools/migration/topology.json"
        and domains["publication"]["topology"] == "_tools/publication/topology.json"
        and domains["release-packaging"]["topology"]
        == "_tools/release_packaging/topology.json"
        and domains["tooling-topology"]["topology"]
        == "_tools/tooling_topology/topology.json",
    )

    topology = json.loads(
        (SOURCE_ROOT / "_tools/continuity_portability_restore/topology.json").read_text(
            encoding="utf-8"
        )
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    facade_path = "_tools/agent_os_continuity_portability_restore.py"
    apply_path = "_tools/continuity_portability_restore/apply_orchestration.py"
    analysis_path = "_tools/continuity_portability_restore/target_analysis.py"
    contracts_path = "_tools/continuity_portability_restore/contracts.py"
    backup_validation_path = (
        "_tools/continuity_portability_restore/backup_validation.py"
    )
    backup_lifecycle_path = "_tools/continuity_portability_restore/backup_lifecycle.py"
    receipt_validation_path = (
        "_tools/continuity_portability_restore/receipt_validation.py"
    )
    receipt_builder_path = "_tools/continuity_portability_restore/receipt_builder.py"
    plan_validation_path = "_tools/continuity_portability_restore/plan_validation.py"
    stage_path = "_tools/continuity_portability_restore/stage_plan.py"
    shard_path = "_tools/continuity_portability_restore/test_target_analysis.py"
    contracts_shard = "_tools/continuity_portability_restore/test_contracts.py"
    plan_validation_shard = (
        "_tools/continuity_portability_restore/test_plan_validation.py"
    )
    check(
        "restore-topology-declares-facade-analysis-and-shard",
        topology["public_facade"] == facade_path
        and set(entries[facade_path]["depends_on"])
        == {
            analysis_path,
            apply_path,
            backup_lifecycle_path,
            backup_validation_path,
            contracts_path,
            plan_validation_path,
            receipt_builder_path,
            receipt_validation_path,
            stage_path,
        }
        and entries[analysis_path]["focused_shard"] == shard_path
        and entries[contracts_path]["focused_shard"] == contracts_shard
        and entries[plan_validation_path]["focused_shard"] == plan_validation_shard,
    )

    analysis_source = (SOURCE_ROOT / analysis_path).read_text(encoding="utf-8")
    check(
        "analysis-module-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in analysis_source
        and "from agent_os_continuity_portability_restore" not in analysis_source,
    )

    methods = (
        "restore_target_execution_order",
        "restore_compatibility",
        "render_restore_diff",
    )
    check(
        "public-method-identities-are-preserved-through-inheritance",
        all(
            getattr(ContinuityRestoreMixin, name)
            is getattr(RestoreTargetAnalysisMixin, name)
            for name in methods
        ),
    )
    check(
        "public-mro-includes-target-analysis-mixin",
        RestoreTargetAnalysisMixin in ContinuityRestoreMixin.__mro__,
        mro=[item.__name__ for item in ContinuityRestoreMixin.__mro__],
    )

    service = ContinuityRestoreMixin()
    with patch.object(
        service,
        "restore_target_execution_order",
        return_value=(["patched"], []),
    ):
        patched = service.restore_target_execution_order(Path("unused"), {}, [])
    check(
        "instance-monkeypatch-contract-remains-compatible",
        patched == (["patched"], []),
    )

    class CompatibilityProbe(ContinuityRestoreMixin):
        def __init__(self, contracts: dict[str, str] | None) -> None:
            self._contracts = contracts

        def contract_hashes(self) -> dict[str, str] | None:
            return self._contracts

        def binding(self) -> dict[str, str]:
            return {"project_id": "target-project"}

    unavailable = CompatibilityProbe(None).restore_compatibility({})
    contracts = {
        "binding_sha256": "binding",
        "adapter_fingerprint_sha256": "adapter",
        "core_manifest_sha256": "core",
        "record_type_registry_sha256": "registry",
        "recovery_profile_sha256": "recovery",
        "retention_policy_sha256": "retention",
    }
    contaminated = CompatibilityProbe(contracts).restore_compatibility(
        {"project_id": "foreign-project"}
    )
    check(
        "compatibility-fail-closed-results-survive-extraction",
        unavailable == [{"code": "PORTABILITY_CONTRACTS_UNAVAILABLE"}]
        and contaminated
        == [
            {
                "code": "PORTABILITY_PROJECT_CONTAMINATION",
                "bundle_project_id": "foreign-project",
                "target_project_id": "target-project",
            }
        ],
    )

    class DiffProbe(ContinuityRestoreMixin):
        def __init__(self, root: Path) -> None:
            self.root = root

        def policy(self) -> tuple[dict[str, Any], list[str]]:
            return (
                {
                    "bounds": {
                        "max_file_bytes": 1024,
                        "max_manifest_bytes": 4096,
                    }
                },
                [],
            )

        def project_path(self, relative: str) -> Path:
            return self.root / relative

    with tempfile.TemporaryDirectory(prefix="aos15-w6-rs1-") as temporary:
        root = Path(temporary)
        project = root / "project"
        bundle = root / "bundle"
        target_path = project / "docs/status.md"
        payload_path = bundle / "files/status.bin"
        target_path.parent.mkdir(parents=True)
        payload_path.parent.mkdir(parents=True)
        target_path.write_text("before\n", encoding="utf-8")
        payload_path.write_text("after\n", encoding="utf-8")
        rendered = DiffProbe(project).render_restore_diff(
            [
                {
                    "entry_id": "status",
                    "path": "docs/status.md",
                    "before_sha256": "before-hash",
                    "after_sha256": "after-hash",
                    "bytes": 6,
                }
            ],
            bundle,
            {
                "entries": [
                    {
                        "entry_id": "status",
                        "storage_path": "files/status.bin",
                        "bytes": 6,
                    }
                ]
            },
        )
    check(
        "bounded-text-diff-output-survives-extraction",
        "--- a/docs/status.md" in rendered
        and "+++ b/docs/status.md" in rendered
        and "-before" in rendered
        and "+after" in rendered,
        rendered=rendered,
    )

    failed = [item for item in cases if not item["passed"]]
    print(
        json.dumps(
            {
                "ok": not failed,
                "suite": "aos15-w6-br5-rs1-target-analysis",
                "passed": len(cases) - len(failed),
                "total": len(cases),
                "cases": cases,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
