import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))
import preflight


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_repo(lines: int = 2) -> tuple[tempfile.TemporaryDirectory[str], Path, str]:
    holder = tempfile.TemporaryDirectory(prefix="aos15-preflight-")
    root = Path(holder.name)
    (root / "src").mkdir()
    (root / "src" / "tracked.py").write_text("one\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.name", "AOS fixture")
    git(root, "config", "user.email", "fixture@agent-os.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    (root / "src" / "tracked.py").write_text(
        "one\n" + "two\n" * (lines - 1), encoding="utf-8"
    )
    return holder, root, git(root, "rev-parse", "HEAD")


def envelope(base: str, budget: int = 5) -> dict[str, object]:
    return {
        "schema_version": 1,
        "base_commit": base,
        "budgets": {
            "oversized_source_test_lines": 1000,
            "source_test_growth_lines": budget,
            "documentation_growth_lines": 0,
            "data_growth_bytes": 0,
            "max_file_bytes": 1_048_576,
        },
        "paths": [{"path": "src/tracked.py", "artifact_class": "source-test"}],
    }


def invoke(root: Path, args: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with (
        patch.object(preflight, "PROJECT_ROOT", root),
        patch.object(sys, "argv", ["preflight", *args]),
        redirect_stdout(output),
    ):
        try:
            preflight.main()
        except SystemExit as error:
            code = int(error.code)
    return code, json.loads(output.getvalue())


def record(r: list[dict[str, object]], c: str, p: bool) -> None:
    r.append({"id": c, "passed": p})


def main() -> None:
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="aos15-envelope-") as holder:
        envelope_path = Path(holder) / "capacity.json"
        fixture, root, base = make_repo()
        try:
            envelope_path.write_text(json.dumps(envelope(base)), encoding="utf-8")
            code, admitted = invoke(root, ["--capacity-envelope", str(envelope_path)])
            record(
                results,
                "explicit-envelope-admitted",
                code == 0 and admitted["capacity_admission"]["state"] == "ADMITTED",
            )
            code, normal = invoke(root, ["--mode", "FAST", "--files", "src/tracked.py"])
            record(
                results,
                "normal-mode-compatible",
                code == 0
                and "capacity_admission" not in normal
                and normal["mode"] == "FAST",
            )
        finally:
            fixture.cleanup()

        missing = Path(holder) / "missing.json"
        code, payload = invoke(root, ["--capacity-envelope", str(missing)])
        record(
            results,
            "missing-envelope-fails-closed",
            code == 2 and payload["reason_codes"] == ["CAPACITY_ENVELOPE_INVALID"],
        )

        fixture, root, base = make_repo(2)
        try:
            envelope_path.write_text(json.dumps(envelope("0" * 40)), encoding="utf-8")
            code, payload = invoke(root, ["--capacity-envelope", str(envelope_path)])
            record(
                results,
                "invalid-base-preserves-primitive",
                code == 2
                and payload["reason_codes"] == ["CAPACITY_BASE_COMMIT_INVALID"],
            )
            (root / "src" / "extra.py").write_text("extra\n", encoding="utf-8")
            envelope_path.write_text(json.dumps(envelope(base)), encoding="utf-8")
            code, payload = invoke(root, ["--capacity-envelope", str(envelope_path)])
            record(
                results,
                "undeclared-path-preserves-primitive",
                code == 2
                and payload["reason_codes"] == ["CAPACITY_UNDECLARED_PATH_CHANGED"]
                and payload["offending_paths"] == ["src/extra.py"],
            )
        finally:
            fixture.cleanup()

        fixture, root, base = make_repo(8)
        try:
            envelope_path.write_text(json.dumps(envelope(base, 0)), encoding="utf-8")
            code, payload = invoke(root, ["--capacity-envelope", str(envelope_path)])
            record(
                results,
                "budget-preserves-primitive",
                code == 2
                and payload["reason_codes"]
                == ["CAPACITY_SOURCE_TEST_GROWTH_BUDGET_EXCEEDED"]
                and payload["offending_paths"] == ["src/tracked.py"],
            )
        finally:
            fixture.cleanup()
    passed = sum(bool(item["passed"]) for item in results)
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
