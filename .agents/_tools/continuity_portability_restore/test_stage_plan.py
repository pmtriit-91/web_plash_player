#!/usr/bin/env python3
"""Focused RS2a checks for restore stage-plan extraction and topology."""

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
from continuity_portability_restore.stage_plan import RestoreStagePlanMixin

SOURCE_ROOT = TOOLS_DIR.parent


class ExistingStageProbe(ContinuityRestoreMixin):
    def __init__(self, root: Path, inspected: dict[str, Any]) -> None:
        self.root = root
        self.inspected = inspected

    def verified_owned_directory(
        self,
        relative: str,
        *,
        create: bool,
    ) -> Path:
        staging = self.root / relative
        if create:
            staging.mkdir(parents=True, exist_ok=True)
        return staging

    def inspect_bundle(self, source: str | Path) -> dict[str, Any]:
        return self.inspected


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, **details: Any) -> None:
        cases.append({"id": identifier, "passed": passed, **details})

    topology = json.loads(
        (SOURCE_ROOT / "_tools/continuity_portability_restore/topology.json").read_text(
            encoding="utf-8"
        )
    )
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    facade_path = "_tools/agent_os_continuity_portability_restore.py"
    stage_path = "_tools/continuity_portability_restore/stage_plan.py"
    shard_path = "_tools/continuity_portability_restore/test_stage_plan.py"
    check(
        "restore-topology-declares-stage-plan-dependency",
        stage_path in entries[facade_path]["depends_on"]
        and entries[stage_path]["focused_shard"] == shard_path,
    )

    stage_source = (SOURCE_ROOT / stage_path).read_text(encoding="utf-8")
    check(
        "stage-plan-module-has-no-reverse-facade-import",
        "import agent_os_continuity_portability_restore" not in stage_source
        and "from agent_os_continuity_portability_restore" not in stage_source,
    )

    methods = ("stage_bundle", "plan_restore")
    check(
        "public-method-identities-are-preserved-through-inheritance",
        all(
            getattr(ContinuityRestoreMixin, name)
            is getattr(RestoreStagePlanMixin, name)
            for name in methods
        ),
    )
    check(
        "public-mro-includes-stage-plan-mixin",
        RestoreStagePlanMixin in ContinuityRestoreMixin.__mro__,
        mro=[item.__name__ for item in ContinuityRestoreMixin.__mro__],
    )

    service = ContinuityRestoreMixin()
    with patch.object(
        service,
        "stage_bundle",
        return_value={"ok": False, "reason_codes": ["PATCHED"]},
    ):
        patched = service.stage_bundle(Path("unused"), {}, "unused")
    check(
        "instance-monkeypatch-contract-remains-compatible",
        patched == {"ok": False, "reason_codes": ["PATCHED"]},
    )

    check(
        "plan-expiry-failure-result-survives-extraction",
        service.plan_restore("unused", expiry_seconds=59)
        == {"ok": False, "reason_codes": ["PORTABILITY_PLAN_EXPIRY_INVALID"]},
    )

    with tempfile.TemporaryDirectory(prefix="aos15-w6-rs2a-") as temporary:
        root = Path(temporary)
        destination = root / "_runtime/continuity-portability/staging/bundle-1"
        destination.mkdir(parents=True)
        manifest = {"bundle_id": "bundle-1", "inventory_sha256": "inventory"}
        reusable = ExistingStageProbe(
            root,
            {
                "ok": True,
                "manifest_sha256": "manifest",
                "manifest": {"inventory_sha256": "inventory"},
            },
        ).stage_bundle(root, manifest, "manifest")
        conflict = ExistingStageProbe(root, {"ok": False}).stage_bundle(
            root, manifest, "manifest"
        )
    check(
        "existing-stage-reuse-and-conflict-results-survive-extraction",
        reusable == {"ok": True, "staged_path": destination}
        and conflict == {"ok": False, "reason_codes": ["PORTABILITY_STAGING_CONFLICT"]},
    )

    failed = [item for item in cases if not item["passed"]]
    print(
        json.dumps(
            {
                "ok": not failed,
                "suite": "aos15-w6-br5-rs2a-stage-plan",
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
