# Project documentation map template

This file is a release-owned scaffold, not project authority and not a required boot
dependency. A consumer project may adapt it into an application-owned documentation
map such as `docs/README.md`, `documentation/README.md`, or another path declared by
its repository instructions.

Do not copy placeholder facts into Project Memory, Project Genesis, a roadmap, or
current status. Inventory the real repository before adapting this template.

## Scope

The adapted map should answer:

1. Which artifact owns each documentation concern?
2. Which path should an agent update when that concern changes?
3. When may an agent create a new file or directory?
4. Which machine-readable authority must remain separate from human documentation?

The map owns placement and navigation only. It must not become a second roadmap,
current-state record, task ledger, decision database, or verification authority.

## Project-local authority matrix

Replace every placeholder with current repository evidence.

| Concern | Canonical authority | Update trigger | Forbidden duplication |
| --- | --- | --- | --- |
| Mission and product truth | `<genesis-or-project-definition>` | Owner-confirmed constitutional change | Roadmap or status copy |
| Roadmap and dependency order | `<roadmap>` | Approved sequence or exit-gate change | Per-phase roadmap copy |
| Verified current state | `<current-status>` | Verification changes actual state | Future plan |
| Phase or milestone plan | `<phase-or-milestone-path>` | Scope, boundary, or gate change | Task ledger copy |
| Architecture decisions | `<decision-authority>` | Accepted/superseded decision | Unlinked analysis |
| Task ownership and scope | `<machine-task-ledger>` | Claim, block, completion, or handoff | Markdown task database |
| Verification evidence | `<evidence-path-or-system>` | Claim-specific evidence created | Documentation-only proof |
| Handoff | `<machine-handoff-authority>` | Cross-session/agent continuation | Raw conversation |
| Research policy and trace | `<research-authority>` | Research boundary or limitation changes | External answer as truth |

## Directory roles

Document every durable documentation directory with:

- concern and owner;
- required versus conditional artifacts;
- naming convention and stable identifiers;
- update and retirement conditions;
- links to machine-readable authority where applicable.

Prefer a small taxonomy that matches the repository. Do not force a `docs/` directory
onto a project that already has a coherent documentation system.

## Placement workflow

Before creating, renaming, or moving durable documentation:

1. read repository instructions, durable-work governance, and the adapted map;
2. classify the content before choosing a path;
3. find the current authority and inbound references;
4. update or supersede the current artifact instead of creating `copy`, `final`, or
   `final-v2`;
5. define a stable path, lifecycle, owner, and consumer for any new artifact;
6. keep raw prompts, conversations, chain-of-thought, secrets, caches, and ordinary
   command output outside durable documentation;
7. review link integrity, authority duplication, historical references, and required
   machine records before completion.

Moving a historical artifact requires a migration map, inbound-link repair, explicit
supersession where semantics change, and revalidation of affected hashes or receipts.
Cosmetic normalization alone is not sufficient reason to move it.

## Missing-map behavior

Absence of an adapted project map must never make Agent OS boot fail, change lifecycle
state, or block unrelated code work. When a task actually creates or restructures
durable documentation and no map exists:

1. inventory current documentation and repository instructions;
2. infer the smallest concern/authority matrix supported by evidence;
3. adapt this scaffold only when the task authorizes documentation governance;
4. otherwise update the safest existing authority and report the missing map as a
   follow-up.

Core, routing, and lifecycle tools must not parse the adapted map as project truth.
