#!/usr/bin/env python3
"""Privacy, budget, provider, registry and terminal continuity contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_continuity import CORE_REGISTRY_REL, PROFILE_REGISTRY_REL, sha256_file
from continuity_core.test_baseline_contracts import evaluate_baseline_contracts
from continuity_core.test_dependency_handoff_contracts import (
    evaluate_dependency_handoff_contracts,
)
from continuity_core.test_identity_path_contracts import (
    evaluate_identity_path_contracts,
)
from continuity_core.test_payload_drift_contracts import (
    evaluate_payload_drift_contracts,
)
from continuity_core.test_support import (
    PROJECT_ID,
    commit_all,
    derive,
    has_code,
    reference,
    write_json,
)


def evaluate_privacy_terminal_contracts(
    _baseline: dict[str, Any],
) -> list[tuple[str, bool]]:
    cases: list[tuple[str, bool]] = []

    def forbidden_secret(root: Path, catalog: dict[str, Any]) -> None:
        catalog["token"] = "secret=do-not-store"

    cases.append(
        (
            "C18-forbidden-secret",
            has_code(derive(forbidden_secret), "CONTINUITY_CATALOG_FORBIDDEN_PAYLOAD"),
        )
    )

    def catalog_budget(root: Path, catalog: dict[str, Any]) -> None:
        profile_path = root / PROFILE_REGISTRY_REL
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["profiles"][0]["catalog_max_bytes"] = 4096
        write_json(profile_path, profile)
        catalog["recovery_profile"]["profile_sha256"] = sha256_file(profile_path)

    cases.append(
        (
            "C19-catalog-budget",
            has_code(derive(catalog_budget), "CONTINUITY_CATALOG_BUDGET_EXCEEDED"),
        )
    )

    def projection_budget(root: Path, catalog: dict[str, Any]) -> None:
        profile_path = root / PROFILE_REGISTRY_REL
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["profiles"][0]["projection_max_bytes"] = 512
        write_json(profile_path, profile)
        catalog["recovery_profile"]["profile_sha256"] = sha256_file(profile_path)

    cases.append(
        (
            "C19-projection-budget",
            has_code(
                derive(projection_budget), "CONTINUITY_PROJECTION_BUDGET_EXCEEDED"
            ),
        )
    )

    def materialize_genesis(root: Path, catalog: dict[str, Any]) -> None:
        document = {
            "schema_version": 1,
            "project_id": PROJECT_ID,
            "document_id": "genesis-fixture-project",
            "revision": 1,
        }
        write_json(root / "project/genesis.json", document)
        commit = commit_all(root.parent, "fixture genesis")
        item = reference(catalog, "genesis")
        item["source"]["sha256"] = hashlib.sha256(
            (root / "project/genesis.json").read_bytes()
        ).hexdigest()
        item["source"]["git_commit"] = commit
        item["record_revision"] = 1

    independent = derive(
        materialize_genesis, genesis_state="confirmed", context_state="STALE"
    )
    readiness = {
        item["reference_id"]: item["readiness"]
        for item in independent.get("references", [])
    }
    cases.append(
        (
            "C24-independent-provider-lifecycles",
            readiness.get("genesis") == "available"
            and readiness.get("context") == "stale",
        )
    )
    conflicting = derive(materialize_genesis, genesis_state="conflicting")
    conflicting_readiness = {
        item["reference_id"]: item["readiness"]
        for item in conflicting.get("references", [])
    }
    cases.append(
        (
            "C25-complete-topology-provider-conflicting",
            conflicting.get("topology_state") == "complete"
            and conflicting_readiness.get("genesis") == "conflicting",
        )
    )

    def registry_drift(root: Path, catalog: dict[str, Any]) -> None:
        path = root / CORE_REGISTRY_REL
        document = json.loads(path.read_text(encoding="utf-8"))
        document["registry_version"] = 2
        write_json(path, document)

    cases.append(
        (
            "C27-registry-hash-drift",
            has_code(derive(registry_drift), "CONTINUITY_CORE_REGISTRY_DRIFT"),
        )
    )

    def extension_override(root: Path, catalog: dict[str, Any]) -> None:
        extension = json.loads((root / CORE_REGISTRY_REL).read_text(encoding="utf-8"))
        extension["registry_id"] = f"project.{PROJECT_ID}.types"
        extension["types"] = [deepcopy(extension["types"][4])]
        extension_path = root / "project/context/continuity-record-types.json"
        write_json(extension_path, extension)
        catalog["project_record_type_registry"] = {
            "path": ".agents/project/context/continuity-record-types.json",
            "registry_id": extension["registry_id"],
            "registry_version": extension["registry_version"],
            "registry_sha256": sha256_file(extension_path),
        }

    cases.append(
        (
            "C28-extension-core-override",
            has_code(derive(extension_override), "CONTINUITY_EXTENSION_OVERRIDES_CORE"),
        )
    )

    def duplicate_identity(root: Path, catalog: dict[str, Any]) -> None:
        duplicate = deepcopy(reference(catalog, "roadmap"))
        duplicate["reference_id"] = "roadmap-duplicate-identity"
        catalog["references"].append(duplicate)

    duplicate_identity_result = derive(duplicate_identity)
    cases.append(
        (
            "C29-duplicate-identity-cardinality",
            has_code(duplicate_identity_result, "CONTINUITY_RECORD_IDENTITY_DUPLICATE")
            and has_code(
                duplicate_identity_result, "CONTINUITY_PROFILE_CARDINALITY_EXCEEDED"
            ),
        )
    )

    def invalid_task_ledger(root: Path, catalog: dict[str, Any]) -> None:
        task_path = root / "project/context/active-tasks.json"
        write_json(
            task_path,
            {
                "schema_version": 1,
                "project_id": PROJECT_ID,
                "tasks": [{"id": "bad-task"}],
            },
        )
        commit = commit_all(root.parent, "invalid task ledger fixture")
        task_reference = reference(catalog, "tasks")
        task_reference["source"]["sha256"] = hashlib.sha256(
            task_path.read_bytes()
        ).hexdigest()
        task_reference["source"]["git_commit"] = commit

    cases.append(
        (
            "provider-invalid-task-ledger-fails-closed",
            has_code(derive(invalid_task_ledger), "CONTINUITY_TASK_LEDGER_INVALID"),
        )
    )

    def missing_core_registry(root: Path, catalog: dict[str, Any]) -> None:
        (root / CORE_REGISTRY_REL).unlink()

    cases.append(
        (
            "missing-core-contract-returns-structured-error",
            has_code(
                derive(missing_core_registry), "CONTINUITY_CORE_CONTRACT_UNREADABLE"
            ),
        )
    )
    return cases


def evaluate_all_contracts() -> list[tuple[str, bool]]:
    baseline, cases = evaluate_baseline_contracts()
    cases.extend(evaluate_identity_path_contracts(baseline))
    cases.extend(evaluate_payload_drift_contracts(baseline))
    cases.extend(evaluate_dependency_handoff_contracts(baseline))
    cases.extend(evaluate_privacy_terminal_contracts(baseline))
    return cases


def run_focused() -> None:
    baseline, prerequisite_cases = evaluate_baseline_contracts()
    cases = evaluate_privacy_terminal_contracts(baseline)
    results = [{"id": case_id, "passed": passed} for case_id, passed in cases]
    passed = sum(result["passed"] for result in results)
    prerequisite_ok = all(result for _case_id, result in prerequisite_cases)
    output = {
        "ok": passed == len(results) and prerequisite_ok,
        "passed": passed,
        "total": len(results),
        "prerequisite_ok": prerequisite_ok,
        "cases": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


def run_aggregate() -> None:
    cases = evaluate_all_contracts()
    failed = [case_id for case_id, passed in cases if not passed]
    output = {
        "ok": not failed,
        "executable_cases": len(cases),
        "non_executable_cases": 0,
        "cases": [{"id": case_id, "passed": passed} for case_id, passed in cases],
        "failed": failed,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focused", action="store_true")
    arguments = parser.parse_args()
    if arguments.focused:
        run_focused()
    run_aggregate()


if __name__ == "__main__":
    main()
