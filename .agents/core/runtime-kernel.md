# Runtime Kernel — V9.1.0

## Mission

Preserve agent intelligence while reducing orchestration overhead, without
sacrificing evidence, human control, project isolation, or safe transactions.

## Invariants

1. Core is project-agnostic. Real project facts belong only to application-owned
   Adapter scopes.
2. State is derived from current evidence; it is never trusted as a mutable
   status flag.
3. Read-only diagnostics remain available in every state.
4. Adapter commands require `BOUND`; Project Memory authority additionally
   requires a project-bound Context Memory result of `FRESH`.
5. Core integrity and Adapter validity are independent checks.
6. Git HEAD is freshness metadata, never project identity.
7. Core update writes are restricted to release-owned manifest paths.
8. MCP and NotebookLM are optional interfaces, never boot dependencies.
9. Routing has one active registry per domain. Vendor meta-routers remain
   inactive.
10. Stable OS and Adapter files remain Git-trackable; only explicit runtime
    output is ignored.
11. Actual context records, task ledgers, handoffs, and memory projections are
    application-owned. Core owns only their engine, policy, schemas, and templates.
12. Raw conversations and chain-of-thought are not Context Memory records.
    NotebookLM remains a cold research surface and cannot become boot authority.
13. Project Genesis is the application-owned constitutional authority only when its
    derived source state is `confirmed` and its bounded projection matches revision
    and source hash. Project Binding establishes identity; Context Memory preserves
    operations; neither silently substitutes for Genesis.
14. Genesis migration permission creates or upgrades a draft only. Owner semantic
    confirmation is a separate evidence-bound transaction with a durable
    application-owned receipt.
15. A dependent major phase cannot open, release, or receive final handoff while its
    declared cumulative phase review gate is missing or
    `REMEDIATION_REQUIRED`. The project work-governance record remains normative;
    boot and reviewer workflow are enforcement projections, not competing authority.
16. An implementation task governed by a repository Capacity Gate cannot mutate
    source without a bounded task envelope. Crossing a declared scope, size, case,
    runtime, or checkpoint threshold requires `STOP_AND_SPLIT`; boot, planning, and
    review only enforce the project authority and never create a competing threshold.
17. Hosted verification is a scarce final evidence surface, not a debugging loop.
    A failed hosted tuple must not be rerun blindly or retried automatically. Triage
    starts from a bounded compact summary, uses only targeted log excerpts when that
    summary is insufficient, and returns to focused local reproduction and the full
    relevant local acceptance path before one evidence-bound hosted dispatch.

## Derived states

### `UNBOUND`

No valid project binding exists. Allow audit, diagnostics, and an explicitly
authorized initialization or repair. Block project-context authority, Adapter
commands, and normal project mutation.

### `BOUND`

Core integrity, client bridge, binding schema, repository identity, command
evidence, and Adapter checks pass. Capabilities become eligible but remain
subject to user intent and tool safety.

### `DEGRADED`

A binding exists but one or more required checks fail, or client discovery
cannot be proven. Allow diagnostics and approved repair transactions. Block
normal project-context authority and mutation.

## Evidence and tools

Prefer current source and low-cost local evidence. Browse current official
documentation when facts may have changed. Use NotebookLM for multi-source
research and critique when useful, then reconcile its output with repository
truth.

Never claim completion from documentation, filenames, a manifest timestamp, or
an external model answer alone. Runtime claims require runtime evidence.
