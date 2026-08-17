#!/usr/bin/env python3
"""AOS-15 W5 focused shard: export bundle adversarial guards."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_context_memory import canonical_hash
from agent_os_continuity_portability import (
    ContinuityPortabilityService,
    artifact_entry_id,
)
from continuity_portability.test_support import (
    create_directory_redirect,
    prepare_fixture,
    rehash_export_inventory,
    rehash_manifest,
    remove_directory_redirect,
    write_json,
)

SHARD_ID = "export-bundle-adversarial-guards"
GROUPS = ("export",)
TIMEOUT_SECONDS = 120


def scenario_export_bundle_adversarial_guards(
    cases: list[tuple[str, bool]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-adversarial-") as temporary:
        root = prepare_fixture(Path(temporary), payload_mode="portable-bytes")
        service = ContinuityPortabilityService(root)
        destination = Path(temporary) / "bundle"
        planned = service.plan_export(destination)
        service.apply_portability(
            planned["plan"]["plan_id"],
            True,
            expected_operation="export",
        )

        extra = Path(temporary) / "extra"
        shutil.copytree(destination, extra)
        (extra / "unexpected.bin").write_bytes(b"extra")
        cases.append(
            (
                "extra-bundle-file-is-rejected",
                "PORTABILITY_BUNDLE_FILE_SET_MISMATCH"
                in service.inspect_bundle(extra).get("reason_codes", []),
            )
        )

        redirect = Path(temporary) / "redirect"
        shutil.copytree(destination, redirect)
        redirect_path = redirect / "continuity-export-manifest.json"
        redirect_manifest = json.loads(redirect_path.read_text(encoding="utf-8"))
        redirect_entry = next(
            item for item in redirect_manifest["entries"] if item["present"]
        )
        redirect_entry["storage_path"] = "files/redirect.bin"
        rehash_manifest(redirect_manifest)
        write_json(redirect_path, redirect_manifest)
        cases.append(
            (
                "rehash-cannot-redirect-storage-path",
                "PORTABILITY_MANIFEST_ENTRY_INVALID"
                in service.inspect_bundle(redirect).get("reason_codes", []),
            )
        )

        traversal = Path(temporary) / "traversal"
        shutil.copytree(destination, traversal)
        traversal_path = traversal / "continuity-export-manifest.json"
        traversal_manifest = json.loads(traversal_path.read_text(encoding="utf-8"))
        traversal_entry = traversal_manifest["entries"][0]
        traversal_entry["canonical_path"] = "../outside"
        traversal_entry["entry_id"] = (
            "continuity-entry-"
            + canonical_hash(
                {
                    "canonical_path": "../outside",
                    "present": traversal_entry["present"],
                    "sha256": traversal_entry["sha256"],
                }
            )[:24]
        )
        traversal_entry["storage_path"] = (
            f"files/{traversal_entry['entry_id']}.bin"
            if traversal_entry["present"]
            else None
        )
        rehash_manifest(traversal_manifest)
        write_json(traversal_path, traversal_manifest)
        cases.append(
            (
                "traversal-path-is-rejected-even-after-rehash",
                "PORTABILITY_MANIFEST_ENTRY_PATH_INVALID"
                in service.inspect_bundle(traversal).get("reason_codes", []),
            )
        )

        for label, unsafe_path in (
            ("Windows-drive", "C:/outside"),
            ("UNC", "//server/share/outside"),
        ):
            unsafe = Path(temporary) / f"unsafe-{label}"
            shutil.copytree(destination, unsafe)
            unsafe_manifest_path = unsafe / "continuity-export-manifest.json"
            unsafe_manifest = json.loads(
                unsafe_manifest_path.read_text(encoding="utf-8")
            )
            unsafe_entry = unsafe_manifest["entries"][0]
            unsafe_entry["canonical_path"] = unsafe_path
            unsafe_entry["entry_id"] = (
                "continuity-entry-"
                + canonical_hash(
                    {
                        "canonical_path": unsafe_path,
                        "present": unsafe_entry["present"],
                        "sha256": unsafe_entry["sha256"],
                    }
                )[:24]
            )
            unsafe_entry["storage_path"] = (
                f"files/{unsafe_entry['entry_id']}.bin"
                if unsafe_entry["present"]
                else None
            )
            rehash_manifest(unsafe_manifest)
            write_json(unsafe_manifest_path, unsafe_manifest)
            cases.append(
                (
                    f"{label}-path-is-rejected-even-after-rehash",
                    "PORTABILITY_MANIFEST_ENTRY_PATH_INVALID"
                    in service.inspect_bundle(unsafe).get("reason_codes", []),
                )
            )

        if hasattr(os, "symlink"):
            symlinked = Path(temporary) / "symlinked"
            shutil.copytree(destination, symlinked)
            (symlinked / "linked").symlink_to(
                symlinked / "continuity-export-manifest.json"
            )
            cases.append(
                (
                    "bundle-symlink-is-rejected",
                    service.inspect_bundle(symlinked).get("reason_codes")
                    == ["PORTABILITY_BUNDLE_SYMLINK"],
                )
            )
            root_symlink = Path(temporary) / "bundle-root-link"
            root_redirected = create_directory_redirect(
                root_symlink,
                destination,
            )
            if root_redirected:
                root_symlink_supported = service.inspect_bundle(root_symlink).get(
                    "reason_codes"
                ) == ["PORTABILITY_BUNDLE_ROOT_SYMLINK"]
            else:
                root_symlink_supported = False
            remove_directory_redirect(root_symlink)
            cases.append(
                (
                    "bundle-root-symlink-is-rejected-before-resolve",
                    root_symlink_supported,
                )
            )

        injected = Path(temporary) / "injected"
        shutil.copytree(destination, injected)
        injected_manifest_path = injected / "continuity-export-manifest.json"
        injected_manifest = json.loads(
            injected_manifest_path.read_text(encoding="utf-8")
        )
        injected_payload = b"bundle-controlled content\n"
        injected_digest = hashlib.sha256(injected_payload).hexdigest()
        injected_id = artifact_entry_id(
            "docs/forged-by-bundle.md",
            True,
            injected_digest,
        )
        injected_entry = {
            "entry_id": injected_id,
            "canonical_path": "docs/forged-by-bundle.md",
            "storage_path": f"files/{injected_id}.bin",
            "canonical_owner": "application",
            "restore_mode": "replace",
            "present": True,
            "bytes": len(injected_payload),
            "sha256": injected_digest,
            "privacy_class": "project-internal",
            "retention_class": "advisory",
            "reference_ids": ["forged-self-consistent"],
        }
        injected_manifest["entries"].append(injected_entry)
        (injected / injected_entry["storage_path"]).write_bytes(injected_payload)
        rehash_export_inventory(injected_manifest)
        write_json(injected_manifest_path, injected_manifest)
        injected_result = service.inspect_bundle(injected)
        cases.append(
            (
                "self-consistent-injected-target-is-not-provider-authorized",
                "PORTABILITY_SOURCE_CLOSURE_MISMATCH"
                in injected_result.get("reason_codes", [])
                and not (root.parent / "docs/forged-by-bundle.md").exists(),
            )
        )


SCENARIOS = (
    (
        "export-bundle-adversarial-guards",
        (
            "extra-bundle-file-is-rejected",
            "rehash-cannot-redirect-storage-path",
            "traversal-path-is-rejected-even-after-rehash",
            "Windows-drive-path-is-rejected-even-after-rehash",
            "UNC-path-is-rejected-even-after-rehash",
            "bundle-symlink-is-rejected",
            "bundle-root-symlink-is-rejected-before-resolve",
            "self-consistent-injected-target-is-not-provider-authorized",
        ),
        scenario_export_bundle_adversarial_guards,
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
