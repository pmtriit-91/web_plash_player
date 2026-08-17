# Agent OS Control Center

Control Center is a dependency-free local web client over the same domain functions
used by the CLI and read-only MCP adapter. It is not part of boot and cannot affect
routing when stopped or broken.

Start it with:

```bash
python3 .agents/_tools/agent_os_cli.py settings serve
```

The server chooses a free port, binds exactly `127.0.0.1`, creates an expiring random
session token, and prints a local URL. It has no CDN, cloud backend, package install,
or background daemon.

## Security boundary

- API requests require a Bearer session token; mutation additionally requires exact
  `Origin` and `Host` checks.
- CSP, frame denial, no-referrer, no-store, and content-type protections are applied
  to every response.
- The UI cannot change hard safety: activation approval stays enabled, while
  background daemon, auto-commit, and auto-push stay disabled.
- The UI never writes authority files directly. A settings change first creates a
  plan with Git HEAD, before/after hashes, protected-scope digest, exact diff, risk,
  and expiry. Apply revalidates them and atomically writes or rolls back.
- Runtime plans and receipts are ignored under their `_runtime/control-center/**`,
  `_runtime/capability-lifecycle/**`, and `_runtime/context-memory/**` domains.

Application-owned settings use the settings transaction service. Capability
integration, state changes, rollback, and crash recovery use the AOS-10 lifecycle
transaction service. Both require a reviewed plan and explicit apply; neither can
commit or push. Update deployment remains the separate release update transaction.
MCP exposes only read projections of these states.

The Context Memory panel shows freshness, authority, hot records, active tasks, and
handoff counts. Initialization, refresh, record proposal, task claim, handoff, and
compaction create review plans; the generic approval queue applies them through the
Context Memory transaction engine. UI code cannot write project memory directly or
promote stale/NotebookLM context to boot authority.
