#!/usr/bin/env python3
"""Pure bounded path selection for registered continuity migrations."""

from __future__ import annotations

from typing import Any, NoReturn

MAX_MIGRATIONS = 64
MAX_MIGRATION_HOPS = 8


class MigrationChainError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


def _fail(reason_code: str, detail: str) -> NoReturn:
    raise MigrationChainError(reason_code, detail)


def resolve_migration_chain(
    migrations: list[dict[str, Any]],
    source_generation: int,
    target_generation: int,
    *,
    max_hops: int = MAX_MIGRATION_HOPS,
) -> list[dict[str, Any]]:
    """Return the unique registered source-to-target path in stable hop order."""
    if (
        not isinstance(migrations, list)
        or len(migrations) > MAX_MIGRATIONS
        or type(source_generation) is not int
        or type(target_generation) is not int
        or source_generation < 0
        or target_generation < source_generation
        or type(max_hops) is not int
        or not 1 <= max_hops <= MAX_MIGRATION_HOPS
    ):
        _fail("CONTINUITY_MIGRATION_CHAIN_INPUT_INVALID", "invalid path request")

    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    graph: dict[int, list[int]] = {}
    for entry in migrations:
        if not isinstance(entry, dict):
            _fail("CONTINUITY_MIGRATION_CHAIN_ENTRY_INVALID", "entry is not an object")
        identifier = entry.get("migration_id")
        provider = entry.get("provider")
        source = entry.get("source_generation")
        target = entry.get("target_generation")
        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 128
            or not isinstance(provider, str)
            or not provider
            or len(provider) > 256
            or type(source) is not int
            or type(target) is not int
            or source < 0
            or target < 0
        ):
            _fail("CONTINUITY_MIGRATION_CHAIN_ENTRY_INVALID", "entry fields invalid")
        if identifier in identifiers:
            _fail("CONTINUITY_MIGRATION_CHAIN_ID_DUPLICATE", identifier)
        identifiers.add(identifier)
        normalized.append(dict(entry))
        graph.setdefault(source, []).append(target)
        graph.setdefault(target, [])

    state: dict[int, int] = {}

    def visit(generation: int) -> None:
        if state.get(generation) == 1:
            _fail("CONTINUITY_MIGRATION_CHAIN_CYCLE", str(generation))
        if state.get(generation) == 2:
            return
        state[generation] = 1
        for successor in graph.get(generation, []):
            visit(successor)
        state[generation] = 2

    for generation in sorted(graph):
        visit(generation)
    if any(
        item["target_generation"] <= item["source_generation"] for item in normalized
    ):
        _fail(
            "CONTINUITY_MIGRATION_CHAIN_NON_MONOTONIC",
            "target generation must increase",
        )
    if source_generation == target_generation:
        return []

    by_source: dict[int, list[dict[str, Any]]] = {}
    for entry in normalized:
        by_source.setdefault(entry["source_generation"], []).append(entry)
    for entries in by_source.values():
        entries.sort(
            key=lambda item: (
                item["target_generation"],
                item["migration_id"],
                item["provider"],
            )
        )

    path_counts = {target_generation: 1}
    unique_paths: dict[int, list[dict[str, Any]]] = {target_generation: []}
    generations = sorted(
        {
            source_generation,
            target_generation,
            *(item["source_generation"] for item in normalized),
            *(item["target_generation"] for item in normalized),
        },
        reverse=True,
    )
    for generation in generations:
        if generation == target_generation:
            continue
        count = 0
        selected: list[dict[str, Any]] | None = None
        for entry in by_source.get(generation, []):
            successor = entry["target_generation"]
            successor_count = path_counts.get(successor, 0)
            if successor_count == 0:
                continue
            count = min(2, count + successor_count)
            selected = (
                [entry, *unique_paths[successor]]
                if count == 1 and successor_count == 1
                else None
            )
        path_counts[generation] = count
        if selected is not None:
            unique_paths[generation] = selected

    path_count = path_counts.get(source_generation, 0)
    if path_count == 0:
        _fail("CONTINUITY_MIGRATION_CHAIN_NOT_FOUND", "no registered path")
    if path_count != 1:
        _fail("CONTINUITY_MIGRATION_CHAIN_AMBIGUOUS", "multiple registered paths")
    path = unique_paths[source_generation]
    if len(path) > max_hops:
        _fail("CONTINUITY_MIGRATION_CHAIN_TOO_LONG", str(len(path)))
    return path
