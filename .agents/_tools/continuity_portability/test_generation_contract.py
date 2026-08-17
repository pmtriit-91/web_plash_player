#!/usr/bin/env python3
"""Focused P2a2a checks for the generation-2 catalog contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "core/contracts/continuity-catalog.schema.json"
TEMPLATE_PATH = ROOT / "project-template/context/continuity.json"
REGISTRY_PATH = ROOT / "memory/continuity-record-types.json"
PROFILE_PATH = ROOT / "memory/continuity-recovery-profiles.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    definitions = schema["$defs"]
    extension_property = schema["properties"]["migration_extensions"]
    extension = definitions["migrationExtension"]
    extension_fields = extension["properties"]["fields"]
    extension_value = definitions["migrationExtensionValue"]["oneOf"]
    scalar = definitions["migrationExtensionScalar"]["oneOf"]
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    check(
        "catalog-contract-is-explicit-generation-two",
        schema["$schema"].endswith("draft/2020-12/schema")
        and schema["properties"]["schema_version"] == {"const": 2},
    )
    check(
        "migration-extension-remains-optional-non-authority",
        "migration_extensions" not in schema["required"]
        and schema["additionalProperties"] is False,
    )
    check(
        "migration-envelope-count-matches-hop-cap",
        extension_property
        == {
            "type": "array",
            "maxItems": 8,
            "uniqueItems": True,
            "items": {"$ref": "#/$defs/migrationExtension"},
        },
    )
    check(
        "migration-envelope-is-strict-and-carries-hash-evidence",
        extension["additionalProperties"] is False
        and set(extension["required"])
        == {
            "source_generation",
            "migration_id",
            "unknown_fields_sha256",
            "fields",
        }
        and extension["properties"]["unknown_fields_sha256"]
        == {"$ref": "#/$defs/sha256"}
        and extension["properties"]["source_generation"]["maximum"] == 1,
    )
    check(
        "unknown-field-map-is-key-and-count-bounded",
        extension_fields["type"] == "object"
        and extension_fields["maxProperties"] == 32
        and extension_fields["propertyNames"]["pattern"] == "^[a-z][a-z0-9._-]{1,127}$"
        and extension_fields["additionalProperties"]
        == {"$ref": "#/$defs/migrationExtensionValue"},
    )
    check(
        "unknown-values-are-shallow-bounded-metadata",
        scalar[0] == {"type": "string", "maxLength": 4096}
        and scalar[1]["minimum"] == -1000000000000
        and scalar[1]["maximum"] == 1000000000000
        and extension_value[1]["maxItems"] == 32
        and extension_value[2]["maxProperties"] == 32
        and extension_value[1]["items"] == {"$ref": "#/$defs/migrationExtensionScalar"}
        and extension_value[2]["additionalProperties"]
        == {"$ref": "#/$defs/migrationExtensionScalar"},
    )
    check(
        "project-template-selects-generation-two-with-empty-envelope",
        template["schema_version"] == 2
        and template["migration_extensions"] == []
        and set(template) <= set(schema["properties"]),
    )
    check(
        "project-template-retains-core-contract-hashes",
        template["record_type_registry"]["registry_sha256"]
        == sha256_file(REGISTRY_PATH)
        and template["recovery_profile"]["profile_sha256"] == sha256_file(PROFILE_PATH),
    )

    passed = sum(1 for item in cases if item["passed"])
    output = {"ok": passed == len(cases), "passed": passed, "total": len(cases)}
    output["results"] = cases
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
