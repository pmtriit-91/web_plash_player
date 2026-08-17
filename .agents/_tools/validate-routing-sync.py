#!/usr/bin/env python3
"""Validate Agent OS routing, lifecycle paths, skills, vendors, and integrity."""

from __future__ import annotations

import argparse
import json
import sys

from agent_os_lifecycle import validate_skills, verify_core, verify_vendors
from preflight import validate_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Agent OS routing sync")
    parser.add_argument("--skip-manifest", action="store_true")
    args = parser.parse_args()

    checks = {
        "routing_and_paths": validate_paths(),
        "vendor_integrity": verify_vendors(),
        "skills": validate_skills(),
    }
    if not args.skip_manifest:
        checks["core_integrity"] = verify_core()
    errors = [name for name, result in checks.items() if not result.get("ok")]
    output = {"ok": not errors, "version": "9.1.0", "checks": checks, "errors": errors}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
