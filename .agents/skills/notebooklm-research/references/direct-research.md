# NotebookLM direct research reference

Use this reference when NotebookLM is a research workspace rather than only an
artifact generator.

## Authority boundary

NotebookLM answers and Studio artifacts are source-grounded synthesis, not project
truth. Record citations and inference separately. Verify architecture,
implementation, Git state, security, and completion claims with the authoritative
repository, tests, compiler, runtime, or owner-confirmed product contract.

NotebookLM failure must degrade only the optional research capability. It must not
block Agent OS boot, project binding, local inspection, or ordinary implementation.

When a host-global NotebookLM guide overlaps this registered release skill, use it
only for supplemental live tool semantics. The repository-local capability wins on
interface selection, approval, export, provenance, and authority. In particular, an
upstream instruction to ask between CLI and MCP does not override MCP-first behavior
inside a `BOUND` Agent OS.

## Direct-query sequence

```text
server_info + live schemas
        ↓
select existing notebook and verify purpose/ownership
        ↓
inspect source inventory or notebook description just in time
        ↓
choose the smallest relevant source_ids
        ↓
notebook_query
        ↓
reuse conversation_id for focused follow-ups
        ↓
challenge conflicts and unknowns
        ↓
verify technical claims outside NotebookLM
        ↓
persist only filtered conclusions and minimal provenance
```

Use a new conversation when the question, source set, project, authority class, or
decision changes materially. Do not keep unrelated research in one long conversation
only to preserve convenience.

Prefer `notebook_query_start` plus bounded `notebook_query_status` polling for long
queries. Prefer `cross_notebook_query` only when the notebook boundary itself is part
of the comparison; avoid `all=True` by default because it increases rate-limit,
contamination, and context risks.

## Studio as an exploration surface

Studio artifacts can compress a corpus into alternative views:

- report: narrative synthesis and contradiction prompts;
- data table: repeated-field comparison and evidence gaps;
- mind map: topic hierarchy and branch discovery;
- slides or infographic: communication structure and missing causal links;
- quiz or flashcards: recall gaps and ambiguous terminology;
- audio or video: audience-oriented explanation and narrative stress test.

Inspect existing artifacts before generating duplicates. Use their title, status,
source scope, prompt metadata, and visible structure to formulate the next focused
notebook query.

The 0.9.0 MCP does not expose a dedicated method that semantically clicks and expands
an individual mind-map node. Apply this fallback order:

1. use a live Studio/MCP operation when the current schema exposes the interaction;
2. when exact visual node state matters and an authenticated browser is available and
   authorized, inspect or click the Studio UI directly;
3. otherwise take the visible node label and ancestor path as a focused
   `notebook_query`, preserving `conversation_id` when it belongs to the same line of
   inquiry;
4. disclose that the semantic fallback was used.

Do not replace a missing click API by downloading the entire source corpus. A targeted
artifact export is acceptable only when its content cannot be inspected otherwise and
the active task authorizes that external write.

## Read versus mutation

| Operation | Default classification |
| --- | --- |
| `server_info`, list/get/describe/status | Read-oriented |
| `notebook_query`, cross-notebook query | External read/research; keep source scope |
| create notebook, add/import/sync source | External mutation; require matching intent |
| create/revise/rename Studio artifact | External mutation; require generation/edit intent |
| share/invite/public link | External state and access change; require explicit intent |
| delete notebook/source/artifact/profile | Irreversible; require explicit confirmation |
| download/export one artifact | External write; require deliverable/evidence need |
| `download_all_artifacts` or all-notebook sweep | Bulk external write; explicit backup/export intent only |

Do not infer permission for mutation from permission to read or query a notebook.

## Version and session drift

Call `server_info` rather than assuming the globally installed CLI version equals the
live MCP process version. After an upgrade, the long-lived client may keep the prior
server until reconnect or restart. Verify the live version and callable schemas in a
fresh session before claiming an MCP upgrade complete.

For `auth_status`:

- `configured`: proceed;
- `unverified`: try a safe read or diagnose connectivity before re-authentication;
- `stale` or `not_configured`: ask the user to run or authorize `nlm login`;
- `error`: report the health-check failure without exposing credentials.

Never persist cookies, tokens, account identifiers, or raw NotebookLM conversation
history in project memory.

## Durable handoff

When research affects later work, retain only:

- notebook ID/title and verified ownership or purpose;
- selected source IDs or a pinned source manifest;
- query or conversation ID when safe and useful;
- artifact ID/type when it materially informed the finding;
- sourced finding, inference label, conflict, limitation, verification result, and
  next action.

Do not copy the entire notebook, corpus, generated artifact set, raw prompts, or raw
chat transcript into Git.

For behavioral acceptance, a redacted trace may retain operation names, ordering,
source aliases, a non-secret conversation reference, artifact aliases, result state,
and explicit export rationale. It must prove that prohibited downloads or mutations
were absent; it must not preserve answer bodies, credentials, account identifiers,
or raw conversation history.
