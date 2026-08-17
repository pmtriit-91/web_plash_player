"""Privacy-safe capability usage telemetry."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from typing import Any

from capability_lifecycle.platform_privacy import (
    USAGE_CONFIDENCE,
    USAGE_MAX_EVIDENCE_ITEMS,
    USAGE_OUTCOMES,
    recent_jsonl_lines,
    usage_receipt_errors,
    windows_dpapi,
)
from capability_lifecycle.shared import (
    DESCRIPTORS,
    REGISTRY,
    atomic_bytes,
    canonical_hash,
    iso_time,
    load_json,
    receipt_hash,
)

USAGE_MAX_TASK_BYTES = 65536
USAGE_MAX_EVIDENCE_BYTES = 4096
TELEMETRY_KEY_BYTES = 32
TELEMETRY_KEY_DPAPI_PREFIX = b"agent-os-dpapi-v1\\0"


class TelemetryMixin:
    # fmt: off
    def telemetry_key(self) -> bytes | None:
        """Load or create the local telemetry HMAC key without disclosing it."""
        self.telemetry_salt.parent.mkdir(parents=True, exist_ok=True)
        if self.telemetry_salt.is_symlink():
            return None
        if not self.telemetry_salt.exists():
            descriptor: int | None = None
            try:
                key = os.urandom(TELEMETRY_KEY_BYTES)
                if os.name == "nt":
                    protected = windows_dpapi(key, protect=True)
                    if protected is None:
                        return None
                    stored = TELEMETRY_KEY_DPAPI_PREFIX + protected
                else:
                    stored = key
                descriptor = os.open(
                    self.telemetry_salt,
                    os.O_CREAT
                    | os.O_EXCL
                    | os.O_WRONLY
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                written = os.write(descriptor, stored)
                if written != len(stored):
                    return None
                os.fsync(descriptor)
            except FileExistsError:
                pass
            except OSError:
                return None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        if self.telemetry_salt.is_symlink() or not self.telemetry_salt.is_file():
            return None
        try:
            stored = self.telemetry_salt.read_bytes()
        except OSError:
            return None
        if os.name == "nt":
            if stored.startswith(TELEMETRY_KEY_DPAPI_PREFIX):
                key = windows_dpapi(stored[len(TELEMETRY_KEY_DPAPI_PREFIX):], protect=False)
            elif len(stored) == TELEMETRY_KEY_BYTES:
                key = stored
                protected = windows_dpapi(key, protect=True)
                if protected is None:
                    return None
                try:
                    atomic_bytes(self.telemetry_salt, TELEMETRY_KEY_DPAPI_PREFIX + protected)
                except OSError:
                    return None
            else:
                return None
        else:
            try:
                os.chmod(self.telemetry_salt, 0o600)
                if stat.S_IMODE(self.telemetry_salt.stat().st_mode) != 0o600:
                    return None
            except OSError:
                return None
            key = stored
        return key if key is not None and len(key) == TELEMETRY_KEY_BYTES else None

    @staticmethod
    def telemetry_hmac(key: bytes, domain: bytes, value: bytes) -> str:
        return hmac.new(key, b"agent-os-telemetry-v2\0" + domain + b"\0" + value, hashlib.sha256).hexdigest()

    def append_usage_receipt(self, receipt: dict[str, Any]) -> bool:
        """Append one bounded, raw-free receipt with a single OS write."""
        payload = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.telemetry.parent.mkdir(parents=True, exist_ok=True)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.telemetry,
                os.O_APPEND
                | os.O_CREAT
                | os.O_WRONLY
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
            written = os.write(descriptor, payload)
            if written != len(payload):
                return False
            os.fsync(descriptor)
        except OSError:
            return False
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return True

    def record_usage(self, capability_id: str, task: str, confidence: str, evidence: list[str], outcome: str) -> dict[str, Any]:
        descriptor_document = self.document(DESCRIPTORS, {})
        known = {item.get("id"): item for item in descriptor_document.get("capabilities", []) if isinstance(item, dict)}
        try:
            task_bytes = task.encode("utf-8") if isinstance(task, str) else b""
            evidence_bytes = (
                [item.encode("utf-8") for item in evidence]
                if isinstance(evidence, list) and all(isinstance(item, str) for item in evidence)
                else []
            )
        except UnicodeEncodeError:
            task_bytes = b""
            evidence_bytes = []
        evidence_valid = bool(
            isinstance(evidence, list)
            and len(evidence) == len(evidence_bytes)
            and len(evidence) <= USAGE_MAX_EVIDENCE_ITEMS
            and all(
                isinstance(item, str)
                and 0 < len(encoded_item) <= USAGE_MAX_EVIDENCE_BYTES
                for item, encoded_item in zip(evidence, evidence_bytes)
            )
        )
        if (
            capability_id not in known
            or confidence not in USAGE_CONFIDENCE
            or outcome not in USAGE_OUTCOMES
            or not 0 < len(task_bytes) <= USAGE_MAX_TASK_BYTES
            or not evidence_valid
        ):
            return {"ok": False, "reason_codes": ["USAGE_RECEIPT_INVALID"]}
        salt = self.telemetry_key()
        if salt is None:
            return {"ok": False, "reason_codes": ["USAGE_TELEMETRY_KEY_INVALID"]}
        selected_at = iso_time(self.now())
        evidence_hashes = list(
            dict.fromkeys(
                self.telemetry_hmac(salt, b"evidence", item)
                for item in evidence_bytes
            )
        )
        receipt = {
            "schema_version": 2,
            "receipt_id": canonical_hash({"capability": capability_id, "at": selected_at, "nonce": os.urandom(16).hex()})[:24],
            "capability_id": capability_id,
            "capability_version": known[capability_id].get("version"),
            "router_version": self.document(REGISTRY, {}).get("version"),
            "task_hash": self.telemetry_hmac(salt, b"task", task_bytes),
            "task_hash_algorithm": "hmac-sha256-v2",
            "selected_at": selected_at,
            "confidence": confidence,
            "evidence_hashes": evidence_hashes,
            "evidence_hash_algorithm": "hmac-sha256-v2",
            "outcome": outcome,
            "raw_prompt_stored": False,
            "raw_evidence_stored": False,
        }
        receipt["content_sha256"] = receipt_hash(receipt)
        if usage_receipt_errors(receipt):
            return {"ok": False, "reason_codes": ["USAGE_RECEIPT_INVALID"]}
        if not self.append_usage_receipt(receipt):
            return {"ok": False, "reason_codes": ["USAGE_TELEMETRY_WRITE_FAILED"]}
        return {"ok": True, "receipt": receipt, "raw_prompt_stored": False, "raw_evidence_stored": False}

    def usage_review(self) -> dict[str, Any]:
        descriptor_document = self.document(DESCRIPTORS, {})
        known = sorted(item.get("id") for item in descriptor_document.get("capabilities", []) if isinstance(item, dict) and item.get("id"))
        records: dict[str, list[dict[str, Any]]] = {capability_id: [] for capability_id in known}
        malformed = 0
        privacy_unsafe = 0
        if self.telemetry.is_file():
            for line in recent_jsonl_lines(self.telemetry, 10000):
                try:
                    item = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    malformed += 1
                    continue
                errors = usage_receipt_errors(item)
                if errors:
                    malformed += 1
                    if isinstance(item, dict) and (
                        item.get("schema_version") != 2
                        or "evidence" in item
                        or item.get("raw_prompt_stored") is not False
                        or item.get("raw_evidence_stored") is not False
                    ):
                        privacy_unsafe += 1
                    continue
                if item.get("capability_id") in records:
                    records[item["capability_id"]].append(item)
        summary = []
        for capability_id in known:
            items = records[capability_id]
            failed = sum(1 for item in items if item.get("outcome") in {"declined", "failed"})
            summary.append(
                {
                    "capability_id": capability_id,
                    "observations": len(items),
                    "failed_or_declined": failed,
                    "never_observed": not items,
                    "review_recommended": len(items) >= 3 and failed / len(items) >= 0.5,
                }
            )
        return {
            "ok": True,
            "summary": summary,
            "malformed_records_ignored": malformed,
            "privacy_unsafe_records_ignored": privacy_unsafe,
            "raw_prompts_stored": False,
            "raw_evidence_stored": False,
            "authority": "local-telemetry-only",
        }

    def queue(self) -> dict[str, Any]:
        plans = [load_json(path, {}) for path in sorted(self.plans.glob("*.json"))] if self.plans.is_dir() else []
        receipts = [load_json(path, {}) for path in sorted(self.receipts.glob("*.json"))] if self.receipts.is_dir() else []
        return {"ok": True, "plans": plans, "receipts": receipts, "recovery_required": self.journal.is_file()}
    # fmt: on
