# Governed vendor capability catalog — V9.1.0

This is a human-readable view. `routing/capability-registry.json` is the loading
authority and `vendor/vendor-lock.json` is the provenance authority.

The release contains eight selected `SKILL.md` files from
`addyosmani/agent-skills`, pinned to commit
`98967c45a42b88d6b8fb3a88b7ff6273920763d6` under its MIT license:

- API and interface design
- code review and quality
- code simplification
- debugging and error recovery
- documentation and ADRs
- security and hardening
- source-driven development
- test-driven development

Only the allowlisted skill files and upstream license are vendored. Upstream hooks,
agents, commands, scripts, installers, and meta-routing are deliberately excluded.

No other researched repository is part of this release. Research candidates require
an explicit redistribution-compatible license, a full commit pin, path allowlist,
content/security review, and integration evals before admission.

## Adapted research sources

`vendor/vendor-lock.json` also records exact inspected revisions that influenced
local release policy without being copied as vendor packages:

- `jacob-bd/notebooklm-mcp-cli`: adapted into the concise on-demand
  `notebooklm-research` skill. The 891-line upstream skill is not vendored.
- `obra/superpowers`: fresh-evidence and review-feedback principles were adapted
  into existing gates. Its boot hooks, mandatory router, subagent workflows,
  Git/worktree operations, telemetry surface, and duplicate skills are excluded.

An adapted research source is provenance, not a runtime dependency or loading route.
