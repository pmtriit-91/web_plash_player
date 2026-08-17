#!/usr/bin/env python3
"""AOS-15 W5 test shard: cli-integration."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from agent_os_cli import JSON_INPUT_MAX_BYTES, read_json_input
from continuity_portability.test_support import (
    export_bundle,
    prepare_fixture,
    run_cli,
)

SHARD_ID = "cli-integration"
GROUPS = ("cli-integration",)
TIMEOUT_SECONDS = 120


def scenario_cli_json_ingress(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-cli-json-") as temporary:
        json_source = Path(temporary) / "input.json"
        json_source.write_bytes(b'{"bounded":true}')
        oversized_source = Path(temporary) / "oversized.json"
        oversized_source.write_bytes(b"x" * (JSON_INPUT_MAX_BYTES + 1))
        with patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("unbounded CLI Path.read_bytes() used"),
        ):
            json_input, json_error = read_json_input(str(json_source))
            oversized_input, oversized_error = read_json_input(str(oversized_source))
        cases.append(
            (
                "CLI-JSON-ingress-is-descriptor-bounded",
                json_input == {"bounded": True}
                and json_error is None
                and oversized_input is None
                and oversized_error == "input exceeds 1048576-byte limit",
            )
        )


def scenario_cli_bundle_inspection(cases: list[tuple[str, bool]]) -> None:
    with tempfile.TemporaryDirectory(prefix="aos15-w5-cli-inspection-") as temporary:
        root = prepare_fixture(Path(temporary), payload_mode="portable-bytes")
        destination = Path(temporary) / "bundle"
        service, _applied = export_bundle(root, destination)
        inspected = service.inspect_bundle(destination)
        cli_inspection = run_cli(
            ["continuity", "inspect-bundle", "--source", str(destination)],
            root.parent,
        )
        cases.append(
            (
                "CLI-inspection-delegates-to-canonical-portability-service",
                cli_inspection.get("ok") is True
                and cli_inspection.get("manifest", {}).get("bundle_id")
                == inspected["manifest"]["bundle_id"],
            )
        )


SCENARIOS = (
    (
        "cli-json-ingress",
        ("CLI-JSON-ingress-is-descriptor-bounded",),
        scenario_cli_json_ingress,
    ),
    (
        "cli-bundle-inspection",
        ("CLI-inspection-delegates-to-canonical-portability-service",),
        scenario_cli_bundle_inspection,
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
