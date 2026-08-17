#!/usr/bin/env python3
"""Focused localhost, token, origin, CSP, and read-parity contracts."""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from agent_os_context_memory import ContextMemoryService
from agent_os_control_center import CSP, ControlCenterServer
from agent_os_domain import (
    memory_snapshot,
    research_snapshot,
    settings_snapshot,
    skills_list,
)
from agent_os_transactions import TransactionService
from control_center.test_support import BASE_SETTINGS, git

ROOT = Path(__file__).resolve().parents[2]


def repository(parent: Path, name: str) -> tuple[Path, Path]:
    root = parent / name
    agent_root = root / ".agents"
    (agent_root / "project").mkdir(parents=True)
    (agent_root / "skills" / "project-memory").mkdir(parents=True)
    (agent_root / "project" / "skill-config.json").write_text(json.dumps(BASE_SETTINGS, indent=2) + "\n", encoding="utf-8")
    (agent_root / "memory").mkdir(parents=True)
    (agent_root / "memory" / "context-policy.json").write_bytes((ROOT / "memory" / "context-policy.json").read_bytes())
    (agent_root / "project" / "project-binding.json").write_text(
        json.dumps({"schema_version": 1, "project_id": "fixture-project", "repository": {"kind": "git", "root_markers": ["marker.txt"], "remote_aliases": ["fixture/control-center"]}, "commands": [], "context_entrypoints": [], "created_at": "2026-07-19T00:00:00Z", "last_verified_at": "2026-07-19T00:00:00Z", "last_verified_commit": None}, indent=2) + "\n",
        encoding="utf-8",
    )
    (agent_root / "_manifest").mkdir(parents=True)
    (agent_root / "_manifest" / "base-release-manifest.json").write_text('{"schema_version":1,"release_id":"fixture"}\n', encoding="utf-8")
    (agent_root / "skills" / "project-memory" / "SKILL.md").write_text("protected\n", encoding="utf-8")
    (root / ".gitignore").write_text(".agents/_runtime/\n", encoding="utf-8")
    (root / "marker.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Agent OS Test")
    git(root, "config", "user.email", "agent-os@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture baseline")
    return root, agent_root


def request(port: int, method: str, path: str, token: str | None = None, origin: str | None = None, body: str | None = None, host: str | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers: dict[str, str] = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    if body is not None:
        headers["Content-Type"] = "application/json"
    if host is not None:
        headers["Host"] = host
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    response_headers = {key: value for key, value in response.getheaders()}
    connection.close()
    return response.status, response_headers, payload


def run_security_contracts(
    port: int,
    token: str,
    origin: str,
    memory_service: ContextMemoryService,
) -> tuple[list[dict], str]:
    results: list[dict] = []
    status, headers, payload = request(port, "GET", "/")
    text = payload.decode("utf-8")
    results.append({"id": "static-local-no-cdn-csp", "passed": status == 200 and headers.get("Content-Security-Policy") == CSP and "https://" not in text and "http://" not in text})

    status, _, _ = request(port, "GET", "/api/transactions")
    results.append({"id": "api-token-required", "passed": status == 401})

    status, _, payload = request(port, "GET", "/api/transactions", token=token)
    results.append({"id": "authorized-read", "passed": status == 200 and json.loads(payload).get("ok") is True})

    parity = True
    for endpoint, expected in (
        ("/api/skills", skills_list()),
        ("/api/research", research_snapshot()),
        ("/api/settings", settings_snapshot()),
    ):
        api_status, _, api_payload = request(port, "GET", endpoint, token=token)
        parity = parity and api_status == 200 and json.loads(api_payload) == expected
    results.append({"id": "ui-domain-read-parity", "passed": parity})

    api_status, _, api_payload = request(port, "GET", "/api/memory", token=token)
    results.append({"id": "memory-ui-domain-read-parity", "passed": api_status == 200 and json.loads(api_payload) == memory_snapshot(service=memory_service)})

    status, _, _ = request(port, "GET", "/api/transactions", token="wrong")
    results.append({"id": "wrong-token-rejected", "passed": status == 401})

    status, _, _ = request(port, "GET", "/", host="malicious.example")
    results.append({"id": "host-header-rejected", "passed": status == 400})

    desired = deepcopy(BASE_SETTINGS)
    desired["default_mode"] = "FAST"
    body = json.dumps({"desired": desired})
    status, _, _ = request(port, "POST", "/api/settings/plan", token=token, body=body)
    results.append({"id": "mutation-origin-required", "passed": status == 403})

    status, _, _ = request(port, "POST", "/api/settings/plan", token=token, origin="http://malicious.example", body=body)
    results.append({"id": "cross-origin-rejected", "passed": status == 403})

    status, _, _ = request(port, "POST", "/api/settings/plan", token=token, origin=origin, body="{")
    results.append({"id": "malformed-json-rejected", "passed": status == 400})
    return results, body


def main() -> None:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="agent-os-control-security-") as temporary:
        _, agent_root = repository(Path(temporary), "server")
        memory_service = ContextMemoryService(agent_root)
        initialized = memory_service.plan_initialize()
        if not initialized.get("ok") or not memory_service.apply(initialized["plan"]["plan_id"], True).get("ok"):
            raise RuntimeError("memory fixture initialization failed")
        for command in (["git", "add", ".agents/project/context", ".agents/skills/project-memory/SKILL.md"], ["git", "commit", "-qm", "fixture memory"]):
            result = subprocess.run(command, cwd=agent_root.parent, capture_output=True, text=True, timeout=10, check=False)
            if result.returncode != 0:
                raise RuntimeError(result.stderr)
        token = "test-token-with-sufficient-entropy-for-fixture"
        server = ControlCenterServer(("127.0.0.1", 0), token, 300, TransactionService(agent_root), None, memory_service)
        port = server.server_address[1]
        origin = server.origin
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            results, body = run_security_contracts(port, token, origin, memory_service)

            status, _, payload = request(port, "POST", "/api/settings/plan", token=token, origin=origin, body=body)
            planned = json.loads(payload)
            plan_id = planned.get("plan", {}).get("plan_id", "")
            apply_status, _, apply_payload = request(port, "POST", f"/api/transactions/{plan_id}/apply", token=token, origin=origin, body=json.dumps({"confirm": True}))
            results.append({"id": "two-phase-api-apply", "passed": status == 201 and apply_status == 200 and json.loads(apply_payload).get("ok") is True})

            memory_status, _, memory_payload = request(port, "POST", "/api/memory/refresh/plan", token=token, origin=origin, body="{}")
            memory_plan = json.loads(memory_payload)
            results.append({"id": "memory-mutation-is-plan-only", "passed": memory_status == 201 and memory_plan.get("plan", {}).get("status") == "pending-approval"})

            server.session_deadline = time.monotonic() - 1
            status, _, _ = request(port, "GET", "/api/transactions", token=token)
            results.append({"id": "session-expiry-enforced", "passed": status == 403})
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        unsafe_bind_rejected = False
        try:
            ControlCenterServer(("0.0.0.0", 0), token, 300, TransactionService(agent_root))
        except ValueError:
            unsafe_bind_rejected = True
        results.append({"id": "non-localhost-bind-rejected", "passed": unsafe_bind_rejected})

    passed = sum(1 for item in results if item.get("passed"))
    output = {"ok": passed == len(results), "passed": passed, "total": len(results), "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    raise SystemExit(0 if output["ok"] else 2)


if __name__ == "__main__":
    main()
