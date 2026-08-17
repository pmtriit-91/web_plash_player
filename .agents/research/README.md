# Skill Research and Assembly Lab

This directory contains release-owned policy and empty authority stores for candidate
research. Candidate discovery never activates a skill and never executes upstream
content.

## Authority split

- `connectors.json` declares optional, failure-isolated discovery surfaces.
- `research-policy.json` defines zero-execution provenance, license, security,
  overlap, and approval gates.
- `candidate-registry.json` is an empty portable seed for research views, not the
  operational candidate database or active routing authority.
- `decision-history.json` is the portable seed for curated research decisions.
- `routing/capability-descriptors.json` remains the active runtime portfolio.
- `vendor/vendor-lock.json` remains exact byte provenance for approved vendors.

Operational candidate states, connector receipts, connector health, account-specific
notebook IDs, downloaded snapshots, and transient scan results belong under ignored
`_runtime/research/**`; they are not release authority. Raw prompts are not persisted
by default. Only an approved integration projects durable active facts into routing,
capability decision, lifecycle, eval, and vendor authorities.

## Zero-execution inspection

```bash
python3 .agents/_tools/agent_os_research.py status
python3 .agents/_tools/agent_os_research.py validate-registry
python3 .agents/_tools/agent_os_research.py discover \
  --connector local \
  --source /pinned/static/snapshot \
  --candidate-id example-skill \
  --repository https://example.invalid/repository \
  --commit 0123456789abcdef0123456789abcdef01234567 \
  --positive "A prompt that should select the candidate" \
  --negative "A similar prompt that must not select it"
```

The result is a recommendation only. Missing full commit or vendor-compatible license
blocks vendoring; archives, unsafe symlinks, prompt injection, global installers, and
unauthorized Git/deploy behavior are rejected. Executable content is quarantined and
never run. Competing boot/router/memory frameworks may only yield an adaptation
recommendation, never whole-package import.
