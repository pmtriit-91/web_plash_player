#!/usr/bin/env python3
"""Canonical dependency-free lifecycle engine for Universal Agent OS."""

from __future__ import annotations

from lifecycle import update_transaction as update_transaction_owner
from lifecycle.binding_validation import (
    adapter_reason_codes,  # noqa: F401 - public facade re-export
    contains_absolute_or_secret,  # noqa: F401 - public facade re-export
    expected_adapter_digests,  # noqa: F401 - public facade re-export
    normalized_binding_sections,  # noqa: F401 - public facade re-export
    resolve_json_pointer,  # noqa: F401 - public facade re-export
    safe_relative,  # noqa: F401 - public facade re-export
    unique_string_list,  # noqa: F401 - public facade re-export
    valid_timestamp,  # noqa: F401 - public facade re-export
    validate_binding,  # noqa: F401 - public facade re-export
    validate_fingerprint,  # noqa: F401 - public facade re-export
)
from lifecycle.builders import (
    BINDING_PATH,  # noqa: F401 - public facade re-export
    FINGERPRINT_PATH,  # noqa: F401 - public facade re-export
    MANIFEST_PATH,  # noqa: F401 - public facade re-export
    ROOT,
    TEXT_SUFFIXES,  # noqa: F401 - public facade re-export
    VERSION,  # noqa: F401 - public facade re-export
    build_adapter_fingerprint,  # noqa: F401 - public facade re-export
    build_manifest,  # noqa: F401 - public facade re-export
    main,
    purity_scan,  # noqa: F401 - public facade re-export
)
from lifecycle.core_validation import (
    parse_frontmatter,  # noqa: F401 - public facade re-export
    validate_skills,  # noqa: F401 - public facade re-export
    verify_core,
    verify_vendors,  # noqa: F401 - public facade re-export
)
from lifecycle.health import doctor, verify_adapter, verify_bridge  # noqa: F401
from lifecycle.release_tree import (
    FORBIDDEN_UPDATE_SCOPES,  # noqa: F401 - public facade re-export
    FULL_COMMIT,  # noqa: F401 - public facade re-export
    FULL_SHA256,  # noqa: F401 - public facade re-export
    classify,  # noqa: F401 - public facade re-export
    collect_release_entries,  # noqa: F401 - public facade re-export
    collect_release_entries_at_commit,  # noqa: F401 - public facade re-export
    configured_remote_urls,  # noqa: F401 - public facade re-export
    manifest_entries,  # noqa: F401 - public facade re-export
    matches_scope,  # noqa: F401 - public facade re-export
    ownership_policy,  # noqa: F401 - public facade re-export
    symlink_within_release,  # noqa: F401 - public facade re-export
    verified_release_provenance,  # noqa: F401 - public facade re-export
    verify_release_tree,  # noqa: F401 - public facade re-export
)
from lifecycle.shared import (
    canonical_sha256,  # noqa: F401 - public facade re-export
    dump,  # noqa: F401 - public facade re-export
    git_output,  # noqa: F401 - public facade re-export
    load_json,  # noqa: F401 - public facade re-export
    sha256_bytes,  # noqa: F401 - public facade re-export
    sha256_file,  # noqa: F401 - public facade re-export
    utc_now,  # noqa: F401 - public facade re-export
)
from lifecycle.update_planning import (
    PROTECTED_APPLICATION_SCOPES,  # noqa: F401 - public facade re-export
    collect_application_entries,  # noqa: F401 - public facade re-export
    dirty_agent_paths,  # noqa: F401 - public facade re-export
    plan_update,  # noqa: F401 - public facade re-export
)
from lifecycle.update_transaction import (
    UPDATE_RUNTIME_ROOT,  # noqa: F401 - public facade re-export
    apply_update,  # noqa: F401 - public facade re-export
    atomic_json,  # noqa: F401 - public facade re-export
    backup_update_paths,  # noqa: F401 - public facade re-export
    copy_update_path,  # noqa: F401 - public facade re-export
    current_entry_digest,  # noqa: F401 - public facade re-export
    remove_update_path,  # noqa: F401 - public facade re-export
    restore_update_backup,  # noqa: F401 - public facade re-export
    rollback_update,  # noqa: F401 - public facade re-export
    update_relative_path,  # noqa: F401 - public facade re-export
)

PROJECT_ROOT = ROOT.parent
POLICY_PATH = ROOT / "core" / "contracts" / "ownership-policy.json"
PROJECT_MEMORY_PATH = ROOT / "skills" / "project-memory" / "SKILL.md"
ROOT_BRIDGE_PATH = PROJECT_ROOT / "AGENTS.md"


update_transaction_owner.bind_core_verifier(lambda: verify_core())


if __name__ == "__main__":
    main()
