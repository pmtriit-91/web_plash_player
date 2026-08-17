# Agent OS local MCP contract — V9.1.0

Run the optional stdio server with:

```bash
python3 .agents/_tools/agent_os_mcp_server.py
```

## Trust boundary

The server is read-only. It must not write manifests, bindings, memory, telemetry,
source files, Git state, client configuration, or dependencies. All paths remain
repository-relative and deterministic checks delegate to the canonical lifecycle
and routing tools.

## Tools

- `agent_os/doctor` (includes Project Genesis source/projection health)
- `agent_os/verify_core`
- `agent_os/verify_adapter`
- `agent_os/verify_vendors`
- `agent_os/validate_skills`
- `agent_os/run_preflight`
- `agent_os/validate_routing`
- `agent_os/resolve_routing`
- `agent_os/list_capabilities`
- `agent_os/show_capability`
- `agent_os/simulate_routing`
- `agent_os/validate_capability_catalog`
- `agent_os/research_status`
- `agent_os/validate_research_registry`
- `agent_os/effective_settings`
- `agent_os/capability_lifecycle_status`
- `agent_os/usage_review`
- `agent_os/show_candidate`
- `agent_os/context_memory_doctor`
- `agent_os/context_memory_load`
- `agent_os/context_memory_tasks`
- `agent_os/context_memory_handoffs`
- `agent_os/client_bridges`
- `agent_os/migration_inspect`
- `agent_os/publication_audit`

Each tool returns structured JSON with `ok` and task-specific details. `doctor` may
truthfully return `ok: false, state: UNBOUND` when no Project Adapter exists. This is
an expected safe state, not an MCP transport error.

Lifecycle writes such as manifest creation remain CLI-only and require explicit
`--confirm`. Project command execution is intentionally outside this MCP surface.

Capability responses are projections of the descriptor, policy, decision, routing,
and vendor authorities. They may explain or simulate a selection but cannot activate,
install, integrate, edit, or fetch a capability.

Research status does not probe GitHub, NotebookLM, local indexes, or MCP servers. It
reports connector configuration as `not-probed`; connector failure is isolated from
boot and active routing. Candidate discovery and every integration write remain
outside the early MCP surface.

Context Memory tools diagnose and read only; they never apply a proposal. Client
bridge listing is generated from the registry. Migration inspection reports only the
current repository family and guards. Migration plan/apply/rollback remain CLI-only
because they require transaction approval semantics.

Publication audit checks local license, disclosure, third-party notice, immutable CI
pin, provenance, secret-signature, client-evidence, and manual-gate state. It never
contacts a host, reports a matching secret value, publishes, or converts engineering
readiness into owner approval.
