#!/usr/bin/env python3
"""Focused portable lexical, traversal, character and collision policy checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_paths import portable_collision_key, portable_relative


def accepted(value: str, expected: str, canonical: bool = False) -> bool:
    try:
        return portable_relative(value, canonical=canonical) == expected
    except ValueError:
        return False


def rejected(value: str, canonical: bool = False) -> bool:
    try:
        portable_relative(value, canonical=canonical)
    except ValueError:
        return True
    return False


def evaluate_portable_lexical_policy() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    results.append(
        {
            "id": "posix-relative",
            "passed": accepted(
                "core/contracts/policy.json", "core/contracts/policy.json", True
            ),
        }
    )
    results.append(
        {
            "id": "windows-separators-normalized-for-input",
            "passed": accepted("docs\\guide.md", "docs/guide.md"),
        }
    )
    results.append(
        {
            "id": "manifest-backslashes-rejected",
            "passed": rejected("core\\policy.json", True),
        }
    )
    blocked = [
        "../escape",
        "a/../../escape",
        "/absolute/path",
        "~/home/path",
        "C:\\Windows\\system32",
        "D:/secrets.txt",
        "\\\\server\\share\\file",
        "./ambiguous",
        "a/./ambiguous",
        "bad\x00path",
    ]
    results.append(
        {
            "id": "cross-platform-absolute-and-traversal-blocked",
            "passed": all(rejected(item) for item in blocked),
        }
    )
    reserved = [
        "CON",
        "docs/nul.txt",
        "AUX.tar.gz",
        "devices/COM1",
        "devices/com9.log",
        "devices/LPT¹.txt",
        "devices/CON .txt",
    ]
    results.append(
        {
            "id": "windows-reserved-device-names-blocked",
            "passed": all(rejected(item, True) for item in reserved),
        }
    )
    invalid = [
        "docs/name<copy>.md",
        'docs/name".md',
        "docs/name:stream",
        "docs/name|pipe.md",
        "docs/name?.md",
        "docs/name*.md",
        "docs/control\x1f.md",
    ]
    results.append(
        {
            "id": "windows-invalid-and-control-characters-blocked",
            "passed": all(rejected(item, True) for item in invalid),
        }
    )
    boundary = [
        "docs/name.",
        "docs/name ",
        " docs/name",
        "docs/ name",
        "folder./name",
        "folder /name",
    ]
    results.append(
        {
            "id": "windows-boundary-dot-and-space-blocked",
            "passed": all(rejected(item, True) for item in boundary),
        }
    )
    results.append(
        {
            "id": "portable-components-and-distinct-keys-preserved",
            "passed": (
                accepted(".agents/docs/My Guide.md", ".agents/docs/My Guide.md", True)
                and portable_collision_key("docs/alpha.md", canonical=True)
                != portable_collision_key("docs/beta.md", canonical=True)
            ),
        }
    )
    results.append(
        {
            "id": "windows-case-only-collision-key",
            "passed": portable_collision_key("Docs/Guide.md", canonical=True)
            == portable_collision_key("docs/guide.MD", canonical=True),
        }
    )
    results.append(
        {
            "id": "unicode-nfc-nfd-collision-key",
            "passed": portable_collision_key("docs/café.md", canonical=True)
            == portable_collision_key("docs/cafe\u0301.md", canonical=True),
        }
    )
    return results


def main() -> None:
    results = evaluate_portable_lexical_policy()
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
