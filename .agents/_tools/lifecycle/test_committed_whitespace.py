#!/usr/bin/env python3
"""Regression fixture for committed-range whitespace assurance."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

AGENTS_ROOT = Path(__file__).resolve().parents[2]
CHECKER = AGENTS_ROOT / "_tools" / "check-committed-whitespace.py"
WORKFLOW = AGENTS_ROOT.parent / ".github" / "workflows" / "agent-os-ci.yml"
UPLOAD_ARTIFACT_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"


def workflow_step(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    end = workflow.find("\n      - ", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start:end]


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=30, check=False
    )


def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *arguments], repository)


def commit(repository: Path, message: str) -> str:
    added = git(repository, "add", ".")
    created = git(repository, "commit", "-m", message)
    head = git(repository, "rev-parse", "HEAD")
    if added.returncode != 0 or created.returncode != 0 or head.returncode != 0:
        raise RuntimeError(added.stderr or created.stderr or head.stderr)
    return head.stdout.strip()


def check(
    repository: Path, base: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(CHECKER), "--repository", str(repository)]
    if base is not None:
        command.extend(["--base", base])
    return run(command, repository)


def main() -> None:
    results: list[dict[str, object]] = []
    workflow = WORKFLOW.read_text(encoding="utf-8")
    trigger = workflow.split("\npermissions:", 1)[0]
    eval_step = workflow_step(workflow, "Run bounded behavioral evals")
    portability_step = workflow_step(workflow, "Run offline portability shards")
    metadata_step = workflow_step(workflow, "Bind compact summary metadata")
    publish_step = workflow_step(workflow, "Publish compact job summary")
    upload_step = workflow_step(workflow, "Upload compact summaries")
    results.extend(
        [
            {
                "id": "hosted-ci-is-manual-dispatch-only",
                "passed": (
                    "\n  workflow_dispatch:" in trigger
                    and "\n  push:" not in trigger
                    and "\n  pull_request:" not in trigger
                ),
            },
            {
                "id": "manual-dispatch-requires-explicit-range-base",
                "passed": (
                    "base_commit:" in trigger
                    and "required: true" in trigger
                    and '--base "${{ inputs.base_commit }}"' in workflow
                ),
            },
            {
                "id": "hosted-evals-isolate-offline-portability",
                "passed": (
                    "timeout-minutes: ${{ matrix.timeout_minutes }}" in workflow
                    and "- os: ubuntu-latest\n            timeout_minutes: 20"
                    in workflow
                    and "- os: macos-latest\n            timeout_minutes: 20"
                    in workflow
                    and "- os: windows-latest\n            timeout_minutes: 45"
                    in workflow
                    and "--exclude-case-id continuity-offline-portability" in workflow
                    and "python .agents/_tools/test-continuity-portability.py"
                    in workflow
                    and workflow.index(
                        "--exclude-case-id continuity-offline-portability"
                    )
                    < workflow.index(
                        "python .agents/_tools/test-continuity-portability.py"
                    )
                ),
            },
            {
                "id": "workflow-binds-range-base-and-exact-workflow-digest",
                "passed": (
                    'AGENT_OS_RANGE_BASE: "${{ inputs.base_commit }}"' in workflow
                    and "shell: python" in metadata_step
                    and "subprocess.check_output" in metadata_step
                    and 'git", "show' in metadata_step
                    and "GITHUB_SHA" in metadata_step
                    and "hashlib.sha256(blob).hexdigest()" in metadata_step
                    and "AGENT_OS_WORKFLOW_SHA256={digest}" in metadata_step
                ),
            },
            {
                "id": "eval-and-portability-steps-emit-release-summary-pairs",
                "passed": (
                    "--summary-json agent-os-evals-summary.json" in eval_step
                    and "--summary-markdown agent-os-evals-summary.md" in eval_step
                    and "--summary-json agent-os-portability-summary.json"
                    in portability_step
                    and "--summary-markdown agent-os-portability-summary.md"
                    in portability_step
                    and "--summary-profile release" in eval_step
                    and "--summary-profile release" in portability_step
                ),
            },
            {
                "id": "summary-publication-is-always-run-and-non-masking",
                "passed": (
                    "if: always()" in publish_step
                    and "continue-on-error: true" in publish_step
                    and "$env:GITHUB_STEP_SUMMARY" in publish_step
                    and "continue-on-error" not in eval_step
                    and "continue-on-error" not in portability_step
                ),
            },
            {
                "id": "compact-json-artifact-is-pinned-bounded-and-non-masking",
                "passed": (
                    f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in upload_step
                    and "if: always()" in upload_step
                    and "continue-on-error: true" in upload_step
                    and "retention-days: 5" in upload_step
                    and "if-no-files-found: ignore" in upload_step
                    and "agent-os-evals-summary.json" in upload_step
                    and "agent-os-portability-summary.json" in upload_step
                    and "agent-os-evals-summary.md" not in upload_step
                    and "agent-os-portability-summary.md" not in upload_step
                ),
            },
        ]
    )
    with tempfile.TemporaryDirectory(prefix="agent-os-whitespace-") as temporary:
        repository = Path(temporary)
        for arguments in (
            ("init", "-b", "main"),
            ("config", "user.name", "Whitespace Fixture"),
            ("config", "user.email", "whitespace@agent-os.invalid"),
        ):
            result = git(repository, *arguments)
            if result.returncode != 0:
                raise RuntimeError(result.stderr)

        (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
        baseline = commit(repository, "baseline")

        (repository / "bad.txt").write_text(
            "committed trailing whitespace   \n", encoding="utf-8"
        )
        commit(repository, "introduce whitespace defect")
        clean_checkout_noop = git(repository, "diff", "--check")
        head_detection = check(repository)
        results.extend(
            [
                {
                    "id": "clean-checkout-working-diff-is-noop",
                    "passed": clean_checkout_noop.returncode == 0,
                },
                {
                    "id": "head-fallback-detects-committed-whitespace",
                    "passed": head_detection.returncode != 0
                    and "bad.txt" in head_detection.stdout,
                },
            ]
        )

        (repository / "follow-up.txt").write_text("clean follow-up\n", encoding="utf-8")
        commit(repository, "clean follow-up commit")
        head_only = check(repository)
        range_detection = check(repository, baseline)
        results.extend(
            [
                {
                    "id": "head-only-does-not-substitute-for-push-range",
                    "passed": head_only.returncode == 0,
                },
                {
                    "id": "push-range-detects-defect-behind-clean-tip",
                    "passed": range_detection.returncode != 0
                    and "bad.txt" in range_detection.stdout,
                },
            ]
        )

        (repository / "bad.txt").write_text("repaired content\n", encoding="utf-8")
        commit(repository, "repair whitespace defect")
        clean_range = check(repository, baseline)
        results.append(
            {
                "id": "clean-final-range-passes",
                "passed": clean_range.returncode == 0,
            }
        )

    passed = sum(1 for item in results if item["passed"])
    output = {
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(output, indent=2))
    raise SystemExit(0 if output["ok"] else 1)


if __name__ == "__main__":
    main()
