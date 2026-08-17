---
name: agent-os-maintenance
description: Audit, repair, curate, or update a repository-local Universal Agent OS. Use when work targets `.agents`, Agent OS lifecycle or integrity, project binding, client boot bridges, vendor skills, skill provenance, or cross-project contamination.
---

# Agent OS Maintenance

Preserve universality, project isolation, and reviewable Git history while
changing Agent OS.

## Procedure

1. Run the read-only lifecycle doctor before planning a change.
2. Classify every target with the ownership policy:
   - release-owned Core, routing, tools, templates, and governed vendor files;
   - repository-owned `project/**`, `skills/project-memory/**`, and
     `skills/project-local/**`;
   - ephemeral runtime output.
3. Treat repository-owned files as a preservation boundary. Do not rewrite,
   normalize, relocate, or delete them during a Core update.
4. Challenge the proposal against boot reliability, context economy, client
   portability, update recovery, licensing, and supply-chain risk.
5. Prefer one canonical lifecycle implementation with CLI and MCP adapters.
6. Before an Agent OS major-phase release, final handoff, or dependent-phase open,
   resolve the reviewer workflow and apply the cumulative phase review gate declared
   by project governance. Do not treat the skill, report presence, or a prior
   workstep review as gate authority.
7. Before release-owned mutation, apply the repository Capacity Gate. Keep one
   behavior concern per task, list exact release-owned paths, and count generated
   manifest/projection/receipt paths separately from source. If the declared scope,
   size, case, runtime, or checkpoint ceiling is crossed, return `STOP_AND_SPLIT`,
   preserve/inventory current bytes, and hand off or supersede the oversized claim.
   Require a caller-supplied capacity envelope and primitive admission before source
   mutation; missing or invalid admission is `STOP_AND_SPLIT`, with no inferred or
   waived threshold. If a declared path is `.agents/_tools` or below it, require
   `root_cardinality` from the same resolved base. Accept an exact-name exception
   only for a stable public entrypoint or global runner whose owner, role, and nested
   caller path were already committed in topology at the Git base; a self-authorized
   worktree exception is `STOP_AND_SPLIT`.
8. Validate changed skills and routing, then rebuild and verify the release
   manifest only after the tree passes a purity audit.
9. Report the exact Git diff. Never stage, commit, push, deploy, or use
   destructive Git cleanup without a separate explicit user request.

## Vendor import gate

Accept a vendor skill only when all conditions pass:

- an explicit redistribution-compatible license exists;
- the source is pinned to a full commit hash;
- imported paths are allowlisted;
- skill instructions and bundled scripts pass static safety review;
- discovery behavior and integration are validated;
- the skill does not introduce a competing router, hook, memory system, or
  client-global installer.

Preserve accepted vendor files byte-for-byte. Put Agent OS policy in the
routing registry and vendor lock, not inside upstream skill content.

## Research policy

Use current repository evidence as authority. NotebookLM, GitHub Trending,
stars, and external catalogs are discovery and critique inputs only. Reject any
recommendation that conflicts with current Git evidence, license terms, or the
ownership boundary.
