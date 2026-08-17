#!/usr/bin/env python3
"""Focused filesystem containment and vendor checkout portability checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_paths import safe_join


def evaluate_filesystem_checkout() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-portable-path-") as temporary:
        root = Path(temporary)
        inside = safe_join(root, "nested/file.txt")
        inside.parent.mkdir(parents=True)
        inside.write_text("fixture\n", encoding="utf-8")
        results.append(
            {
                "id": "safe-join-contained",
                "passed": inside.resolve().is_relative_to(root.resolve()),
            }
        )
    with tempfile.TemporaryDirectory(prefix="agent-os-vendor-bytes-") as temporary:
        root = Path(temporary)
        vendor = root / ".agents" / "vendor" / "fixture" / "SKILL.md"
        vendor.parent.mkdir(parents=True)
        attributes = (ROOT / ".gitattributes").read_bytes()
        (root / ".agents" / ".gitattributes").write_bytes(attributes)
        vendor.write_bytes(b"line one\nline two\n")
        expected = hashlib.sha256(vendor.read_bytes()).hexdigest()
        commands = (
            ["git", "init", "-q"],
            ["git", "config", "user.name", "Agent OS Test"],
            ["git", "config", "user.email", "agent-os@example.invalid"],
            ["git", "add", ".agents/.gitattributes", ".agents/vendor/fixture/SKILL.md"],
            ["git", "commit", "-qm", "vendor bytes fixture"],
        )
        setup_ok = all(
            subprocess.run(
                command, cwd=root, capture_output=True, check=False
            ).returncode
            == 0
            for command in commands
        )
        vendor.unlink()
        checkout = subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "checkout",
                "--",
                ".agents/vendor/fixture/SKILL.md",
            ],
            cwd=root,
            capture_output=True,
            check=False,
        )
        actual = (
            hashlib.sha256(vendor.read_bytes()).hexdigest() if vendor.exists() else ""
        )
        results.append(
            {
                "id": "vendor-bytes-survive-windows-checkout",
                "passed": setup_ok and checkout.returncode == 0 and actual == expected,
            }
        )
    return results


def main() -> None:
    results = evaluate_filesystem_checkout()
    passed = sum(1 for result in results if result["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
