"""Platform protection and privacy-safe usage receipt contracts."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from capability_lifecycle.shared import parse_time, receipt_valid

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PLAN_ID = re.compile(r"^[0-9a-f]{24}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
USAGE_CONFIDENCE = {"low", "medium", "high"}
USAGE_OUTCOMES = {"selected", "declined", "completed", "failed"}
USAGE_MAX_EVIDENCE_ITEMS = 8
USAGE_MAX_STORED_RECEIPT_BYTES = 4096
TELEMETRY_KEY_DPAPI_ENTROPY = b"agent-os-telemetry-key-v2"
USAGE_RECEIPT_FIELDS = {
    "schema_version",
    "receipt_id",
    "capability_id",
    "capability_version",
    "router_version",
    "task_hash",
    "task_hash_algorithm",
    "selected_at",
    "confidence",
    "evidence_hashes",
    "evidence_hash_algorithm",
    "outcome",
    "raw_prompt_stored",
    "raw_evidence_stored",
    "content_sha256",
}


# fmt: off
def windows_dpapi(
    content: bytes,
    *,
    protect: bool,
    diagnostics: list[str] | None = None,
) -> bytes | None:
    """Protect or unprotect bytes for the current Windows user via DPAPI."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        def blob(value: bytes) -> tuple[DataBlob, Any]:
            buffer = ctypes.create_string_buffer(value)
            return (
                DataBlob(
                    len(value),
                    ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)),
                ),
                buffer,
            )

        input_blob, input_buffer = blob(content)
        entropy_blob, entropy_buffer = blob(TELEMETRY_KEY_DPAPI_ENTROPY)
        output_blob = DataBlob()
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DataBlob),
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        operation = (
            crypt32.CryptProtectData
            if protect
            else crypt32.CryptUnprotectData
        )
        description = "Universal Agent OS telemetry key" if protect else None
        ctypes.set_last_error(0)
        succeeded = operation(
            ctypes.byref(input_blob),
            description,
            ctypes.cast(ctypes.byref(entropy_blob), ctypes.c_void_p),
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )
        _ = input_buffer, entropy_buffer
        if not succeeded or not output_blob.pbData:
            if diagnostics is not None:
                action = "PROTECT" if protect else "UNPROTECT"
                diagnostics.append(f"DPAPI_{action}_FAILED_{ctypes.get_last_error()}")
            return None
        result = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        try:
            return result
        finally:
            try:
                local_free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
                local_free.argtypes = [ctypes.c_void_p]
                local_free.restype = ctypes.c_void_p
                local_free(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
            except Exception:  # noqa: BLE001 - DPAPI cleanup must stay fail-closed
                # The protected result remains valid. Cleanup failure is bounded
                # to this allocation and must not downgrade storage to plaintext.
                if diagnostics is not None:
                    diagnostics.append("DPAPI_LOCAL_FREE_EXCEPTION")
    except Exception as error:  # noqa: BLE001 - FFI boundary must stay fail-closed
        # The FFI boundary is security-sensitive: any platform/signature failure
        # must disable telemetry rather than expose or persist an unprotected key.
        if diagnostics is not None:
            action = "PROTECT" if protect else "UNPROTECT"
            diagnostics.append(f"DPAPI_{action}_EXCEPTION_{type(error).__name__}")
        return None


def usage_receipt_errors(receipt: Any) -> list[str]:
    """Validate the exact privacy-safe activation receipt contract.

    Schema v1 receipts are intentionally rejected: their ``evidence`` field may
    contain raw operator or prompt-derived text. Callers must ignore them rather
    than project that data onto any read surface.
    """
    if not isinstance(receipt, dict):
        return ["USAGE_RECEIPT_NOT_OBJECT"]
    errors: list[str] = []
    if set(receipt) != USAGE_RECEIPT_FIELDS:
        errors.append("USAGE_RECEIPT_FIELDS_INVALID")
    if receipt.get("schema_version") != 2:
        errors.append("USAGE_RECEIPT_SCHEMA_UNSAFE")
    if not isinstance(receipt.get("receipt_id"), str) or PLAN_ID.fullmatch(receipt["receipt_id"]) is None:
        errors.append("USAGE_RECEIPT_ID_INVALID")
    if not isinstance(receipt.get("capability_id"), str) or SAFE_ID.fullmatch(receipt["capability_id"]) is None:
        errors.append("USAGE_CAPABILITY_ID_INVALID")
    for field in ("capability_version", "router_version"):
        value = receipt.get(field)
        if not isinstance(value, str) or not value or len(value) > 64:
            errors.append(f"USAGE_{field.upper()}_INVALID")
    for field in ("task_hash",):
        value = receipt.get(field)
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            errors.append(f"USAGE_{field.upper()}_INVALID")
    if receipt.get("task_hash_algorithm") != "hmac-sha256-v2":
        errors.append("USAGE_TASK_HASH_ALGORITHM_INVALID")
    selected_at = receipt.get("selected_at")
    try:
        parsed_at = parse_time(selected_at) if isinstance(selected_at, str) else None
    except ValueError:
        parsed_at = None
    if parsed_at is None or parsed_at.tzinfo is None:
        errors.append("USAGE_SELECTED_AT_INVALID")
    if receipt.get("confidence") not in USAGE_CONFIDENCE:
        errors.append("USAGE_CONFIDENCE_INVALID")
    evidence_hashes = receipt.get("evidence_hashes")
    evidence_hashes_valid = isinstance(evidence_hashes, list)
    if evidence_hashes_valid:
        evidence_hashes_valid = (
            len(evidence_hashes) <= USAGE_MAX_EVIDENCE_ITEMS
            and all(isinstance(item, str) and SHA256.fullmatch(item) is not None for item in evidence_hashes)
            and len(evidence_hashes) == len(set(evidence_hashes))
        )
    if not evidence_hashes_valid:
        errors.append("USAGE_EVIDENCE_HASHES_INVALID")
    if receipt.get("evidence_hash_algorithm") != "hmac-sha256-v2":
        errors.append("USAGE_EVIDENCE_HASH_ALGORITHM_INVALID")
    if receipt.get("outcome") not in USAGE_OUTCOMES:
        errors.append("USAGE_OUTCOME_INVALID")
    if receipt.get("raw_prompt_stored") is not False:
        errors.append("USAGE_RAW_PROMPT_FLAG_INVALID")
    if receipt.get("raw_evidence_stored") is not False:
        errors.append("USAGE_RAW_EVIDENCE_FLAG_INVALID")
    if not isinstance(receipt.get("content_sha256"), str) or SHA256.fullmatch(receipt["content_sha256"]) is None:
        errors.append("USAGE_CONTENT_HASH_INVALID")
    elif not receipt_valid(receipt):
        errors.append("USAGE_CONTENT_HASH_MISMATCH")
    return errors


def recent_jsonl_lines(path: Path, record_limit: int) -> list[bytes]:
    """Read a bounded JSONL tail without loading an unbounded telemetry file."""
    if record_limit <= 0:
        return []
    byte_limit = record_limit * USAGE_MAX_STORED_RECEIPT_BYTES
    try:
        with path.open("rb") as handle:
            end = handle.seek(0, os.SEEK_END)
            start = max(0, end - byte_limit)
            handle.seek(start)
            content = handle.read(byte_limit)
    except OSError:
        return []
    if start:
        newline = content.find(b"\n")
        content = b"" if newline < 0 else content[newline + 1 :]
    return content.splitlines()[-record_limit:]
# fmt: on
