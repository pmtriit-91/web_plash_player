#!/usr/bin/env python3
"""Focused P1a2c checks for restore artifact collision admission."""

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash, receipt_hash
from agent_os_continuity_portability import artifact_id
from continuity_portability.test_support import (
    export_bundle,
    prepare_fixture,
    rehash_restore_plan,
)


def replace_paths(
    items: list[dict[str, Any]], paths: tuple[str, str]
) -> list[dict[str, Any]]:
    replaced = deepcopy(items)
    if len(replaced) != len(paths):
        raise RuntimeError(f"expected {len(paths)} restore items, got {len(replaced)}")
    for item, path in zip(replaced, paths, strict=True):
        item["path"] = path
    return sorted(replaced, key=lambda item: item["path"])


def forge_plan(plan: dict[str, Any], paths: tuple[str, str]) -> dict[str, Any]:
    forged = deepcopy(plan)
    forged["targets"] = replace_paths(forged["targets"], paths)
    forged["target_inventory_sha256"] = canonical_hash(forged["targets"])
    rehash_restore_plan(forged)
    return forged


def forge_backup(index: dict[str, Any], paths: tuple[str, str]) -> dict[str, Any]:
    forged = deepcopy(index)
    forged["files"] = replace_paths(forged["files"], paths)
    forged["content_sha256"] = receipt_hash(forged)
    return forged


def forge_receipt(receipt: dict[str, Any], paths: tuple[str, str]) -> dict[str, Any]:
    forged = deepcopy(receipt)
    forged["targets"] = replace_paths(forged["targets"], paths)
    forged["target_inventory_sha256"] = canonical_hash(forged["targets"])
    forged["receipt_id"] = artifact_id(
        forged,
        "continuity-restore-",
        "receipt_id",
    )
    forged["content_sha256"] = receipt_hash(forged)
    return forged


def add_result(
    results: list[dict[str, Any]], identifier: str, passed: bool, errors: Any = None
) -> None:
    results.append({"id": identifier, "passed": passed, "errors": errors})


def main() -> None:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="aos15-w6-p1a2c-") as temporary:
        root = prepare_fixture(Path(temporary))
        destination = Path(temporary) / "bundle"
        service, _exported = export_bundle(root, destination)
        (root.parent / "docs/roadmap.md").write_bytes(b"# restore drift\n")
        (root.parent / "docs/context/current-status.md").write_bytes(
            b"# restore status drift\n"
        )
        planned = service.plan_restore(destination)
        if planned.get("ok") is not True:
            raise RuntimeError(f"restore planning failed: {planned}")
        plan = planned["plan"]
        plan_errors = service.validate_restore_plan(plan, plan["plan_id"])
        applied = service.apply_restore(plan["plan_id"], True)
        if applied.get("ok") is not True:
            raise RuntimeError(f"restore apply failed: {applied}")
        receipt = applied["receipt"]
        plan_reference = {
            "backup_id": receipt["backup"]["backup_id"],
            "plan_id": receipt["plan_id"],
            "project_id": receipt["project_id"],
            "targets": [
                {**target, "backup_required": True} for target in receipt["targets"]
            ],
        }
        backup_index_path = service.project_path(receipt["backup"]["index_path"])
        backup_path = backup_index_path.parent
        backup_index = json.loads(backup_index_path.read_text(encoding="utf-8"))
        backup_errors = service.validate_restore_backup_index(
            backup_index,
            plan_reference,
            backup_path,
        )
        receipt_errors = service.validate_restore_receipt(receipt)
        add_result(
            results,
            "current-restore-plan-remains-valid",
            plan_errors == [],
            plan_errors,
        )
        add_result(
            results,
            "current-restore-backup-remains-valid",
            backup_errors == [],
            backup_errors,
        )
        add_result(
            results,
            "current-restore-receipt-remains-valid",
            receipt_errors == [],
            receipt_errors,
        )
        validators = (
            (
                "plan",
                "PORTABILITY_RESTORE_TARGET_PATH_COLLISION",
                lambda paths: service.validate_restore_plan(
                    forge_plan(plan, paths),
                    forge_plan(plan, paths)["plan_id"],
                ),
            ),
            (
                "backup",
                "PORTABILITY_RESTORE_BACKUP_PATH_COLLISION",
                lambda paths: service.validate_restore_backup_index(
                    forge_backup(backup_index, paths),
                    plan_reference,
                    backup_path,
                ),
            ),
            (
                "receipt",
                "PORTABILITY_RESTORE_RECEIPT_TARGET_PATH_COLLISION",
                lambda paths: service.validate_restore_receipt(
                    forge_receipt(receipt, paths)
                ),
            ),
        )
        for suffix, paths in (
            ("case-only", ("docs/Guide.md", "docs/guide.md")),
            ("nfc-nfd", ("docs/café.md", "docs/cafe\u0301.md")),
        ):
            for owner, collision_code, validate in validators:
                errors = validate(paths)
                add_result(
                    results,
                    f"{owner}-rejects-{suffix}-collision",
                    errors == [collision_code],
                    errors,
                )
        distinct_paths = ("docs/alpha.md", "docs/beta.md")
        distinct_errors = [
            (collision_code, validate(distinct_paths))
            for _owner, collision_code, validate in validators
        ]
        add_result(
            results,
            "distinct-paths-are-not-misclassified-as-collisions",
            all(
                collision_code not in errors
                for collision_code, errors in distinct_errors
            ),
            distinct_errors,
        )
    passed = sum(1 for item in results if item["passed"])
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
