#!/usr/bin/env python3
"""Localhost-only Control Center for Universal Agent OS."""

from __future__ import annotations

import argparse
import json
import secrets
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from agent_os_capability_lifecycle import CapabilityLifecycleService
from agent_os_context_memory import ContextMemoryService, load_json
from agent_os_domain import candidate_show, lifecycle_snapshot, memory_snapshot, overview, research_snapshot, settings_snapshot, skill_show, skills_list, simulate, usage_review
from agent_os_transactions import TransactionService

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "control-center"
MAX_BODY = 1024 * 1024
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"


class ControlCenterServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str, session_seconds: int, transactions: TransactionService | None = None, capability_transactions: CapabilityLifecycleService | None = None, memory_transactions: ContextMemoryService | None = None):
        if address[0] != "127.0.0.1":
            raise ValueError("Control Center must bind exactly 127.0.0.1")
        super().__init__(address, ControlCenterHandler)
        self.session_token = token
        self.session_deadline = time.monotonic() + session_seconds
        self.transactions = transactions or TransactionService()
        self.capability_transactions = capability_transactions or CapabilityLifecycleService()
        self.memory_transactions = memory_transactions or ContextMemoryService()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class ControlCenterHandler(BaseHTTPRequestHandler):
    server: ControlCenterServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def security_headers(self) -> None:
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

    def send_payload(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: int, data: Any) -> None:
        self.send_payload(status, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), "application/json; charset=utf-8")

    def request_host_valid(self) -> bool:
        return self.headers.get("Host", "") == f"127.0.0.1:{self.server.server_address[1]}"

    def authenticated(self) -> tuple[bool, str]:
        if time.monotonic() > self.server.session_deadline:
            return False, "SESSION_EXPIRED"
        value = self.headers.get("Authorization", "")
        supplied = value.removeprefix("Bearer ") if value.startswith("Bearer ") else ""
        if not supplied or not secrets.compare_digest(supplied, self.server.session_token):
            return False, "AUTH_REQUIRED"
        return True, ""

    def api_guard(self, mutation: bool = False) -> bool:
        if not self.request_host_valid():
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "HOST_REJECTED", "message": "Invalid Host header."}})
            return False
        authenticated, reason = self.authenticated()
        if not authenticated:
            status = HTTPStatus.UNAUTHORIZED if reason == "AUTH_REQUIRED" else HTTPStatus.FORBIDDEN
            self.send_json(status, {"ok": False, "error": {"code": reason, "message": reason.replace("_", " ").title()}})
            return False
        if mutation and self.headers.get("Origin") != self.server.origin:
            self.send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": {"code": "ORIGIN_REJECTED", "message": "Mutation requires exact same origin."}})
            return False
        return True

    def read_json(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length")
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Request body size is invalid")
        return json.loads(self.rfile.read(length))

    def serve_static(self, relative: str, content_type: str) -> None:
        path = STATIC / relative
        try:
            payload = path.read_bytes()
        except OSError:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "NOT_FOUND", "message": relative}})
            return
        self.send_payload(HTTPStatus.OK, payload, content_type)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not self.request_host_valid():
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "HOST_REJECTED", "message": "Invalid Host header."}})
            return
        if parsed.path == "/":
            self.serve_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self.serve_static("app.js", "text/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self.serve_static("styles.css", "text/css; charset=utf-8")
            return
        if not parsed.path.startswith("/api/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "NOT_FOUND", "message": parsed.path}})
            return
        if not self.api_guard():
            return
        try:
            if parsed.path == "/api/overview":
                result = overview()
            elif parsed.path == "/api/skills":
                result = skills_list()
            elif parsed.path.startswith("/api/skills/") and parsed.path.endswith("/usage"):
                capability = unquote(parsed.path.removeprefix("/api/skills/").removesuffix("/usage").strip("/"))
                result = usage_review(capability)
            elif parsed.path.startswith("/api/skills/"):
                result = skill_show(unquote(parsed.path.removeprefix("/api/skills/")))
            elif parsed.path == "/api/research":
                result = research_snapshot()
            elif parsed.path.startswith("/api/research/"):
                result = candidate_show(unquote(parsed.path.removeprefix("/api/research/")))
            elif parsed.path == "/api/lifecycle":
                result = lifecycle_snapshot()
            elif parsed.path == "/api/settings":
                result = settings_snapshot()
            elif parsed.path == "/api/memory":
                result = memory_snapshot(service=self.server.memory_transactions)
            elif parsed.path == "/api/memory/tasks":
                result = self.server.memory_transactions.list_tasks()
            elif parsed.path == "/api/memory/handoffs":
                result = self.server.memory_transactions.list_handoffs()
            elif parsed.path == "/api/transactions":
                settings_queue = self.server.transactions.queue()
                capability_queue = self.server.capability_transactions.queue()
                memory_plans = [load_json(path, {}) for path in sorted(self.server.memory_transactions.plans.glob("*.json"))] if self.server.memory_transactions.plans.is_dir() else []
                memory_receipts = [load_json(path, {}) for path in sorted(self.server.memory_transactions.receipts.glob("*.json"))] if self.server.memory_transactions.receipts.is_dir() else []
                result = {
                    "ok": settings_queue.get("ok") is True and capability_queue.get("ok") is True,
                    "plans": [
                        *({**item, "transaction_domain": "settings"} for item in settings_queue.get("plans", [])),
                        *({**item, "transaction_domain": "capability"} for item in capability_queue.get("plans", [])),
                        *({**item, "transaction_domain": "memory"} for item in memory_plans),
                    ],
                    "receipts": [
                        *({**item, "transaction_domain": "settings"} for item in settings_queue.get("receipts", [])),
                        *({**item, "transaction_domain": "capability"} for item in capability_queue.get("receipts", [])),
                        *({**item, "transaction_domain": "memory"} for item in memory_receipts),
                    ],
                }
            elif parsed.path == "/api/routing":
                prompt = parse_qs(parsed.query).get("prompt", [""])[0]
                if not prompt or len(prompt) > 4000:
                    raise ValueError("prompt is required and limited to 4000 characters")
                result = simulate(prompt)
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "NOT_FOUND", "message": parsed.path}})
                return
            self.send_json(HTTPStatus.OK if result.get("ok") else HTTPStatus.UNPROCESSABLE_ENTITY, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "INVALID_INPUT", "message": str(exc)}})
        except Exception:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Control Center operation failed."}})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "NOT_FOUND", "message": parsed.path}})
            return
        if not self.api_guard(mutation=True):
            return
        try:
            body = self.read_json()
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            if parsed.path == "/api/settings/plan":
                result = self.server.transactions.plan_settings(body.get("desired"))
            elif parsed.path == "/api/skills/integrations/plan":
                result = self.server.capability_transactions.plan_integration(body.get("candidate"), body.get("assembly"))
            elif parsed.path == "/api/skills/states/plan":
                result = self.server.capability_transactions.plan_state_change(
                    str(body.get("capability_id", "")), str(body.get("state", "")), body.get("replacement")
                )
            elif parsed.path == "/api/skills/rollbacks/plan":
                result = self.server.capability_transactions.plan_rollback(str(body.get("transaction_id", "")))
            elif parsed.path == "/api/lifecycle/recover":
                result = self.server.capability_transactions.recover(body.get("confirm") is True)
            elif parsed.path == "/api/memory/initialize/plan":
                result = self.server.memory_transactions.plan_initialize()
            elif parsed.path == "/api/memory/refresh/plan":
                result = self.server.memory_transactions.plan_refresh()
            elif parsed.path == "/api/memory/proposals/plan":
                result = self.server.memory_transactions.plan_upsert(body.get("proposal"))
            elif parsed.path == "/api/memory/tasks/plan":
                result = self.server.memory_transactions.plan_claim_task(body.get("task"))
            elif parsed.path == "/api/memory/handoffs/plan":
                result = self.server.memory_transactions.plan_handoff(body.get("handoff"))
            elif parsed.path == "/api/memory/compactions/plan":
                result = self.server.memory_transactions.plan_compact(body.get("compaction"))
            elif parsed.path.startswith("/api/transactions/") and parsed.path.endswith("/apply"):
                plan_id = unquote(parsed.path.removeprefix("/api/transactions/").removesuffix("/apply").strip("/"))
                capability_plan = self.server.capability_transactions.plans / f"{plan_id}.json"
                memory_plan = self.server.memory_transactions.plans / f"{plan_id}.json"
                if memory_plan.is_file():
                    result = self.server.memory_transactions.apply(plan_id, body.get("confirm") is True)
                elif capability_plan.is_file():
                    result = self.server.capability_transactions.apply(plan_id, body.get("confirm") is True)
                else:
                    result = self.server.transactions.apply_settings(plan_id, body.get("confirm") is True)
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "NOT_FOUND", "message": parsed.path}})
                return
            success_status = HTTPStatus.CREATED if parsed.path.endswith("/plan") and result.get("ok") else HTTPStatus.OK
            self.send_json(success_status if result.get("ok") else HTTPStatus.CONFLICT, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": {"code": "INVALID_INPUT", "message": str(exc)}})
        except Exception:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Control Center mutation failed."}})


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local Agent OS Control Center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--session-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.host != "127.0.0.1" or not 60 <= args.session_seconds <= 86400 or not 0 <= args.port <= 65535:
        print(json.dumps({"ok": False, "reason_codes": ["UNSAFE_SERVER_CONFIGURATION"]}, indent=2))
        raise SystemExit(2)
    token = secrets.token_urlsafe(32)
    server = ControlCenterServer((args.host, args.port), token, args.session_seconds)
    print(json.dumps({"ok": True, "url": f"{server.origin}/?token={token}", "bind": args.host, "port": server.server_address[1], "session_seconds": args.session_seconds}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
