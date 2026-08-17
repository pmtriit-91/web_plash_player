#!/usr/bin/env python3
"""Pure stable dependency ordering for continuity restore targets."""

from __future__ import annotations

import heapq
from typing import Any, NoReturn

ORDERING_RELATIONS = frozenset({"requires", "generated-from"})


class DependencyOrderError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


def _fail(reason_code: str, detail: str) -> NoReturn:
    raise DependencyOrderError(reason_code, detail)


def stable_dependency_order(
    references: list[dict[str, Any]], targets: list[dict[str, Any]]
) -> list[str]:
    """Return target entry IDs in deterministic dependency-first order."""
    if not isinstance(references, list) or not isinstance(targets, list):
        _fail("PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID", "inputs must be lists")

    references_by_id: dict[str, dict[str, Any]] = {}
    for reference in references:
        if not isinstance(reference, dict):
            _fail(
                "PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID",
                "reference must be an object",
            )
        reference_id = reference.get("reference_id")
        dependencies = reference.get("dependencies")
        if (
            not isinstance(reference_id, str)
            or not reference_id
            or not isinstance(dependencies, list)
        ):
            _fail(
                "PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID",
                "reference identity or dependencies invalid",
            )
        if reference_id in references_by_id:
            _fail("PORTABILITY_DEPENDENCY_REFERENCE_DUPLICATE", reference_id)
        references_by_id[reference_id] = reference

    reference_successors = {reference_id: set() for reference_id in references_by_id}
    reference_indegree = dict.fromkeys(references_by_id, 0)
    dependency_pairs: set[tuple[str, str]] = set()
    for reference_id, reference in references_by_id.items():
        for dependency in reference["dependencies"]:
            if not isinstance(dependency, dict):
                _fail(
                    "PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID",
                    "dependency must be an object",
                )
            relation = dependency.get("relation")
            target_reference_id = dependency.get("target_reference_id")
            if (
                not isinstance(relation, str)
                or not isinstance(target_reference_id, str)
                or not target_reference_id
            ):
                _fail(
                    "PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID",
                    "dependency fields invalid",
                )
            if target_reference_id not in references_by_id:
                _fail("PORTABILITY_DEPENDENCY_REFERENCE_MISSING", target_reference_id)
            if relation not in ORDERING_RELATIONS:
                continue
            pair = (target_reference_id, reference_id)
            dependency_pairs.add(pair)
            if reference_id not in reference_successors[target_reference_id]:
                reference_successors[target_reference_id].add(reference_id)
                reference_indegree[reference_id] += 1

    ready_references = [
        item for item in reference_indegree if not reference_indegree[item]
    ]
    heapq.heapify(ready_references)
    visited = 0
    while ready_references:
        reference_id = heapq.heappop(ready_references)
        visited += 1
        for successor in sorted(reference_successors[reference_id]):
            reference_indegree[successor] -= 1
            if reference_indegree[successor] == 0:
                heapq.heappush(ready_references, successor)
    if visited != len(references_by_id):
        _fail(
            "PORTABILITY_DEPENDENCY_CYCLE", "ordering dependency graph contains a cycle"
        )

    targets_by_id: dict[str, dict[str, Any]] = {}
    target_for_reference: dict[str, str] = {}
    seen_paths: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            _fail(
                "PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID", "target must be an object"
            )
        entry_id = target.get("entry_id")
        path = target.get("path")
        reference_ids = target.get("reference_ids")
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(path, str)
            or not path
            or not isinstance(reference_ids, list)
        ):
            _fail("PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID", "target fields invalid")
        if entry_id in targets_by_id or path in seen_paths:
            _fail("PORTABILITY_DEPENDENCY_TARGET_AMBIGUOUS", entry_id)
        targets_by_id[entry_id] = target
        seen_paths.add(path)
        for reference_id in reference_ids:
            if not isinstance(reference_id, str) or not reference_id:
                _fail(
                    "PORTABILITY_DEPENDENCY_ORDER_INPUT_INVALID",
                    "target reference invalid",
                )
            if reference_id not in references_by_id:
                _fail("PORTABILITY_DEPENDENCY_TARGET_REFERENCE_MISSING", reference_id)
            previous = target_for_reference.setdefault(reference_id, entry_id)
            if previous != entry_id:
                _fail("PORTABILITY_DEPENDENCY_TARGET_AMBIGUOUS", reference_id)

    successors = {entry_id: set() for entry_id in targets_by_id}
    indegree = dict.fromkeys(targets_by_id, 0)
    for prerequisite_reference, dependent_reference in dependency_pairs:
        prerequisite = target_for_reference.get(prerequisite_reference)
        dependent = target_for_reference.get(dependent_reference)
        if prerequisite is None or dependent is None or prerequisite == dependent:
            continue
        if dependent not in successors[prerequisite]:
            successors[prerequisite].add(dependent)
            indegree[dependent] += 1

    def target_key(entry_id: str) -> tuple[str, str]:
        return targets_by_id[entry_id]["path"], entry_id

    ready_targets = [
        (target_key(item), item) for item in indegree if not indegree[item]
    ]
    heapq.heapify(ready_targets)
    ordered: list[str] = []
    while ready_targets:
        _key, entry_id = heapq.heappop(ready_targets)
        ordered.append(entry_id)
        for successor in sorted(successors[entry_id], key=target_key):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                heapq.heappush(ready_targets, (target_key(successor), successor))
    if len(ordered) != len(targets) or set(ordered) != set(targets_by_id):
        _fail(
            "PORTABILITY_DEPENDENCY_ORDER_INVALID",
            "output is not an exact target permutation",
        )
    return ordered
