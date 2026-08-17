# Universal Agent OS changelog

## Unreleased — AOS-15 Durable Context Continuity

- Added a strict application-owned continuity catalog, release-owned record type
  registry/recovery profile, provider-aware doctor, dependency/supersession graph,
  and state-aware authority diagnostics.
- Added reviewed continuity initialize/refresh/migrate/repair/rollback transactions,
  exact source inventory, backup-before-write, atomic replacement, durable receipts,
  and byte-exact failure rollback.
- Hardened Context Memory plans with a derived plan ID, exact operation metadata,
  target allowlists, payload hashes, and re-derived exact diff before apply. Compact
  plans now prove the complete no-delete semantic transition, canonical manifest,
  unchanged projection, unique creator inputs, and summary-ID separation. Context
  Memory doctor verifies canonical Project Memory bytes, while `memory refresh`
  provides an exact one-file `repair-projection` transaction when that projection
  alone is missing or altered.
- Added release-owned retention policy, deterministic no-delete archives,
  exact Git-reachable provider closure for transitive export bundles, bounded
  signature-based privacy/path/byte validation, same-project compatibility gates,
  and transactional restore with Core `verify-only` enforcement.
- Distinguished durable archive receipts from provenance-only external export
  receipts with bounded inline Git-provenance manifests, and made successful restore
  receipts reopen non-symlink durable application-owned backups while binding all
  contracts to exact Git blobs as `rollback_ready`; actual failure recovery uses
  `rollback_verified`, and partial receipt/artifact cleanup has a separate
  incomplete-rollback reason.
- Added executable wrong-project C23, CRLF/binary preservation, storage redirection,
  path/symlink/secret, bounded literal/scoped Git provenance, all-entry directory
  traversal, stale target, concurrent lock, partial-write, and post-receipt rollback
  fixtures. Retention generation 1 remains inspect plus
  explicit no-delete archive; age/count execution and prune are not implemented.
  W5 keeps Windows path-collision hardening, dependency-ordered restore, stale-lock
  recovery, clean-clone, multi-generation, and partial-loss release drills
  explicitly gated to W6.

## V9.1.0 — Portable documentation governance

- Made Project Genesis evidence, confirmation receipts, source guards, and
  projections use Git-canonical bytes for tracked clean paths while preserving raw
  bytes for uncommitted transaction state, so CRLF checkout transforms do not make a
  confirmed Genesis stale.
- Added an enforced `core.autocrlf=true` fresh-clone fixture and corrected the
  Context Memory legacy-history fixture to claim only exact reachable Git-blob
  bytes, even when the working tree uses CRLF.
- Protected telemetry HMAC keys with verified mode `0600` on POSIX and current-user
  DPAPI on Windows; existing raw Windows keys are upgraded in place and any
  protection failure remains fail closed.
- Hardened `verified-release` manifest creation so locator and commit must be
  supplied together, the commit must exist and equal Git `HEAD`, the locator must
  match a configured fetch or push remote, and every release-owned byte must match
  the exact committed snapshot.
- Kept dirty development snapshots available only as `working-baseline`, made
  rejected provenance builds atomic, and required consumers to match
  `created_from_repository_head` with `source_commit` before trusting an update.
- Added conditional provenance schema constraints and ten adversarial release
  fixtures covering fake, ancestor, incomplete, wrong-remote, tracked-dirty,
  untracked-dirty, atomic-failure, working-baseline, and consumer-forgery paths.
- Made release-provenance fixture inputs byte-deterministic instead of relying on
  platform text-mode newline translation, so the fixture tests exact Git bytes on
  Windows without manufacturing CRLF drift after declaring `eol=lf`.
- Added bounded, privacy-filtered aggregate failure diagnostics that retain failed
  child case IDs and structured reason codes while excluding successful child
  records and redacting common sensitive assignments.
- Extended aggregate diagnostics to both `results` and `cases` child schemas,
  added a raw-free Windows DPAPI round-trip probe with bounded error codes, and
  gave the 52-case Genesis adversarial suite a cross-platform 90-second budget.
- Opened telemetry key and JSONL receipt descriptors in binary mode on Windows so
  CRT newline translation cannot corrupt DPAPI ciphertext or exact receipt bytes.
- Made the Genesis transaction fixture claim Git-canonical evidence under an
  explicit `core.autocrlf=true` baseline, while isolating the projection-drift
  adversarial fixture from unrelated checkout normalization.
- Hardened Context Memory and new handoff receipts with exact reachable Git-blob
  evidence binding; uncommitted, missing, unreachable, and hash-mismatched evidence
  now fails closed with structured diagnostics.
- Preserved immutable v1 handoff receipts while resolving only exact bytes in
  reachable history and disclosing unrecoverable historical references; new
  receipts use schema v2 with an explicit evidence commit.
- Added a release-owned documentation-map scaffold without making project
  documentation a Core boot, binding, lifecycle, or project-truth dependency.
- Added task-time planner and reviewer guards for concern classification, canonical
  authority selection, machine/human separation, historical reference safety, and
  final documentation integrity review.
- Added bounded proactive NotebookLM activation for curated multi-source synthesis,
  conflict analysis, historical reconstruction, and large-corpus critique, with
  explicit local-fact and fresh-research exclusions.
- Added positive and negative behavioral fixtures so documentation governance and
  research routing travel with every consumer release.

## V9.1.0 AOS-14 — Project Genesis and Constitution

- Added application-owned Project Genesis lifecycle states, strict schema and
  evidence-bound durable owner confirmation receipts.
- Added an empty release-owned `unbound-consumer` template; the initializer derives
  project identity from a verified Binding and fingerprint instead of copying
  placeholder bytes.
- Added separate two-phase migration, semantic confirmation, and projection
  transactions with exact deltas, HEAD/binding/source guards, write-ahead backups,
  atomic writes, rollback, and explicit crash recovery.
- Added a 64 KiB source-hash/revision-bound boot projection that discloses claim
  values only for confirmed Genesis.
- Added executable lifecycle, authority-forgery, migration, projection,
  cross-domain, package-purity, interruption-recovery, and clean-clone fixtures.
- Kept actual Genesis, confirmation ledgers, and projections outside the universal
  release payload. Permission to continue work or apply a migration is not owner
  confirmation of constitutional product claims.

## V9.1.0 AOS-13.2 — NotebookLM behavioral and host-skill hardening

- Added explicit repository-local precedence over overlapping host-global skills
  while keeping external guides available as reference-only tool documentation.
- Added a machine-readable NotebookLM research trace contract and deterministic
  positive/negative behavioral fixtures for source scope, conversation continuity,
  Studio follow-up, read-only mutation boundaries, and targeted export exceptions.
- Added a live redacted acceptance record for the existing AOS-13 notebook without
  persisting raw answers, conversation history, credentials, or account identifiers.
- Kept AOS-13.1 as a valid prior release while separating routing/integrity evidence
  from end-to-end behavioral acceptance.

## V9.1.0 AOS-13.1 — NotebookLM direct research runtime

- Changed the release-owned NotebookLM skill from artifact-oriented guidance to an
  MCP-first direct research workflow over existing notebooks and curated sources.
- Added source-scoped follow-ups, conversation continuity, Studio exploration, mind
  map semantic/browser fallback, and durable filtered-provenance guidance.
- Kept NotebookLM optional and research-only; repository, Git, tests, compiler, and
  runtime remain authority for project and completion claims.
- Classified Studio generation and external mutation by user intent, with deletion
  requiring explicit confirmation and bulk artifact download reserved for authorized
  delivery or backup rather than routine research.
- Updated inspected upstream provenance to `notebooklm-mcp-cli` 0.9.0 at full commit
  `2f28855b1545ea321568be6e39dc8c2efb338dd5` without vendoring the upstream installer,
  Git workflow, or competing interface-selection policy.
- Added routing and shadow-eval coverage for direct notebook research, Studio branch
  exploration, local-evidence negatives, and unwanted bulk export.
- Host-level CLI/MCP and user-scope skill updates are maintenance evidence only; they
  are not release payload or proof that a live client reconnected successfully.

## V9.1.0 AOS-12.3 — Private-beta hardening

- Added a dependency-free, read-only publication audit that separates automatic
  engineering blockers from host-side checks and explicit owner approval.
- Added a private-beta security disclosure policy and complete notices for governed
  vendored and research sources without selecting a license for Agent OS itself.
- Pinned external GitHub Actions to full commit SHAs, disabled persisted checkout
  credentials, and bounded CI jobs with a timeout.
- Added secret-signature scanning that covers tracked and non-ignored untracked files
  but reports only path and rule, never a matched value.
- Exposed the same audit through the CLI and read-only MCP, added adversarial
  regression coverage, and kept public publication disabled.

## V9.1.0 AOS-12 — Cross-project and cross-client release

- Added three unrelated disposable consumer fixtures that bind a Node monorepo,
  Python service, and documentation site, then recover `BOUND` plus `FRESH` state.
- Added a machine-readable client bridge registry, generated catalog, optional thin
  package shims, and read-only CLI/MCP views; Codex remains the reference client.
- Added transactional V8 legacy and V9 working-baseline migration with dirty-target,
  source provenance, HEAD/hash, protected-inventory, root-bridge, rollback, and
  post-integrity gates.
- Added host-independent path validation for POSIX traversal, Windows drives, UNC,
  mixed separators, home paths, NUL, and symlink-parent escape.
- Removed hard-coded `python3` process launches so the eval/MCP stack uses the active
  interpreter on macOS, Linux, and Windows.
- Added reproducible package byte-tree checks and a three-OS hosted CI matrix.
- Kept non-Codex discovery evidence explicit and separated private-beta readiness
  from public publication.

## V9.1.0 AOS-11 — Universal Context Memory

- Added project-bound hot/warm/cold Context Memory stores with explicit authority,
  evidence hashes, budgets, freshness diagnosis, and contamination protection.
- Added independent `UNCONFIGURED`, `FRESH`, `STALE`, and `DEGRADED` memory states;
  only `BOUND` plus `FRESH` permits the generated Project Memory projection.
- Kept actual records, task ledger, handoffs, and projection application-owned while
  shipping only engine, policy, schemas, templates, clients, and evals in Core.
- Added two-phase initialize, refresh, record proposal, task claim, handoff, and cold
  compaction transactions with Git/target guards, lock, exact diff, and rollback.
- Added overlapping task-scope and stale-base detection plus immutable,
  hash-verifiable handoff receipts for concurrent agents.
- Rejected raw conversations, prompts, scratchpads, and chain-of-thought; restricted
  NotebookLM to cold `research-only` authority.
- Added CLI and Control Center write flows plus read-only MCP diagnosis, tier load,
  task, and handoff projections.
- Added fixtures for fresh recovery, wrong-project/remote contamination, source
  drift, authority conflict, evidence refresh, partial failure, concurrent plans,
  compaction preservation, and projection budgets.

## V9.1.0 AOS-10 — Autonomous capability lifecycle

- Added one-approval transactional integration for eligible `vendor-pin`,
  `adapt-local-skill`, and `adapt-local-principles` candidates without executing
  upstream code.
- Bound plans to Git HEAD, protected application digest, policy/eval hashes,
  candidate hash, expiry, exact diff, and exact before/after bytes.
- Added atomic multi-authority apply, manifest-last verification, automatic
  byte-for-byte failure rollback, write-ahead crash recovery, and compensating
  explicit rollback with preserved history.
- Added update comparison that keeps the old pin active until apply, project
  automatic/manual-only/disabled overrides, lifecycle state changes, and HMAC-based
  redacted usage review.
- Kept operational research candidates and observations runtime-owned; active
  routing, provenance, eval, and lifecycle receipts remain release-owned.
- Added CLI, local Control Center, and read-only MCP projections plus adversarial
  lifecycle, policy, routing, vendor, crash, and transaction coverage.
- Capability apply produces an internally consistent `working-baseline` manifest;
  verified release provenance still requires separate content and manifest commits.

## V9.1.0 AOS-9 — Local Control Center

- Added a Python-standard-library, static, no-CDN Control Center for health, skills,
  research, approvals, routing, automation settings, update state, memory readiness,
  and diagnostics.
- Added a shared domain service and unified CLI so UI, CLI, and read-only MCP project
  the same capability, research, routing, and settings authorities.
- Added localhost-only binding, expiring Bearer sessions, strict Host/origin checks,
  CSP, frame denial, no-referrer, no-store, input bounds, and redacted usage views.
- Added two-phase application-owned settings transactions with clean-Git, HEAD,
  before/after hash, protected digest, expiry, exact diff, atomic apply, receipt, and
  failure rollback checks. Commit and push remain disabled.
- Added disposable tests for stale/concurrent plans, dirty Git, expiry, hard locks,
  rollback, authentication, CSRF/origin, malformed input, UI/domain parity, and
  unsafe network binding.

## V9.1.0 AOS-8 — Skill Research and Assembly Lab

- Added optional GitHub, NotebookLM, local, and MCP-index connector contracts whose
  failures are isolated from boot and active routing.
- Added zero-execution static snapshot inspection for full commit/license provenance,
  file hashes, archives, symlinks, executable content, prompt injection, unauthorized
  mutation, global installers, competing frameworks, and portfolio overlap.
- Added candidate states, positive/negative shadow routing, recommendations, and
  hash-verifiable append-only decision receipt contracts.
- Added an adversarial corpus covering missing licenses, dynamic refs, archives,
  unsafe symlinks, scripts, prompt injection, Git automation, framework conflicts,
  duplicate capabilities, receipt tampering, and offline connector isolation.

## V9.1.0 AOS-7 — Capability contract and Router V2

- Added descriptors for every active local and vendored capability, including
  purpose, counter-examples, lifecycle, integration mode, provenance, permissions,
  risk, token profile, eval state, compatibility, and decision reference.
- Separated routing, vendor-byte provenance, policy, and append-only integration
  rationale instead of treating one registry as every kind of authority.
- Added hybrid deterministic/semantic ranking with confidence, evidence,
  alternatives, lifecycle exclusion, and a safe capability-gap fallback.
- Added CLI and read-only MCP list, show, explain/simulate, and catalog validation.
- Added regression coverage proving complete descriptor/decision coverage, positive
  routing, low-confidence fallback, and operational skill-card data.

## V9.1.0 AOS-6 — Canonical source workspace and transactional update

- Bound the independent source repository without placing maintainer context in the
  distributable release.
- Added deterministic update plan IDs, protected inventory evidence, transactional
  release-owned apply, automatic failure rollback, and explicit rollback receipts.
- Kept Project Adapter, Project Memory, project-local skills, Git operations, and
  publishing outside update authority.
- Added disposable apply/rollback/failure fixtures and canonical source CI.

## V9.0.0 AOS-5 — Read-only update planning

- Added a CLI-only `plan-update` command that verifies an external release manifest
  before computing a release-owned diff.
- Hard-blocked Project Adapter, Project Memory, and project-local skill paths from
  source release manifests independently of source policy claims.
- Added separate dirty release/application reporting and a SHA-256 inventory of
  protected application-owned state.
- Kept update application intentionally unsupported until an independent canonical
  source and transactional migration mechanism are designated.
- Added temporary-fixture evals for clean planning, tampered sources, protected-scope
  injection, and application-state preservation.

## V9.0.0 AOS-4 — Project binding integrity

- Added a machine-readable adapter fingerprint schema and canonical digest builder.
- Strengthened Adapter verification for workspace markers, package-script evidence,
  project association, context entrypoints, timestamps, and fingerprint tampering.
- Made lifecycle eval state assertions portable across unbound and bound deployments.
- Kept binding, fingerprint, Project Memory, and project preferences application-owned
  and outside the Core release manifest.

## V9.0.0 AOS-3.1 — NotebookLM Studio and methodology curation

- Added a concise on-demand NotebookLM research and Studio skill based on live MCP
  schemas and a pinned MIT upstream research revision.
- Recorded research-source provenance separately from byte-for-byte vendor packages.
- Adapted fresh-evidence and review-feedback principles from `obra/superpowers`
  without importing its competing boot, hooks, router, subagent, Git, or telemetry
  framework.
- Added NotebookLM routing and behavioral coverage.

## V9.0.0 — ownership and supply-chain baseline

- Split release-owned Core from application-owned Project Adapter and Project Memory.
- Added derived `UNBOUND`, `BOUND`, and `DEGRADED` lifecycle state.
- Added repository-local client bridge and a read-only MCP adapter.
- Replaced mixed-scope snapshots with a release-only SHA-256 manifest.
- Added exact vendor commit, license, allowlist, and hash verification.
- Removed unlicensed, opaque, duplicated, unsafe, and unregistered skill/tool payloads.
- Curated eight MIT-licensed engineering skills from one pinned upstream revision.
- Added dependency-free routing, lifecycle, firewall, and MCP behavioral evals.

This repository is the canonical Agent OS source. Its designated `origin` is
`https://github.com/pmtriit-91/Universal-Agent-OS.git`; repository visibility remains
a host-side setting and is not proven by this changelog.
