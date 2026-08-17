"""Shared disposable-candidate fixtures for capability research acceptance."""

from __future__ import annotations

import argparse
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = TOOLS_ROOT.parent
CORPUS = AGENT_ROOT / "evals" / "research-adversarial-corpus.json"
FULL_COMMIT = "0123456789abcdef0123456789abcdef01234567"
CANDIDATE_SHARD_SIZE = 10


def namespace(case: dict, source: Path) -> argparse.Namespace:
    return argparse.Namespace(
        source=str(source),
        candidate_id=case["id"],
        connector="local",
        repository=f"https://example.invalid/{case['id']}",
        commit=case.get("commit", FULL_COMMIT),
        license=case.get("license", ""),
        positive=case.get("positive", [f"Use {case['id']} for its intended purpose"]),
        negative=case.get("negative", ["Prepare vegetable soup for dinner"]),
        discovered_at="2026-07-19T00:00:00Z",
    )


def materialize(case: dict, source: Path) -> None:
    for relative, content in case.get("files", {}).items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for relative, target in case.get("symlinks", {}).items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
