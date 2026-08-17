"""Core, vendor, and skill validation contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lifecycle.release_tree import ROOT, collect_release_entries, manifest_entries
from lifecycle.shared import FULL_COMMIT, FULL_SHA256, load_json, sha256_file

VERSION = "9.1.0"
MANIFEST_PATH = ROOT / "_manifest" / "base-release-manifest.json"
VENDOR_LOCK_PATH = ROOT / "vendor" / "vendor-lock.json"
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# fmt: off
def verify_vendors() -> dict[str, Any]:
    lock = load_json(VENDOR_LOCK_PATH, {})
    errors: list[dict[str, Any]] = []
    verified = 0
    validated_research_records = 0
    packages = lock.get("packages", []) if isinstance(lock, dict) else []
    if not isinstance(packages, list):
        packages = []
    if not packages:
        errors.append({"code": "VENDOR_LOCK_EMPTY"})

    for package in packages:
        package_id = package.get("id", "unknown") if isinstance(package, dict) else "unknown"
        package_root = package.get("root") if isinstance(package, dict) else None
        commit = package.get("commit") if isinstance(package, dict) else None
        license_id = package.get("license") if isinstance(package, dict) else None
        license_path = package.get("license_path") if isinstance(package, dict) else None
        files = package.get("files", {}) if isinstance(package, dict) else {}
        if not isinstance(package_root, str) or not package_root.startswith("vendor/") or ".." in Path(package_root).parts:
            errors.append({"code": "VENDOR_ROOT_INVALID", "package": package_id})
            package_root = None
        if not isinstance(commit, str) or not FULL_COMMIT.fullmatch(commit):
            errors.append({"code": "VENDOR_COMMIT_INVALID", "package": package_id})
        if not isinstance(license_id, str) or not license_id:
            errors.append({"code": "VENDOR_LICENSE_MISSING", "package": package_id})
        if not isinstance(files, dict) or not files:
            errors.append({"code": "VENDOR_FILE_ALLOWLIST_EMPTY", "package": package_id})
            continue
        if not isinstance(license_path, str) or license_path not in files:
            errors.append({"code": "VENDOR_LICENSE_NOT_ALLOWLISTED", "package": package_id})
        allowlisted = {str(relative) for relative in files}
        if package_root:
            root_path = ROOT / package_root
            if not root_path.is_dir():
                errors.append({"code": "VENDOR_ROOT_MISSING", "package": package_id, "path": package_root})
            else:
                actual = {
                    path.relative_to(ROOT).as_posix()
                    for path in root_path.rglob("*")
                    if path.is_file() or path.is_symlink()
                }
                for relative in sorted(actual - allowlisted):
                    errors.append({"code": "VENDOR_FILE_NOT_ALLOWLISTED", "package": package_id, "path": relative})
        for relative, expected in files.items():
            path = ROOT / str(relative)
            if not path.is_file():
                errors.append({"code": "VENDOR_FILE_MISSING", "package": package_id, "path": relative})
                continue
            if path.is_symlink():
                errors.append({"code": "VENDOR_SYMLINK_FORBIDDEN", "package": package_id, "path": relative})
                continue
            actual = sha256_file(path)
            if actual != expected:
                errors.append(
                    {
                        "code": "VENDOR_FILE_CHANGED",
                        "package": package_id,
                        "path": relative,
                        "expected": expected,
                        "actual": actual,
                    }
                )
                continue
            verified += 1

    research_sources = lock.get("research_sources", []) if isinstance(lock, dict) else []
    if not isinstance(research_sources, list):
        errors.append({"code": "RESEARCH_SOURCES_INVALID"})
        research_sources = []
    allowed_integrations = {"adapt-local-skill", "adapt-local-principles", "research-only"}
    for source in research_sources:
        error_count_before = len(errors)
        source_id = source.get("id", "unknown") if isinstance(source, dict) else "unknown"
        repository = source.get("repository") if isinstance(source, dict) else None
        commit = source.get("commit") if isinstance(source, dict) else None
        license_id = source.get("license") if isinstance(source, dict) else None
        integration = source.get("integration") if isinstance(source, dict) else None
        files_inspected = source.get("files_inspected", {}) if isinstance(source, dict) else {}
        local_influence = source.get("local_influence", []) if isinstance(source, dict) else []
        if not isinstance(repository, str) or not repository.startswith("https://github.com/"):
            errors.append({"code": "RESEARCH_REPOSITORY_INVALID", "source": source_id})
        if not isinstance(commit, str) or not FULL_COMMIT.fullmatch(commit):
            errors.append({"code": "RESEARCH_COMMIT_INVALID", "source": source_id})
        if not isinstance(license_id, str) or not license_id:
            errors.append({"code": "RESEARCH_LICENSE_MISSING", "source": source_id})
        if integration not in allowed_integrations:
            errors.append({"code": "RESEARCH_INTEGRATION_INVALID", "source": source_id})
        if not isinstance(files_inspected, dict) or not files_inspected:
            errors.append({"code": "RESEARCH_INSPECTION_EMPTY", "source": source_id})
        else:
            for upstream_path, digest in files_inspected.items():
                if not isinstance(upstream_path, str) or not upstream_path or not isinstance(digest, str) or not FULL_SHA256.fullmatch(digest):
                    errors.append({"code": "RESEARCH_INSPECTION_INVALID", "source": source_id, "path": upstream_path})
        if not isinstance(local_influence, list) or not local_influence:
            errors.append({"code": "RESEARCH_LOCAL_INFLUENCE_EMPTY", "source": source_id})
        else:
            for relative in local_influence:
                if not isinstance(relative, str) or ".." in Path(relative).parts or not (ROOT / relative).is_file():
                    errors.append({"code": "RESEARCH_LOCAL_INFLUENCE_MISSING", "source": source_id, "path": relative})
        if len(errors) == error_count_before:
            validated_research_records += 1
    return {
        "ok": not errors,
        "verified_files": verified,
        "validated_research_records": validated_research_records,
        "errors": errors,
    }


def parse_frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [f"SKILL_UNREADABLE:{path}:{exc}"]
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return {}, [f"SKILL_FRONTMATTER_MISSING:{path}"]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, [f"SKILL_FRONTMATTER_UNCLOSED:{path}"]
    metadata: dict[str, str] = {}
    current_key: str | None = None
    for line in lines[1:end]:
        if line.startswith((" ", "\t")):
            if current_key == "description":
                metadata[current_key] = (metadata.get(current_key, "") + " " + line.strip()).strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        metadata[current_key] = value.strip().strip("'\"")
    return metadata, []


def validate_skills() -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    checked = 0
    roots = [ROOT / "skills", ROOT / "vendor"]
    for skill_file in sorted(path for base in roots for path in base.rglob("SKILL.md")):
        relative = skill_file.relative_to(ROOT).as_posix()
        if relative.startswith("skills/project-memory/") or relative.startswith("skills/project-local/"):
            continue
        metadata, parse_errors = parse_frontmatter(skill_file)
        if parse_errors:
            errors.extend({"code": item, "path": relative} for item in parse_errors)
            continue
        name = metadata.get("name", "")
        description = metadata.get("description", "")
        line_count = len(skill_file.read_text(encoding="utf-8").splitlines())
        if not SKILL_NAME.fullmatch(name):
            errors.append({"code": "SKILL_NAME_INVALID", "path": relative, "name": name})
        if not description:
            errors.append({"code": "SKILL_DESCRIPTION_MISSING", "path": relative})
        if line_count > 500:
            errors.append({"code": "SKILL_TOO_LARGE", "path": relative, "lines": line_count})
        checked += 1
    return {"ok": not errors, "checked": checked, "errors": errors}


def verify_core() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH, {})
    if not isinstance(manifest, dict) or not manifest:
        return {
            "ok": False,
            "reason_codes": ["CORE_MANIFEST_MISSING"],
            "manifest": MANIFEST_PATH.relative_to(ROOT).as_posix(),
        }
    expected, schema_errors = manifest_entries(manifest)
    current, unclassified = collect_release_entries()
    missing = sorted(set(expected) - set(current))
    extra = sorted(set(current) - set(expected))
    changed = sorted(
        path
        for path in set(expected) & set(current)
        if expected[path].get("type") != current[path].get("type")
        or expected[path].get("sha256") != current[path].get("sha256")
        or expected[path].get("target") != current[path].get("target")
    )
    unsafe_symlinks = sorted(
        path
        for path, entry in current.items()
        if entry.get("type") == "symlink" and entry.get("target_within_release") is not True
    )
    reasons: list[str] = []
    if schema_errors:
        reasons.append("CORE_MANIFEST_SCHEMA_INVALID")
    if unclassified:
        reasons.append("UNCLASSIFIED_STABLE_PATH")
    if missing or extra or changed:
        reasons.append("CORE_MANIFEST_MISMATCH")
    if unsafe_symlinks:
        reasons.append("CORE_SYMLINK_OUTSIDE_RELEASE")
    if manifest.get("agent_os_version") != VERSION:
        reasons.append("CORE_VERSION_MISMATCH")
    vendors = verify_vendors()
    skills = validate_skills()
    if not vendors["ok"]:
        reasons.append("VENDOR_LOCK_MISMATCH")
    if not skills["ok"]:
        reasons.append("SKILL_VALIDATION_FAILED")
    return {
        "ok": not reasons,
        "agent_os_version": VERSION,
        "manifest_release_id": manifest.get("release_id"),
        "manifest_entries": len(expected),
        "current_entries": len(current),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "unsafe_symlinks": unsafe_symlinks,
        "unclassified": unclassified,
        "schema_errors": schema_errors,
        "vendor_integrity": vendors,
        "skill_validation": skills,
        "reason_codes": list(dict.fromkeys(reasons)),
    }
# fmt: on
