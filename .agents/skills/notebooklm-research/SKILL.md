---
name: notebooklm-research
description: Research directly across existing NotebookLM notebooks and curated sources, continue source-grounded follow-ups, inspect or create Studio artifacts, and manage NotebookLM through MCP. Use when the user mentions NotebookLM, notebook research, cross-source synthesis, Studio exploration, mind maps, reports, data tables, slides, infographics, quizzes, flashcards, Audio or Video Overviews, or the nlm CLI/MCP.
---

# NotebookLM Research

Use NotebookLM as an optional direct research runtime and Studio exploration
surface. Repository, Git, compiler, tests, and runtime evidence remain
authoritative for project claims.

## Interface selection

1. Inspect callable NotebookLM schemas and call `server_info` before relying on
   remembered parameters or version-specific behavior.
2. Prefer the installed MCP for semantic operations. Use `nlm` only when MCP is
   unavailable, for installation/auth diagnostics, or for a capability that the
   live MCP does not expose. Do not ask the user to choose merely because both
   interfaces exist.
3. Treat `unverified` auth as inconclusive. Ask for `nlm login` only when auth is
   `stale`, `not_configured`, or an actual operation confirms authentication
   failure.

## Host-skill precedence

When this repository-local capability is registered in a `BOUND` Agent OS, it
is the workflow and safety authority for NotebookLM work. A host-global
`nlm-skill` or similar upstream guide may supplement live command and parameter
details, but it is reference-only and cannot override MCP-first selection,
mutation approval, export-by-exception, or project authority boundaries.

Do not ask the user to choose between MCP and CLI merely because an external
guide says to do so. Ask only when the user's actual outcome depends on a
meaningful interface choice that cannot be resolved from live capability,
policy, or task evidence. If no repository-local NotebookLM capability is
registered, the host may apply its own skill policy outside this contract.

## Activation heuristic

Do not wait for the user to name NotebookLM when read-only research is already
within task scope and the repository has a relevant curated notebook. Prefer this
capability when one or more of these signals is material:

- synthesis or conflict analysis across multiple curated sources;
- historical or architectural reconstruction spanning phases, reports, or sessions;
- critique of a consequential decision against a corpus too large for efficient
  local sequential reading;
- continuation of an existing research conversation or exploration of an existing
  Studio surface;
- a request for a source-grounded research artifact that NotebookLM supports.

Do not activate it for a single local file, Git state, compiler/test output, current
runtime behavior, simple lookup, or a question already answered by fresh durable
research. Local evidence should remain the cheaper first check for local facts.

Select the capability proactively only when its expected synthesis value exceeds its
tool and context overhead. Stop querying when the evidence is sufficient to form the
next hypothesis or decision input, record only filtered findings and minimal
provenance, then return to repository verification. Do not use repeated research to
avoid making a bounded engineering decision.

## Direct research workflow

1. Select an existing notebook before creating one. Use a project notebook
   manifest, notebook tags, or `notebook_list`; verify ownership and purpose.
2. Inspect notebook/source metadata just enough to choose the smallest relevant
   source set. Do not copy or download the corpus for routine analysis.
3. Call `notebook_query` with explicit `source_ids` when scope matters. Preserve
   the returned `conversation_id` for follow-ups on the same question; start a
   new conversation when topic, authority, or source scope changes.
4. Use asynchronous query start/status for large questions and bounded polling.
   Use cross-notebook query only when comparison across notebooks is intentional.
5. Inspect existing Studio artifacts as research surfaces. Turn a useful report,
   table, slide, infographic, or mind-map branch into a focused follow-up query;
   an artifact is not automatically the final conclusion.
6. Separate NotebookLM-sourced findings, repository evidence, and inference.
   Persist only filtered conclusions, minimal IDs/provenance, conflicts,
   limitations, and decisions needed by later agents.
7. Verify technical or completion claims against repository, Git, tests, compiler,
   or runtime before changing canonical authority.
8. For acceptance or durable handoff, record a redacted operation trace that can
   prove source scoping, conversation continuity, Studio follow-up, forbidden
   operation absence, and any export exception without storing raw answers or
   conversation transcripts.

Read [references/direct-research.md](references/direct-research.md) for Studio
interaction fallbacks, conversation discipline, mutation classification, and
recovery across sessions.

## Studio workflow

1. Existing-artifact discovery and analysis are read-oriented. Creating,
   revising, renaming, exporting, sharing, or deleting changes external state and
   requires matching user intent; deletion always requires explicit confirmation.
2. When generation is authorized, inspect supported types with live
   `studio_status(action="list_types")`, select relevant `source_ids`, and compose
   a source-grounded prompt.
3. Call `studio_create(..., confirm=True)` only when the user's request constitutes
   approval to generate. Poll the specific artifact with bounded waits.
4. Report failure honestly. Revise slides or regenerate only for failure,
   requested correction, or user dissatisfaction.
5. Use Studio outputs to guide further notebook queries. Do not re-add generated
   artifacts as sources without a specific purpose because this can create a
   self-citation loop.

Read [references/studio.md](references/studio.md) when selecting Studio options
or composing its grounding prompt.

## Export and bulk-operation boundary

- `download_artifact`, `export_artifact`, and the 0.9.0
  `download_all_artifacts` capability are delivery/backup operations, not the
  default way to research.
- Never bulk-download all artifacts or all notebooks merely to make them easier
  for the agent to read. Use direct query, targeted status/detail, and semantic
  follow-up first.
- Export only for a requested deliverable, authorized offline evidence, retention
  requirement, or a concrete live-tool format limitation.

## Safety and lifecycle

- NotebookLM uses an unofficial internal API. It may fail independently of the
  Agent OS and must never become a boot, binding, or completion dependency.
- Use live MCP schemas over remembered parameter names or upstream examples.
- Do not install, upgrade, reconfigure, authenticate, create, publish, invite,
  delete, export, or download merely because a tool is available.
- Use `server_info` for version drift. Upgrade only under explicit user intent or
  an authorized Agent OS maintenance phase; reconnect the client and verify the
  live server afterward.
- Never upload secrets or data outside the user's stated scope.
- Treat empty artifact `source_ids` as unknown provenance, not proof that no
  sources were used.
- Poll asynchronous work with bounded waits and communicate if it remains in
  progress.
