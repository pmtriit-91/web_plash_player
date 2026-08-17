#!/usr/bin/env python3
"""Focused P1a2b checks for archive portable-path collision admission."""

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash, receipt_hash, sha256_bytes
from agent_os_continuity_portability import ContinuityPortabilityService, artifact_id
from agent_os_continuity_portability_retention_archive import (
    ContinuityRetentionArchiveMixin,
)
from continuity_portability.test_support import prepare_fixture


class ArchiveBuilderHarness:
    build_archive_manifest = ContinuityRetentionArchiveMixin.build_archive_manifest

    def __init__(self, root: Path, paths: tuple[str, str]):
        self.root = root
        self.paths = paths
        self.payloads: dict[str, Path] = {}
        for index, path in enumerate(paths):
            payload = root / f"payload-{index}.bin"
            payload.write_bytes(f"payload-{index}".encode())
            self.payloads[path] = payload
        self.catalog_path = root / "catalog.json"
        self.catalog_path.write_text("{}", encoding="utf-8")

    def preflight(self) -> dict[str, Any]:
        references = []
        for index, path in enumerate(self.paths):
            references.append(
                {
                    "reference_id": f"fixture-{chr(97 + index)}",
                    "source": {
                        "path": path,
                        "sha256": sha256_bytes(self.payloads[path].read_bytes()),
                    },
                    "privacy_class": "project-internal",
                    "retention_class": "critical-history",
                    "supersedes": [],
                }
            )
        return {
            "ok": True,
            "head": "0" * 40,
            "policy": {"bounds": {"max_file_bytes": 4096}},
            "contracts": {
                "binding_sha256": "1" * 64,
                "adapter_fingerprint_sha256": "2" * 64,
                "retention_policy_sha256": "3" * 64,
            },
            "catalog": {
                "project_id": "fixture",
                "updated_at": "2026-07-29T00:00:00Z",
                "references": references,
            },
        }

    def inspect_retention(self) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "reference_id": f"fixture-{chr(97 + index)}",
                    "archive_eligible": True,
                    "successor_reference_ids": [],
                    "hold_reasons": [],
                }
                for index in range(2)
            ]
        }

    def project_path(self, path: str) -> Path:
        return self.payloads[path]

    def agent_path(self, _path: str) -> Path:
        return self.catalog_path

    @staticmethod
    def path_is_link_like(_path: Path) -> bool:
        return False

    @staticmethod
    def privacy_error(_content: bytes, _path: str) -> None:
        return None

    @staticmethod
    def validate_archive_manifest(_manifest: Any) -> list[str]:
        return []


def producer_codes(paths: tuple[str, str]) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="aos15-w6-p1a2b-builder-") as temporary:
        result = ArchiveBuilderHarness(Path(temporary), paths).build_archive_manifest(
            ["fixture-a", "fixture-b"]
        )
    return list(result.get("reason_codes", []))


def manifest_with_paths(
    manifest: dict[str, Any], paths: tuple[str, str]
) -> dict[str, Any]:
    forged = deepcopy(manifest)
    template = manifest["entries"][0]
    entries = []
    references = ["fixture-a", "fixture-b"]
    for reference_id, path in zip(references, paths, strict=True):
        entry = deepcopy(template)
        entry["reference_id"] = reference_id
        entry["canonical_path"] = path
        entry["entry_id"] = (
            "continuity-entry-"
            + canonical_hash(
                {
                    "reference_id": reference_id,
                    "canonical_path": path,
                    "sha256": entry["sha256"],
                }
            )[:24]
        )
        entry["storage_path"] = f"files/{entry['entry_id']}.bin"
        entries.append(entry)
    entries.sort(key=lambda item: item["canonical_path"])
    inventory_sha256 = canonical_hash(entries)
    forged["reference_ids"] = references
    forged["entries"] = entries
    forged["summary"] = {
        "reference_count": 2,
        "entry_count": 2,
        "total_bytes": sum(item["bytes"] for item in entries),
        "retention_classes": sorted({item["retention_class"] for item in entries}),
        "predecessors": [
            {"reference_id": item, "predecessor_reference_ids": []}
            for item in references
        ],
        "successors": [
            {"reference_id": item, "successor_reference_ids": []} for item in references
        ],
        "holds": [{"reference_id": item, "hold_reasons": []} for item in references],
        "inventory_sha256": inventory_sha256,
        "source_deleted": False,
    }
    forged["entry_count"] = 2
    forged["total_bytes"] = forged["summary"]["total_bytes"]
    forged["inventory_sha256"] = inventory_sha256
    forged["archive_id"] = artifact_id(forged, "continuity-archive-", "archive_id")
    forged["content_sha256"] = receipt_hash(forged)
    return forged


def add_result(results: list[dict[str, Any]], identifier: str, passed: bool) -> None:
    results.append({"id": identifier, "passed": passed})


def main() -> None:
    results: list[dict[str, Any]] = []
    collision_code = "RETENTION_ARCHIVE_PATH_COLLISION"
    for identifier, paths in (
        ("builder-rejects-case-only-collision", ("docs/Guide.md", "docs/guide.md")),
        ("builder-rejects-nfc-nfd-collision", ("docs/café.md", "docs/cafe\u0301.md")),
    ):
        add_result(results, identifier, collision_code in producer_codes(paths))
    add_result(
        results,
        "builder-preserves-distinct-paths",
        collision_code not in producer_codes(("docs/alpha.md", "docs/beta.md")),
    )
    with tempfile.TemporaryDirectory(prefix="aos15-w6-p1a2b-") as temporary:
        service = ContinuityPortabilityService(
            prepare_fixture(Path(temporary), historical=True)
        )
        built = service.build_archive_manifest(["roadmap-history"])
        manifest = built.get("manifest", {})
        add_result(
            results,
            "current-archive-manifest-remains-valid",
            built.get("ok") is True
            and service.validate_archive_manifest(manifest) == [],
        )
        for identifier, paths in (
            (
                "manifest-rejects-case-only-collision",
                ("docs/Guide.md", "docs/guide.md"),
            ),
            (
                "manifest-rejects-nfc-nfd-collision",
                ("docs/café.md", "docs/cafe\u0301.md"),
            ),
        ):
            add_result(
                results,
                identifier,
                service.validate_archive_manifest(manifest_with_paths(manifest, paths))
                == ["RETENTION_ARCHIVE_ENTRY_PATH_COLLISION"],
            )
        add_result(
            results,
            "manifest-preserves-distinct-paths",
            service.validate_archive_manifest(
                manifest_with_paths(manifest, ("docs/alpha.md", "docs/beta.md"))
            )
            == [],
        )
        add_result(
            results,
            "exact-duplicate-keeps-existing-invalid-code",
            service.validate_archive_manifest(
                manifest_with_paths(manifest, ("docs/same.md", "docs/same.md"))
            )
            == ["RETENTION_ARCHIVE_ENTRY_INVALID"],
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
