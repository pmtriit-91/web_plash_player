# Repository-local client integration — V9.1.0

Agent OS uses the root `AGENTS.md` bridge for Codex-compatible discovery. It does not
create global symlinks or modify client-global configuration.

`agent_os_mcp_server.py` is an optional local, read-only stdio adapter. It exposes
doctor, integrity, routing, and preflight checks backed by the same canonical
lifecycle engine. It has no project command runner and no release update endpoint.

`ide-policy.json` describes client expectations but is not a second lifecycle state
authority.

`project-template/client-bridges.json` is the machine-readable client authority.
Codex is the reference client. Optional `CLAUDE.md` and `GEMINI.md` files only redirect
to the canonical bridge; they do not duplicate policy or prove auto-discovery for an
unwitnessed client version. Packaging can add governed shims with `--client`.
