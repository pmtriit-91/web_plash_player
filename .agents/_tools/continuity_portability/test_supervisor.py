"""Shared bounded process supervision for Continuity portability test shards."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO


def _read_stream(stream: TextIO, stream_name: str, messages: queue.Queue[Any]) -> None:
    try:
        for line in iter(stream.readline, ""):
            messages.put((stream_name, line.rstrip("\n")))
    finally:
        messages.put((stream_name, None))


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return

    # A descendant may own the pipes after the group leader exits. The group ID
    # remains the leader PID, so always signal the whole group.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _progress(prefix: str, event: dict[str, Any]) -> None:
    print(
        prefix + json.dumps(event, ensure_ascii=False, separators=(",", ":")),
        file=sys.stderr,
        flush=True,
    )


def supervise_command(
    label: str,
    command: list[str],
    timeout_seconds: int,
    *,
    cwd: Path,
    heartbeat_seconds: int,
    progress_prefix: str,
) -> dict[str, Any]:
    started = time.monotonic()
    popen_options: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "nt":
        popen_options["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(command, **popen_options)
    if process.stdout is None or process.stderr is None:
        _terminate_process_tree(process)
        raise RuntimeError("worker pipes unavailable")

    messages: queue.Queue[Any] = queue.Queue()
    readers = [
        threading.Thread(
            target=_read_stream, args=(process.stdout, "stdout", messages), daemon=True
        ),
        threading.Thread(
            target=_read_stream, args=(process.stderr, "stderr", messages), daemon=True
        ),
    ]
    for reader in readers:
        reader.start()
    deadline = started + timeout_seconds
    next_heartbeat = started + heartbeat_seconds
    stream_done: set[str] = set()
    timed_out = False
    worker_result: dict[str, Any] | None = None
    protocol_errors: list[dict[str, Any]] = []
    current_scenario: str | None = None
    pending_case_ids: list[str] = []
    _progress(
        progress_prefix,
        {
            "event": "supervisor_start",
            "shard_id": label,
            "timeout_seconds": timeout_seconds,
            "attempt": 1,
            "automatic_retries": 0,
        },
    )

    while True:
        now = time.monotonic()
        if not timed_out and now >= deadline:
            timed_out = True
            _progress(
                progress_prefix,
                {
                    "event": "shard_timeout",
                    "shard_id": label,
                    "timeout_seconds": timeout_seconds,
                    "active_scenario": current_scenario,
                    "pending_case_ids": pending_case_ids,
                },
            )
            _terminate_process_tree(process)
        if not timed_out and now >= next_heartbeat:
            _progress(
                progress_prefix,
                {
                    "event": "heartbeat",
                    "shard_id": label,
                    "elapsed_seconds": round(now - started, 1),
                    "active_scenario": current_scenario,
                    "pending_case_ids": pending_case_ids,
                    "worker_exited": process.poll() is not None,
                },
            )
            next_heartbeat = now + heartbeat_seconds

        try:
            stream_name, line = messages.get(timeout=0.25)
        except queue.Empty:
            stream_name = ""
            line = ""
        if stream_name:
            if line is None:
                stream_done.add(stream_name)
            elif stream_name == "stderr":
                _progress(
                    progress_prefix,
                    {
                        "event": "worker_stderr",
                        "shard_id": label,
                        "message": line[:4000],
                    },
                )
            else:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    protocol_errors.append(
                        {"code": "WORKER_PROTOCOL_INVALID_JSON", "line": line[:2000]}
                    )
                    _progress(
                        progress_prefix,
                        {
                            "event": "worker_stdout",
                            "shard_id": label,
                            "message": line[:2000],
                        },
                    )
                else:
                    if event.get("event") == "scenario_start":
                        current_scenario = event.get("scenario_id")
                        pending_case_ids = list(event.get("case_ids", []))
                    elif event.get("event") == "scenario_end":
                        current_scenario = None
                        pending_case_ids = []
                    elif event.get("event") == "shard_result":
                        worker_result = event
                    _progress(progress_prefix, event)

        if process.poll() is not None and stream_done == {"stdout", "stderr"}:
            break
        if timed_out and time.monotonic() > deadline + 3:
            break

    for reader in readers:
        reader.join(timeout=1)
    return_code = process.poll()
    duration = round(time.monotonic() - started, 3)
    if timed_out:
        protocol_errors.append(
            {
                "code": "SHARD_TIMEOUT",
                "timeout_seconds": timeout_seconds,
                "active_scenario": current_scenario,
                "pending_case_ids": pending_case_ids,
            }
        )
    elif worker_result is None:
        protocol_errors.append(
            {"code": "WORKER_RESULT_MISSING", "return_code": return_code}
        )
    elif return_code not in {0, 2}:
        protocol_errors.append(
            {"code": "WORKER_EXIT_UNEXPECTED", "return_code": return_code}
        )
    return {
        "shard_id": label,
        "attempts": 1,
        "automatic_retries": 0,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "duration_seconds": duration,
        "return_code": return_code,
        "active_scenario": current_scenario,
        "pending_case_ids": pending_case_ids,
        "streams_closed": stream_done == {"stdout", "stderr"},
        "protocol_errors": protocol_errors,
        "worker_result": worker_result,
    }
