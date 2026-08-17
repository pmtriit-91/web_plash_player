# Generated client bridge catalog

Generated from `project-template/client-bridges.json`. Do not maintain a
second client-support table by hand.

| Client | Status | Root file | Discovery evidence | Role |
| --- | --- | --- | --- | --- |
| Codex | `reference-client` | `AGENTS.md` | `verified-by-fresh-session` | canonical boot bridge |
| Claude Code | `thin-shim` | `CLAUDE.md` | `client-dependent` | redirect to canonical AGENTS.md |
| Gemini CLI | `thin-shim` | `GEMINI.md` | `client-dependent` | redirect to canonical AGENTS.md |
| Antigravity | `thin-shim` | `GEMINI.md` | `evidence-required` | repository-local redirect without global symlink |

Codex is the reference client. Other files are deliberately thin redirects;
their presence is not proof that a particular client version auto-discovers them.
