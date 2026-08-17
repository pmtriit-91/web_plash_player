# Universal Agent OS V9.1.0

Agent OS is a portable, repository-local coordination layer for coding agents. Copying
`.agents/` plus the thin root `AGENTS.md` bridge into a repository installs the release;
it does not bind that release to the application automatically.

## Architecture

1. `AGENTS.md` and `core/` define the boot and safety kernel.
2. `routing/` selects one workflow and at most one primary capability.
3. `skills/` contains small release skills; `skills/project-memory/` is application-owned.
4. `vendor/` contains only commit-pinned, license-approved, hash-locked files.
5. `project/` contains the application-owned adapter; `_tools/` validates lifecycle state.

`project-template/documentation-map.md` is a non-authoritative scaffold for projects
that need to establish or repair their own documentation information architecture.
Agents consult an adapted project-local map only before durable documentation
mutation; Core never parses it as boot, binding, lifecycle, roadmap, or project truth.

The exact ownership boundary is machine-readable in
`core/contracts/ownership-policy.json`. The release manifest intentionally excludes
`project/**`, `skills/project-memory/**`, `skills/project-local/**`, and runtime output.

## Derived state

Run:

```bash
python3 .agents/_tools/agent_os_lifecycle.py doctor
```

- `UNBOUND`: no valid Project Adapter; audit and integrity operations only.
- `BOUND`: Core, bridge, and Project Adapter all validate.
- `DEGRADED`: an expected component exists but fails validation or integrity.

State is derived from evidence and is never declared by a static Markdown status file.
Project context has a second diagnosis after `BOUND`: `FRESH`, `STALE`,
`DEGRADED`, or `UNCONFIGURED`. Only `FRESH` permits Project Memory authority.

## Active authorities

- `routing/workflow-registry.json`: workflow selection.
- `routing/capability-registry.json`: compact trigger/load map.
- `routing/capability-descriptors.json`: active capability purpose, lifecycle,
  permissions, risk, provenance, eval, and routing examples.
- `routing/capability-policy.json`: hard routing and activation policy.
- `routing/capability-decisions.json`: append-only integration rationale.
- `routing/capability-lifecycle.json`: append-only integration, state, and rollback
  receipts for the active portfolio.
- `evals/capability-lifecycle-routing.json`: shadow routing evidence added by
  approved integrations.
- `vendor/vendor-lock.json`: vendor provenance and exact file hashes.
- `_manifest/base-release-manifest.json`: release-owned file integrity.
- `project/project-binding.json`: application identity, workspaces, evidenced
  commands, and context entrypoints.
- `project/adapter-fingerprint.json`: canonical digests for binding-critical
  identity, commands, and context pointers.

Markdown catalogs are explanatory views. They do not activate skills.

## Validation

```bash
python3 .agents/_tools/agent_os_lifecycle.py verify-core
python3 .agents/_tools/agent_os_lifecycle.py verify-adapter
python3 .agents/_tools/agent_os_lifecycle.py verify-vendors
python3 .agents/_tools/agent_os_lifecycle.py validate-skills
python3 .agents/_tools/preflight.py --validate-paths
python3 .agents/_tools/validate-routing-sync.py
python3 .agents/_tools/agent_os_resolver.py validate-catalog
python3 .agents/_tools/run-agent-os-evals.py
```

## Explainable capability routing

The V2 resolver first excludes inactive capabilities, then combines deterministic
trigger evidence with small semantic descriptor metadata. It chooses one primary
capability and returns confidence, evidence, alternatives, permissions, and explicit
exclusions. Low-confidence work falls back to `standard_feature` and emits a
capability-gap event for later research; it never downloads a skill while resolving
the current task.

```bash
python3 .agents/_tools/agent_os_resolver.py list
python3 .agents/_tools/agent_os_resolver.py show --capability notebooklm_research
python3 .agents/_tools/agent_os_resolver.py explain --capability notebooklm_research
python3 .agents/_tools/agent_os_resolver.py simulate --prompt "compare research sources"
```

These views are generated from JSON authority rather than a second hand-maintained
skill catalog. The local read-only MCP exposes equivalent list, show, simulate, and
catalog-validation operations.

## Skill Research Lab

`research/**` is deliberately separate from active routing and vendor provenance.
The static research engine can inspect a pinned snapshot, license, file hashes,
symlinks, executable content, prompt injection, competing frameworks, portfolio
overlap, and positive/negative shadow prompts without running upstream code:

```bash
python3 .agents/_tools/agent_os_research.py status
python3 .agents/_tools/agent_os_research.py validate-registry
python3 .agents/_tools/capability_research/test_remaining_contracts.py
```

GitHub, NotebookLM, local snapshots, and MCP indexes are optional discovery signals.
Their health cannot affect boot or existing capability routing. Discovery never means
installation, approval, activation, commit, or release.

Transient candidate states and research receipts live under ignored
`_runtime/research/**`. The empty release registry is a portable seed, not the
operational discovery database. An approved integration moves only the durable active
decision, provenance, eval, lifecycle receipt, and governed bytes into release
authority.

## Control Center and unified CLI

The local Control Center presents health, capability cards, research inbox, approval
queue, routing simulation, settings, update state, Context Memory readiness, and
diagnostics without a Node or cloud dependency:

```bash
python3 .agents/_tools/agent_os_cli.py doctor
python3 .agents/_tools/agent_os_cli.py skills list
python3 .agents/_tools/agent_os_cli.py skills simulate "audit Agent OS integrity"
python3 .agents/_tools/agent_os_cli.py settings serve
```

CLI, MCP, and UI read the same Python domain service. Control Center binds only
`127.0.0.1`, uses an expiring session token, strict origin/Host checks, CSP, and no
CDN. Settings and capability mutations are two-phase: generate a plan with exact
diff/HEAD/hashes, then explicitly approve apply. It does not commit or push. MCP
remains read-only.

## Publication readiness

Public publication is not implied by a verified private release. Maintainers can run
the local, read-only gate without contacting GitHub or changing state:

```bash
python3 .agents/_tools/agent_os_cli.py publication audit
```

The result separates automatic blockers from manual gates. It checks for an explicit
project license, `SECURITY.md`, governed third-party notices, immutable external
workflow action SHAs, vendor/research provenance, tracked secret signatures, and
client evidence. `publication_ready` remains false even after engineering checks pass
until host visibility/security settings and owner approval are separately recorded.
The audit reports only a secret rule and path, never a matching value.

## Autonomous capability lifecycle

An agent can prepare candidate and assembly JSON, then request one reviewed apply:

```bash
python3 .agents/_tools/agent_os_cli.py skills plan-integration \
  --candidate /path/to/candidate.json --assembly /path/to/assembly.json
python3 .agents/_tools/agent_os_cli.py skills apply-integration \
  --plan PLAN_ID --confirm
```

The plan binds Git HEAD, policy/eval hashes, protected application digest, candidate
hash, expiry, exact before/after bytes, and exact multi-file diff. Apply uses a global
lock, writes the manifest last, verifies all bytes, and restores the prior tree after
any failure. An interrupted transaction blocks new applies until explicit recovery:

```bash
python3 .agents/_tools/agent_os_cli.py lifecycle status
python3 .agents/_tools/agent_os_cli.py lifecycle recover --confirm
```

Update checks do not replace the active pin. Deprecation/disable/manual-only changes
and compensating rollback also use reviewed plans. Usage receipts store an HMAC task
hash and redacted metadata, never the raw prompt. `project-local`, `research-only`,
and rejected candidates cannot enter the universal active portfolio.

An integration apply generates a `working-baseline` manifest so Core remains
internally consistent. It does not claim a verified release: the separate content
commit and generated manifest commit are still required.

## Project Genesis

Core ships the Genesis schemas, lifecycle doctor, transaction engine, and an empty
`unbound-consumer` template. Each application owns its actual
`project/genesis.json`, durable confirmation ledger, and bounded boot projection;
those paths never enter a release manifest.

```bash
python3 .agents/_tools/agent_os_cli.py genesis doctor
python3 .agents/_tools/agent_os_cli.py genesis plan-migration
python3 .agents/_tools/agent_os_cli.py genesis apply-migration --plan PLAN_ID --confirm
python3 .agents/_tools/agent_os_cli.py genesis plan-confirmation --input /path/to/candidate.json
python3 .agents/_tools/agent_os_cli.py genesis apply-confirmation --plan PLAN_ID --confirm
python3 .agents/_tools/agent_os_cli.py genesis projection
python3 .agents/_tools/agent_os_cli.py genesis recover --confirm
```

Migration approval only materializes or upgrades a draft. Owner semantic
confirmation is a separate exact-delta transaction bound to Git HEAD, verified
Project Binding and fingerprint, revision, source/evidence hashes, and a durable
claim-basis receipt. Missing, draft, stale, conflicting, contaminated, or
projection-mismatched Genesis data is never loaded as constitutional truth.
Transactions keep runtime backups and write-ahead receipts, verify with the source
doctor after atomic writes, roll back failures, and never commit or push.

## Universal Context Memory

Core ships the Context Memory engine, hard policy, schemas, and initialization
templates. Actual hot/warm/cold stores, active tasks, handoffs, and the generated
Project Memory projection remain application-owned and are excluded from release
manifests.

```bash
python3 .agents/_tools/agent_os_cli.py memory doctor
python3 .agents/_tools/agent_os_cli.py memory load --tier hot
python3 .agents/_tools/agent_os_cli.py memory initialize
python3 .agents/_tools/agent_os_cli.py memory refresh
python3 .agents/_tools/agent_os_cli.py memory propose /path/to/record.json
python3 .agents/_tools/agent_os_cli.py memory apply --plan PLAN_ID --confirm
```

The context manifest indexes canonical project-owned stores and their hashes instead
of copying the same facts into multiple Markdown files. Hot context contains only
identity/current state/critical guardrails; warm context is loaded just in time;
cold context holds research/history. NotebookLM is limited to cold research-only
authority.

Every record cites current evidence hashes. Wrong-project/remote data, same-rank
authority conflicts, stale sources, overlapping active-task scopes, and stale task
base commits are diagnosed before mutation. Task claims and hash-verifiable handoffs
use the same two-phase transaction model. Compaction summarizes and archives cold
research/history without deleting originals or touching active decisions.

Raw conversations, prompts, scratchpads, and chain-of-thought are rejected. The
generated `skills/project-memory/SKILL.md` is a small hot/warm projection, not the
database. MCP exposes diagnosis/load/tasks/handoffs read-only; CLI and Control Center
own reviewed writes and never commit or push.

Compaction is validated as a canonical semantic transition, not merely a self-hashed
plan: selected active cold research/history records remain byte-equivalent except
for archive status/time, all unselected records remain exact, one summary is added,
and the manifest is re-derived from the resulting stores. The projection is excluded
from compact changes and is independently re-rendered by the doctor. If projection
bytes alone are missing or non-canonical, `memory refresh` returns a reviewable
single-file `repair-projection` plan.

After an explicitly approved binding edit, regenerate its fingerprint and verify
the adapter. Then require a `FRESH` Context Memory diagnosis before treating Project
Memory as authority:

```bash
python3 .agents/_tools/agent_os_lifecycle.py build-adapter-fingerprint --confirm
python3 .agents/_tools/agent_os_lifecycle.py verify-adapter
```

Fingerprint generation validates root markers, workspaces, package-script evidence,
context paths, project association, timestamps, and secret/path hygiene before an
atomic write. A fingerprint is freshness/integrity metadata, not project identity by
itself.

## Continuity retention and offline portability

Continuity retention is policy-driven and fail-closed. `critical-active`, live
required/state-aware references, dependency targets, completion evidence, and
recovery-pinned artifacts are held automatically. Archive copies exact verified
bytes into an application-owned deterministic artifact; it does not delete or
replace the source and its summary is only a projection.

Generation 1 implements retention inspection and explicitly selected archive only.
It reports `prune_eligible=false` for every reference; declared `age` and `count`
modes are future policy vocabulary, not active thresholds or automatic deletion.
An archive receipt is `durable-verified` and must reopen the canonical archive,
its exact file set, payload hashes, and reachable Git provenance.

```bash
python3 .agents/_tools/agent_os_cli.py continuity retention
python3 .agents/_tools/agent_os_cli.py continuity plan-archive /path/to/reference-ids.json
python3 .agents/_tools/agent_os_cli.py continuity apply-archive --plan PLAN_ID --confirm
```

Offline export uses a deterministic directory bundle with a strict manifest,
provider-driven transitive source closure reconstructed from an exact Git-reachable
commit, byte hashes, portable paths, project Binding and Adapter fingerprint.
Self-consistent manifest rehashing cannot add, omit, or rewrite that closure.
Every closure byte must already be Git-durable. The destination itself must be
absent; its parent must already exist and remain a real non-symlink directory through
publish. Git provenance uses bounded literal path lookups plus bounded scoped-prefix
enumeration; filesystem traversal counts every visited file, directory, and ignored
entry, so non-JSON clutter or empty directory trees cannot bypass the policy budget.
Inspect is integrity-only; authority is established only after a compatible target
accepts and verifies a restore. An export receipt is `external-unverified`
provenance and retains a bounded inline manifest snapshot so its exact Git closure can
be reopened; it is not durable proof that the external directory still exists.
If archive/export fails after publish, success is reported as rolled back only when
both the false receipt and published artifact are verified absent. Partial cleanup has
its own incomplete-rollback reason and state flags.

```bash
python3 .agents/_tools/agent_os_cli.py continuity plan-export --destination /path/to/bundle
python3 .agents/_tools/agent_os_cli.py continuity apply-export --plan PLAN_ID --confirm
python3 .agents/_tools/agent_os_cli.py continuity inspect-bundle --source /path/to/bundle
python3 .agents/_tools/agent_os_cli.py continuity plan-restore --source /path/to/bundle
python3 .agents/_tools/agent_os_cli.py continuity apply-restore --plan PLAN_ID --confirm
```

Restore rejects a wrong project, changed Binding/fingerprint/Core, tampered or extra
payload, path escape, symlink, supported secret/prompt/reasoning signatures, stale
target, and provider-mode escalation before write. These privacy fields attest to
the defined scanner and structured-field contract; they are not a general secret or
steganography detector. Core and identity entries are verify-only. Mutable
application targets are backed up into an application-owned durable directory before
atomic replacement. A successful receipt is `rollback_ready` and must reopen that
backup through a non-symlink application-owned root and bind project identity plus all
six contract hashes to exact reachable Git blobs. It does not claim a rollback already
occurred. On failure, exact recovery is reported separately as `rollback_verified`;
incomplete recovery fails with a distinct reason code and explicitly reports whether
the false receipt was removed. Neither export nor restore
commits or pushes. W5 exposes write adapters through CLI only; it does not add an MCP
mutation surface. Reopening a successful receipt proves the retained before-image,
not that restored targets have remained unchanged after the receipt was created.

## Cross-project clients and migrations

Codex uses the canonical `AGENTS.md` bridge. Optional client shims are selected from
`project-template/client-bridges.json`; their generated catalog can be rebuilt with:

```bash
python3 .agents/_tools/agent_os_clients.py render-readme --confirm
python3 .agents/_tools/package-release.py --destination /tmp/release \
  --client claude-code --client gemini-cli --confirm
```

Thin shims redirect to `AGENTS.md` and add no policy. A shim marked
`client-dependent` or `evidence-required` is not a claim that every client version
will auto-discover it.

Legacy V8 and V9 working-baseline consumers migrate through a separate reviewed
transaction:

```bash
python3 .agents/_tools/agent_os_cli.py migration inspect
python3 .agents/_tools/agent_os_cli.py migration plan --source /path/to/release/.agents
python3 .agents/_tools/agent_os_cli.py migration apply --plan PLAN_ID --confirm
```

Migration rejects dirty repositories, unverified sources, stale plans, altered
protected bytes, and root bridges requiring a manual merge. It backs up every
release-owned target byte, verifies the new Core, and supports explicit rollback.
Portable path validation applies the same Windows/POSIX rejection rules regardless
of the host running the tool.

## Transactional updates

Inspect a candidate `.agents` release without applying it:

```bash
python3 .agents/_tools/agent_os_lifecycle.py plan-update --source /path/to/candidate/.agents
```

The planner verifies the candidate manifest, rejects protected application paths,
reports release-only changes and dirty ownership scopes, hashes the current
application-owned inventory, and returns a deterministic `plan_id`. It performs no
writes. A `working-baseline` source remains unverified provenance.

Apply an unchanged, ready plan only after reviewing its exact diff:

```bash
python3 .agents/_tools/agent_os_lifecycle.py apply-update \
  --source /path/to/candidate/.agents --plan-id PLAN_ID --confirm
```

Apply writes only release-owned paths, copies the source manifest last, verifies Core
and protected application inventory, and automatically restores its backup on any
failure. A successful transaction returns an ID that can be explicitly rolled back:

```bash
python3 .agents/_tools/agent_os_lifecycle.py rollback-update \
  --transaction-id TRANSACTION_ID --confirm
```

Backups and receipts live under ignored `_runtime/updates/**`. Apply and rollback do
not stage, commit, push, publish, or execute Project Adapter commands.

The local MCP adapter is read-only and exposes the same validation engine. Historical
release documents live under `_manifest/legacy/` and are not current instructions.
