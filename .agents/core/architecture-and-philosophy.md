# Universal Agent OS architecture and philosophy — V9.1.0

## Prime directive

Agent OS is a project-agnostic coordination system, not a project prompt pack. It
must remain portable across unrelated repositories without carrying local facts,
commands, paths, memory, or business vocabulary.

## Layers

1. **Core:** immutable behavioral and safety constraints.
2. **Routing:** one workflow and at most one primary capability per task.
3. **Project Adapter:** application-owned binding, evidence, commands, and memory.
4. **Skills and vendors:** task-scoped procedures subordinate to Core.
5. **Lifecycle and clients:** deterministic validation plus thin local adapters.

Ownership is structural, not editorial. Core updates exclude `project/**`,
`skills/project-memory/**`, and `skills/project-local/**` from the release manifest.
Client discovery uses a repository-local bridge; the release does not mutate global
client configuration.

## Design rules

- Derive `UNBOUND`, `BOUND`, or `DEGRADED` from validation evidence.
- Keep Markdown policy concise; move deterministic checks into dependency-free tools.
- Maintain one authority per domain: workflow registry, capability registry, vendor
  lock, ownership policy, and release manifest.
- Load less context without lowering the quality floor.
- Treat NotebookLM, trending repositories, and model memory as research inputs only.
- Vendor the smallest reviewed subset and preserve exact provenance.
- Require explicit authorization for write-capable lifecycle operations.

## Upgrade sequence

1. Run `doctor` and inspect Git state.
2. Freeze ownership boundaries and preserve application-owned hashes.
3. Challenge the proposed architecture and supply-chain impact.
4. Make focused release-owned changes.
5. Validate routing, skills, vendors, client adapters, and eval behavior.
6. Build the manifest last with explicit confirmation and a truthful provenance state.
7. Report the diff; do not stage, commit, publish, or modify application bindings
   without separate authorization.
