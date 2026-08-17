#!/usr/bin/env python3
"""Shared fixtures for Continuity transaction acceptance tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

from agent_os_context_memory import json_bytes
from agent_os_continuity_transactions import (
    CATALOG_REL,
    MIGRATION_REGISTRY_REL,
    PROJECTION_REL,
    ContinuityTransactionService,
)

SOURCE_ROOT = Path(__file__).resolve().parents[2]
W3_TEST_PATH = Path(__file__).resolve().parents[1] / "continuity_core/test_support.py"


def load_w3_fixture_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "agent_os_w3_continuity_fixture", W3_TEST_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load W3 continuity fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


W3 = load_w3_fixture_module()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(base: Path, *, configured: bool) -> Path:
    root, _catalog = W3.make_fixture(base)
    shutil.copy2(SOURCE_ROOT / MIGRATION_REGISTRY_REL, root / MIGRATION_REGISTRY_REL)
    write_json(
        root / "project/adapter-fingerprint.json",
        {
            "schema_version": 1,
            "project_id": W3.PROJECT_ID,
            "binding_schema_version": 1,
            "digests": {},
        },
    )
    manifest_path = root / "_manifest/base-release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"].append(
        {
            "path": MIGRATION_REGISTRY_REL,
            "type": "file",
            "sha256": sha256(root / MIGRATION_REGISTRY_REL),
        }
    )
    manifest["entries"] = sorted(manifest["entries"], key=lambda item: item["path"])
    write_json(manifest_path, manifest)
    W3.commit_all(root.parent, "add W4 transaction contracts")
    if not configured:
        (root / CATALOG_REL).unlink()
        (root / PROJECTION_REL).unlink(missing_ok=True)
    return root


def initialize(root: Path) -> tuple[ContinuityTransactionService, dict[str, Any]]:
    service = ContinuityTransactionService(root)
    planned = service.plan_initialize()
    if not planned.get("ok"):
        raise RuntimeError(f"initialize plan failed: {planned}")
    result = service.apply(planned["plan"]["plan_id"], True)
    if not result.get("ok"):
        raise RuntimeError(f"initialize apply failed: {result}")
    return service, result


def make_v0(root: Path, *, unknown: bool) -> bytes:
    catalog_path = root / CATALOG_REL
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["schema_version"] = 0
    catalog.pop("catalog_revision", None)
    if unknown:
        catalog["future_unknown"] = {"must_not_be_dropped": True}
    write_json(catalog_path, catalog)
    return catalog_path.read_bytes()
