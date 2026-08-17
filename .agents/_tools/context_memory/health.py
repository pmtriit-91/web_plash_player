"""Context Memory health and bounded-load orchestration boundary."""

from __future__ import annotations

from typing import Any


def _engine() -> Any:
    import agent_os_context_memory as engine

    return engine


def _doctor(service: Any, *, quick: bool) -> dict[str, Any]:
    engine = _engine()
    if not service.path(engine.MANIFEST_REL).is_file():
        return {
            "ok": False,
            "state": "UNCONFIGURED",
            "project_id": service.binding().get("project_id"),
            "reason_codes": ["CONTEXT_MANIFEST_MISSING"],
            "allowed": ["memory initialize plan", "read-only repository evidence"],
        }
    manifest = service.document(engine.MANIFEST_REL, {})
    validation = (
        service.validate_current_authority(manifest)
        if quick and hasattr(service, "validate_current_authority")
        else service.validate_manifest(manifest)
    )
    manifest_fields = manifest if isinstance(manifest, dict) else {}
    errors = validation["errors"]
    stale = validation["stale"]
    conflicts = validation["conflicts"]
    if errors or conflicts:
        state = "DEGRADED"
    elif stale:
        state = "STALE"
    else:
        state = "FRESH"
    return {
        "ok": state == "FRESH",
        "state": state,
        "project_id": manifest_fields.get("project_id"),
        "git_head": service.head(),
        "refreshed_commit": manifest_fields.get("refreshed_commit"),
        "reason_codes": list(dict.fromkeys(item["code"] for item in [*errors, *conflicts, *stale])),
        "errors": errors,
        "conflicts": conflicts,
        "stale": stale,
        "warnings": validation.get("warnings", []),
        "handoff_durability": validation.get("handoff_durability", {}),
        "source_count": len(manifest_fields.get("sources", [])) if isinstance(manifest_fields.get("sources"), list) else 0,
        "task_count": len(validation.get("tasks", {}).get("tasks", [])) if isinstance(validation.get("tasks"), dict) else 0,
        "raw_conversation_stored": False,
        "notebooklm_authority": "cold-research-only",
    }


def doctor(service: Any) -> dict[str, Any]:
    return _doctor(service, quick=False)


def quick_doctor(service: Any) -> dict[str, Any]:
    return _doctor(service, quick=True)


def load(service: Any, tier: str = "hot") -> dict[str, Any]:
    engine = _engine()
    if tier not in engine.TIERS:
        return {"ok": False, "reason_codes": ["CONTEXT_TIER_INVALID"]}
    health = quick_doctor(service)
    if health.get("state") in {"UNCONFIGURED", "DEGRADED"}:
        return {"ok": False, "authoritative": False, "health": health, "records": [], "tasks": []}
    manifest = service.document(engine.MANIFEST_REL, {})
    source = next((item for item in manifest.get("sources", []) if item.get("tier") == tier), None)
    store = service.document(str(source.get("path")), {}) if isinstance(source, dict) else {}
    raw_tasks = service.document(engine.TASKS_REL, {}).get("tasks", []) if tier == "hot" else []
    tasks = [
        task
        for task in raw_tasks
        if isinstance(task, dict) and task.get("status") in engine.ACTIVE_TASK_STATES
    ]
    return {
        "ok": True,
        "tier": tier,
        "authoritative": health.get("state") == "FRESH",
        "freshness_state": health.get("state"),
        "project_id": manifest.get("project_id"),
        "records": store.get("records", []),
        "tasks": tasks,
        "authority_order": manifest.get("authority_order", []),
        "raw_conversation_stored": False,
    }
