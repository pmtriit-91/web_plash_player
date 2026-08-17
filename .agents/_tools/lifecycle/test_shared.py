#!/usr/bin/env python3
"""Nine focused checks for lifecycle shared-foundation extraction."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib
import inspect
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
facade = importlib.import_module("agent_os_lifecycle")
shared = importlib.import_module("lifecycle.shared")
NAMES = (
    "load_json",
    "dump",
    "sha256_bytes",
    "sha256_file",
    "canonical_sha256",
    "utc_now",
    "git_output",
)
ORDERED_AST_SHA256 = "75becddc647fbbd027964f87b47fcc5581f069aca09322654d667640fdccfa42"


def main() -> None:
    cases: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool) -> None:
        cases.append({"id": identifier, "passed": passed})

    source = (TOOLS_ROOT / "lifecycle/shared.py").read_text(encoding="utf-8")
    nodes = {
        node.name: node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
    }
    ordered = "\n".join(
        ast.dump(nodes[name], include_attributes=False) for name in NAMES
    )
    check(
        "ordered-helper-ast-is-preserved",
        hashlib.sha256(ordered.encode()).hexdigest() == ORDERED_AST_SHA256,
    )
    check(
        "facade-reexports-exact-identities",
        all(getattr(facade, name) is getattr(shared, name) for name in NAMES),
    )
    check(
        "signatures-remain-publicly-identical",
        str(inspect.signature(shared.load_json))
        == "(path: 'Path', default: 'Any' = None) -> 'Any'"
        and str(inspect.signature(shared.git_output))
        == "(*args: 'str') -> 'str | None'",
    )
    narrow_buffer = io.BytesIO()
    narrow_stdout = io.TextIOWrapper(narrow_buffer, encoding="cp1252", errors="strict")
    narrow_payload = {"project_truth": "continuity → tiếng Việt"}
    try:
        with contextlib.redirect_stdout(narrow_stdout):
            shared.dump(narrow_payload)
        narrow_stdout.flush()
        narrow_round_trip = json.loads(narrow_buffer.getvalue().decode("cp1252"))
    except (UnicodeEncodeError, json.JSONDecodeError):
        narrow_round_trip = None
    check("dump-is-portable-through-narrow-stdout", narrow_round_trip == narrow_payload)
    with tempfile.TemporaryDirectory(prefix="lifecycle-shared-") as temporary:
        path = Path(temporary) / "value.json"
        path.write_text('{"x":1}', encoding="utf-8")
        check(
            "json-load-and-fallback-parity",
            shared.load_json(path) == {"x": 1}
            and shared.load_json(path.with_name("missing"), 7) == 7,
        )
        check(
            "byte-file-and-canonical-hashes-agree",
            shared.sha256_bytes(path.read_bytes()) == shared.sha256_file(path)
            and len(shared.canonical_sha256({"x": 1})) == 64,
        )
    check(
        "utc-and-git-primitives-remain-live",
        re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", shared.utc_now())
        is not None
        and shared.git_output("rev-parse", "--show-toplevel")
        == str(shared.PROJECT_ROOT),
    )
    index = json.loads((TOOLS_ROOT / "module-topology-index.json").read_text())
    topology = json.loads((TOOLS_ROOT / "lifecycle/topology.json").read_text())
    domains = {item["domain"]: item for item in index["domains"]}
    entries = {item["entrypoint"]: item for item in topology["entries"]}
    shared_path = "_tools/lifecycle/shared.py"
    check(
        "topology-routes-lifecycle-foundation",
        domains["lifecycle"]["topology"] == "_tools/lifecycle/topology.json"
        and entries[shared_path]["focused_shard"] == "_tools/lifecycle/test_shared.py",
    )
    check(
        "shared-owner-has-no-reverse-import",
        "import agent_os_lifecycle" not in source
        and "from agent_os_lifecycle" not in source,
    )
    result = {
        "ok": all(item["passed"] for item in cases),
        "passed": sum(item["passed"] for item in cases),
        "total": len(cases),
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
