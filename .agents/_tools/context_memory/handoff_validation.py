"""Handoff receipt traversal and durability validation for Context Memory."""

from __future__ import annotations

from typing import Any

from context_memory import deep_receipt
from context_memory import evidence as context_evidence


def _engine() -> Any:
    import agent_os_context_memory as engine

    return engine


def validate_handoffs(service: Any) -> dict[str, Any]:
    with context_evidence.deep_batch_reader(service):
        return _validate_handoffs(service)


def validate_for_doctor(service: Any) -> dict[str, Any]:
    """Reuse only a current deep verdict; every cache fault falls back to traversal."""
    before = deep_receipt.current_bindings(service)
    if before is not None:
        cached = deep_receipt.load_cached(service, before, service.now())
        if cached is not None and deep_receipt.current_bindings(service) == before:
            return cached
    result = validate_handoffs(service)
    verdict = {field: result[field] for field in ("errors", "warnings", "summary")}
    after = deep_receipt.current_bindings(service)
    if before is not None and after == before:
        deep_receipt.write_cached(service, before, verdict, service.now())
    return verdict


def _validate_handoffs(service: Any) -> dict[str, Any]:
    engine = _engine()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    valid_receipts: list[dict[str, Any]] = []
    summary = {
        "receipts": 0,
        "legacy_receipts": 0,
        "git_durable_receipts": 0,
        "evidence_references": 0,
        "recoverable_references": 0,
        "legacy_recoverable_references": 0,
        "unrecoverable_references": 0,
    }
    directory = service.path(engine.HANDOFF_DIR_REL)
    if not directory.exists():
        return {
            "errors": errors,
            "warnings": warnings,
            "summary": summary,
            "valid_receipts": valid_receipts,
        }
    if not directory.is_dir() or directory.is_symlink():
        return {
            "errors": [{"code": "HANDOFF_DIRECTORY_INVALID", "path": engine.HANDOFF_DIR_REL}],
            "warnings": warnings,
            "summary": summary,
            "valid_receipts": valid_receipts,
        }
    binding_project_id = service.binding().get("project_id")
    for path in sorted(directory.glob("*.json")):
        summary["receipts"] += 1
        filename_id = path.stem
        safe_detail = (
            {"id": filename_id}
            if engine.HANDOFF_ID.fullmatch(filename_id)
            else {"filename_sha256": engine.sha256_bytes(path.name.encode("utf-8"))}
        )
        if path.is_symlink() or not path.is_file():
            errors.append({"code": "HANDOFF_RECEIPT_PATH_INVALID", **safe_detail})
            continue
        if not engine.HANDOFF_ID.fullmatch(filename_id):
            errors.append({"code": "HANDOFF_RECEIPT_FILENAME_INVALID", **safe_detail})
            continue
        receipt = engine.load_json(path, None)
        if not isinstance(receipt, dict):
            errors.append({"code": "HANDOFF_RECEIPT_INVALID_OR_TAMPERED", **safe_detail})
            continue
        try:
            forbidden = engine.has_forbidden_payload(receipt)
        except RecursionError:
            forbidden = True
        if forbidden:
            errors.append({"code": "HANDOFF_FORBIDDEN_PAYLOAD", **safe_detail})
            continue
        if set(receipt) != engine.HANDOFF_FIELDS:
            errors.append({"code": "HANDOFF_RECEIPT_FIELDS_INVALID", **safe_detail})
            continue
        schema_version = receipt.get("schema_version")
        if type(schema_version) is not int or schema_version not in {1, 2}:
            errors.append({"code": "HANDOFF_SCHEMA_VERSION_UNSUPPORTED", **safe_detail})
            continue
        receipt_id = receipt.get("id")
        if not isinstance(receipt_id, str) or not engine.HANDOFF_ID.fullmatch(receipt_id):
            errors.append({"code": "HANDOFF_ID_INVALID", **safe_detail})
            continue
        if receipt_id != filename_id:
            errors.append({"code": "HANDOFF_FILENAME_ID_MISMATCH", **safe_detail})
            continue
        project_id = receipt.get("project_id")
        if (
            not isinstance(project_id, str)
            or not 1 <= len(project_id) <= 128
            or project_id != binding_project_id
        ):
            errors.append({"code": "HANDOFF_PROJECT_CONTAMINATION", **safe_detail})
            continue
        if not isinstance(receipt.get("task_id"), str) or not engine.SAFE_ID.fullmatch(receipt["task_id"]):
            errors.append({"code": "HANDOFF_TASK_ID_INVALID", **safe_detail})
            continue
        if not isinstance(receipt.get("from_owner"), str) or not 1 <= len(receipt["from_owner"]) <= 128:
            errors.append({"code": "HANDOFF_OWNER_INVALID", **safe_detail})
            continue
        to_owner = receipt.get("to_owner")
        if to_owner is not None and (not isinstance(to_owner, str) or len(to_owner) > 128):
            errors.append({"code": "HANDOFF_OWNER_INVALID", **safe_detail})
            continue
        if not engine.valid_date_time(receipt.get("created_at")):
            errors.append({"code": "HANDOFF_TIMESTAMP_INVALID", **safe_detail})
            continue
        base_commit = receipt.get("base_commit")
        if not isinstance(base_commit, str) or not engine.FULL_COMMIT.fullmatch(base_commit):
            errors.append({"code": "HANDOFF_BASE_COMMIT_INVALID", **safe_detail})
            continue
        if not service.commit_exists(base_commit) or not service.commit_is_ancestor(base_commit):
            errors.append({"code": "HANDOFF_BASE_COMMIT_NOT_REACHABLE", **safe_detail})
            continue
        if not engine.valid_bounded_string_list(receipt.get("verified_outcomes"), 1, 64, 3, 1000):
            errors.append({"code": "HANDOFF_OUTCOMES_INVALID", **safe_detail})
            continue
        if not engine.valid_bounded_string_list(receipt.get("unresolved_risks"), 0, 64, 3, 1000):
            errors.append({"code": "HANDOFF_RISKS_INVALID", **safe_detail})
            continue
        next_action = receipt.get("next_action")
        if not isinstance(next_action, str) or not 3 <= len(next_action) <= 2000:
            errors.append({"code": "HANDOFF_NEXT_ACTION_INVALID", **safe_detail})
            continue
        legacy = schema_version == 1
        evidence = receipt.get("evidence")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 64:
            errors.append({"code": "HANDOFF_EVIDENCE_INVALID", **safe_detail})
            continue
        required_evidence_fields = {"path", "sha256"} if legacy else {"path", "sha256", "git_commit"}
        evidence_structurally_valid = True
        for ref in evidence:
            if not isinstance(ref, dict) or set(ref) != required_evidence_fields:
                evidence_structurally_valid = False
                break
            relative = ref.get("path")
            if not isinstance(relative, str) or not 1 <= len(relative) <= 512:
                evidence_structurally_valid = False
                break
            try:
                engine.safe_join(service.project_root, relative, canonical=True)
            except ValueError:
                evidence_structurally_valid = False
                break
            if not isinstance(ref.get("sha256"), str) or not engine.SHA256.fullmatch(ref["sha256"]):
                evidence_structurally_valid = False
                break
            if not legacy and (
                not isinstance(ref.get("git_commit"), str)
                or not engine.FULL_COMMIT.fullmatch(ref["git_commit"])
            ):
                evidence_structurally_valid = False
                break
        if not evidence_structurally_valid:
            errors.append({"code": "HANDOFF_EVIDENCE_INVALID", **safe_detail})
            continue
        content_sha256 = receipt.get("content_sha256")
        if (
            not isinstance(content_sha256, str)
            or not engine.SHA256.fullmatch(content_sha256)
            or content_sha256 != engine.receipt_hash(receipt)
        ):
            errors.append({"code": "HANDOFF_RECEIPT_INVALID_OR_TAMPERED", **safe_detail})
            continue
        if legacy:
            summary["legacy_receipts"] += 1
        receipt_failed = False
        for ref in evidence:
            summary["evidence_references"] += 1
            if legacy:
                resolved_commit = service.find_reachable_evidence_commit(
                    ref["path"], ref["sha256"], base_commit,
                )
                issues = [] if resolved_commit else [{"code": "CONTEXT_EVIDENCE_NOT_REACHABLE"}]
            else:
                issues = service.validate_git_evidence_ref(ref, require_current=False)
            if not issues:
                summary["recoverable_references"] += 1
                if legacy:
                    summary["legacy_recoverable_references"] += 1
                continue
            summary["unrecoverable_references"] += 1
            receipt_failed = True
            for issue in issues:
                detail = {
                    "id": receipt_id,
                    "path": ref.get("path") if isinstance(ref, dict) else None,
                    "cause": issue.get("code"),
                }
                if legacy:
                    warnings.append({"code": "HISTORICAL_HANDOFF_EVIDENCE_UNRECOVERABLE", **detail})
                else:
                    errors.append({"code": "HANDOFF_EVIDENCE_NOT_GIT_DURABLE", **detail})
        if legacy or not receipt_failed:
            valid_receipts.append(receipt)
        if not legacy and not receipt_failed:
            summary["git_durable_receipts"] += 1
    return {
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "valid_receipts": valid_receipts,
    }
