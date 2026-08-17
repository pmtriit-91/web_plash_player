"""Shared path, document, hash, and runtime-state foundations."""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_paths import portable_relative, safe_join

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = "routing/capability-registry.json"
DESCRIPTORS = "routing/capability-descriptors.json"
CAPABILITY_DECISIONS = "routing/capability-decisions.json"
LIFECYCLE_LEDGER = "routing/capability-lifecycle.json"
CANDIDATES = "research/candidate-registry.json"
RESEARCH_DECISIONS = "research/decision-history.json"
VENDOR_LOCK = "vendor/vendor-lock.json"
ROUTING_CORPUS = "evals/capability-lifecycle-routing.json"
MANIFEST = "_manifest/base-release-manifest.json"
CONTROL_DOCUMENTS = {
    REGISTRY,
    DESCRIPTORS,
    CAPABILITY_DECISIONS,
    LIFECYCLE_LEDGER,
    CANDIDATES,
    RESEARCH_DECISIONS,
    VENDOR_LOCK,
    ROUTING_CORPUS,
    MANIFEST,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# fmt: off
def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return deepcopy(default)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json_bytes(value))


def encoded(content: bytes | None) -> str | None:
    return base64.b64encode(content).decode("ascii") if content is not None else None


def decoded(value: str | None) -> bytes | None:
    return base64.b64decode(value.encode("ascii"), validate=True) if value is not None else None


def safe_relative(value: str) -> str:
    return portable_relative(value)


def receipt_hash(receipt: dict[str, Any]) -> str:
    return canonical_hash({key: value for key, value in receipt.items() if key != "content_sha256"})


def receipt_valid(receipt: dict[str, Any]) -> bool:
    return receipt.get("content_sha256") == receipt_hash(receipt)


class CapabilityLifecycleBase:
    def __init__(self, agent_root: Path = DEFAULT_ROOT, now: Callable[[], datetime] = utc_now):
        self.root = agent_root.resolve()
        self.project_root = self.root.parent
        self.runtime = self.root / "_runtime" / "capability-lifecycle"
        self.plans = self.runtime / "plans"
        self.receipts = self.runtime / "receipts"
        self.telemetry = self.root / "_telemetry" / "activation-receipts.jsonl"
        self.telemetry_salt = self.root / "_runtime" / "telemetry" / "task-hash.key"
        self.runtime_candidates = self.root / "_runtime" / "research" / "candidates.json"
        self.runtime_decisions = self.root / "_runtime" / "research" / "decision-receipts.json"
        self.journal = self.runtime / "write-ahead-journal.json"
        self.now = now

    def path(self, relative: str) -> Path:
        relative = safe_relative(relative)
        return safe_join(self.root, relative)

    def git(self, *arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=self.project_root, capture_output=True,
                text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def read_bytes(self, relative: str) -> bytes | None:
        path = self.path(relative)
        return path.read_bytes() if path.is_file() else None

    def document(self, relative: str, default: Any) -> Any:
        return load_json(self.path(relative), default)

    def protected_digest(self) -> str:
        records: list[dict[str, Any]] = []
        scopes = [self.root / "project", self.root / "skills" / "project-memory", self.root / "skills" / "project-local"]
        for scope in scopes:
            if not scope.exists():
                continue
            for path in sorted(scope.rglob("*"), key=lambda item: item.as_posix()):
                if path.is_dir():
                    continue
                relative = path.relative_to(self.root).as_posix()
                if path.is_symlink():
                    records.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
                elif path.is_file():
                    records.append({"path": relative, "type": "file", "sha256": sha256_bytes(path.read_bytes())})
        return canonical_hash(records)

    def budget(self) -> int:
        settings = self.document("project/skill-config.json", {})
        value = settings.get("budgets", {}).get("max_snapshot_bytes", 10 * 1024 * 1024)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 10 * 1024 * 1024

    def runtime_candidate_records(self) -> list[dict[str, Any]]:
        document = load_json(self.runtime_candidates, {"schema_version": 1, "candidates": []})
        records = document.get("candidates") if isinstance(document, dict) else []
        return records if isinstance(records, list) else []

    def runtime_decision_records(self) -> list[dict[str, Any]]:
        document = load_json(self.runtime_decisions, {"schema_version": 1, "receipts": []})
        records = document.get("receipts") if isinstance(document, dict) else []
        return records if isinstance(records, list) else []

    def persist_runtime_candidate(self, candidate: dict[str, Any]) -> None:
        key = f"{candidate.get('id')}@{candidate.get('source', {}).get('commit')}"
        records = {
            f"{item.get('id')}@{item.get('source', {}).get('commit')}": item
            for item in self.runtime_candidate_records()
            if isinstance(item, dict)
        }
        records[key] = candidate
        atomic_json(
            self.runtime_candidates,
            {"schema_version": 1, "authority": "runtime-research-state", "candidates": [records[item] for item in sorted(records)]},
        )

    def persist_runtime_decision(self, receipt: dict[str, Any]) -> None:
        records = self.runtime_decision_records()
        if any(item.get("id") == receipt.get("id") for item in records if isinstance(item, dict)):
            return
        atomic_json(
            self.runtime_decisions,
            {"schema_version": 1, "authority": "runtime-research-history", "receipts": [*records, receipt]},
        )

    def clean_head(self) -> tuple[str | None, list[str]]:
        head = self.git("rev-parse", "HEAD")
        dirty = (self.git("status", "--porcelain") or "").splitlines()
        return head, dirty

    def base_documents(self) -> dict[str, Any]:
        return {
            REGISTRY: self.document(REGISTRY, {}),
            DESCRIPTORS: self.document(DESCRIPTORS, {"schema_version": 1, "agent_os_version": "", "capabilities": []}),
            CAPABILITY_DECISIONS: self.document(CAPABILITY_DECISIONS, {"schema_version": 1, "receipts": []}),
            LIFECYCLE_LEDGER: self.document(LIFECYCLE_LEDGER, {"schema_version": 1, "append_only": True, "receipts": []}),
            CANDIDATES: self.document(CANDIDATES, {"schema_version": 1, "authority": "research-candidates-only", "candidates": []}),
            RESEARCH_DECISIONS: self.document(RESEARCH_DECISIONS, {"schema_version": 1, "append_only": True, "receipts": []}),
            VENDOR_LOCK: self.document(VENDOR_LOCK, {"schema_version": 1, "generated_at": iso_time(self.now()), "packages": [], "research_sources": []}),
            ROUTING_CORPUS: self.document(ROUTING_CORPUS, {"schema_version": 1, "cases": []}),
        }

    def ownership(self) -> dict[str, Any]:
        return self.document("core/contracts/ownership-policy.json", {})

    @staticmethod
    def matches_scope(relative: str, scope: str) -> bool:
        if scope.endswith("/**"):
            prefix = scope[:-3].rstrip("/")
            return relative == prefix or relative.startswith(prefix + "/")
        return fnmatch.fnmatch(relative, scope)

    def owner(self, relative: str) -> str:
        policy = self.ownership()
        if relative == policy.get("manifest_self"):
            return "manifest"
        if any(self.matches_scope(relative, scope) for scope in policy.get("application_owned_scopes", [])):
            return "application"
        if any(self.matches_scope(relative, scope) for scope in policy.get("runtime_scopes", [])):
            return "runtime"
        return "release" if relative.split("/", 1)[0] in set(policy.get("release_owned_roots", [])) else "unclassified"
# fmt: on
