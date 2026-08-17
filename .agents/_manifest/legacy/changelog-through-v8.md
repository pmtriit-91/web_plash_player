# V8.0.7 (MCP Enforcement, Trace Telemetry & Behavioral Evals)

Added & Upgraded:
- Added `_tools/agent_os_mcp_server.py`, a local stdio MCP wrapper exposing preflight, routing validation, routing resolution, summary telemetry, trace recording, and optional skill fetch tools.
- Added `_tools/agent_os_resolver.py` for deterministic workflow and capability resolution from task prompts.
- Added `_tools/trace_collector.py` for redacted trace spans covering routing, skill loading, tool calls, validation, guardrails, and completion events.
- Added `evals/agent-os-evals.json` and `_tools/run-agent-os-evals.py` as the first behavioral eval suite for routing, context firewall, manifest integrity, and MCP wrapper readiness.
- Added `_tools/private_release_snapshot.py` to create manifest-independent private release snapshots for `.agents/` installations that remain intentionally ignored by application Git history.
- Upgraded active Agent OS metadata and routing registries to V8.0.7.
- Extended preflight and routing validation to verify eval registry integrity.

# V8.0.6 Context Firewall & Workflow Router Hardening

Added & Upgraded:
- Added `.agentignore` as the Agent Context Firewall to block high-payload vendor schemas, binary/media/archive files, caches, raw telemetry logs, and generated artifacts from generic context loading.
- Added `routing/workflow-registry.json` as the single source of truth for internal Agent OS workflow selection.
- Separated workflow routing from `routing/capability-registry.json`, preserving capability/skill routing as its own authority.
- Extended `v8_preflight.py` and `validate-routing-sync.py` to validate workflow registry coverage and firewall minimum rules.
- Hardened `run-benchmark.py` with an Agent OS private snapshot guard because `.agents/` is intentionally ignored by Git.
- Normalized MCP telemetry path behavior and documented the `--skip-manifest` routing validation mode.
- Cleaned active runtime documentation drift, stale version headers, phantom creative paths, and outdated root README architecture diagrams.

# V8.0.6 Hardening Patch (Contract & Portability Remediation)

Fixed:
- Removed local absolute paths from Core OS documentation and root portable user guides.
- Standardized the canonical 8 Architectural Invariants across Core OS and evolution history.
- Replaced destructive Subagent rollback wording with safe transaction boundary rules: abort by default on dirty worktree, proceed only with explicit developer-approved stash/checkpoint strategy.
- Rewrote `_ide/mcp-specification.md` as a Professional Technical English MCP contract with stable input/output schemas.
- Upgraded routing validation to include SHA-256 manifest verification.
- Added `_tools/verify-manifest.py` for read-only manifest checks.
- Updated optional skill fetching and telemetry scripts to return MCP-compatible structured JSON.
- Changed benchmark validation to use task JSON first, then `project/testing-config.md`, with no hard-coded project stack.
- Added Vietnamese user guides for active GSAP skills.
- Removed project-specific examples from portable user-facing guides and kept project-specific examples inside the project memory layer.

# V8.0.6 (Agentic Design Patterns & Trajectory Metrics)

Added & Upgraded:
- **Blast Radius Control (Sandbox Enforcement):** Integrated sandbox boundary rule in `core/runtime-kernel.md` restricting file writes strictly to the scope defined in the approved `implementation_plan.md`.
- **Generator-Critic Planning Loop:** Phased the planning sequence into a Generator phase (functionality design) and Critic phase (adversarial boundary/static review) in `AGENTS.md`.
- **Model Context Protocol (MCP) spec:** Authored `_ide/mcp-specification.md` defining the local MCP Server tool API contracts for preflight, routing, telemetry, and optional skill fetches.
- **Context Triage (Anti-Semantic Drift):** Added P0 (Always Load), P1 (Load if Relevant), and P3 (Discard) context triage rules in `core/runtime-kernel.md` to prevent context overload.
- **Summary Telemetry Foundation:** Added structured summary telemetry for modes, capabilities, files touched, tool names, estimated token cost, duration, and lifecycle events. Detailed tool trajectories require wrapper-supplied metadata.
- **Relational State Memory Standard:** Mandated SQL-like tabular representation for project-specific memory (`project-memory/SKILL.md`) to preserve 1-1 structure consistency.
- System version bumped to V8.0.6 across all files.

# V8.0.5 (Immutable Invariants & Architectural Self-Critique)

Added & Upgraded:
- **8 Immutable Principles Enforced:** Formally registered and integrated the 8 Architectural Invariants of Agent OS into the Core OS layer (`AGENTS.md` and `runtime-kernel.md`).
- **Separation of Layers (Core vs. Project Adapter):** Strictly isolated project-specific names, domain variables, and local configurations from Core OS files (`core/`, `routing/`, and root guides).
- **Contextual Sandboxing:** Implemented rule requiring any project-specific illustrative examples in Core guides to be wrapped within explicit `[Contextual Illustration]` sections to preserve universality.
- **Active Self-Querying & Boundary Critique:** Enforced a mandatory self-critique check during boot sequence (`bootstrap.md` & `AGENTS.md`) requiring the agent to analyze the target file layer before execution.
- **Search Exclusions:** Instructed search tools to exclude user-facing Vietnamese guides (`*_VI.md`) during generic scans to prevent language bleeding and token waste.
- **All Core OS files project-purified:** Cleaned up `.agents/USER_GUIDE_VI.md` to remove specific project references, replacing them with agnostic designators.
- System version bumped to V8.0.5 across all files.

# V8.0.4 (Vietnamese User Guide Policy & TSC Blind Spot Fix)

Added & Upgraded:
- **Vietnamese User Guide Policy:** Established a dual-language system protocol requiring a Vietnamese User Guide (`USER_GUIDE_VI.md`) for all active skills in the registry to help users understand how to invoke and leverage them.
- **Agent Bypass Rule:** Enforced a hard constraint in `AGENTS.md` prohibiting agents from loading or reading the `USER_GUIDE_VI.md` files. This prevents language bleeding and context bloat/noise, ensuring the model relies strictly on the English `SKILL.md` for technical reasoning.
- **Comprehensive Vietnamese Guides:** Authored detailed, production-quality user guides in Vietnamese for all 23 active skills (9 standard skills and 14 Addy Osmani engineering workflow skills).
- **TSC Project References Awareness:** Fixed critical blind spot where `tsc --noEmit` checked ZERO files in Vite projects using Project References (`"files": []`). Agent now uses `tsc --noEmit -p tsconfig.app.json` to target the app config directly. Note: `tsc -b` cannot be combined with `--noEmit` (TS5094).
- **Project-Specific Static Analysis Config:** Added `Static Analysis Commands` section to `project/testing-config.md` as the single source of truth for TSC/ESLint commands per project.
- **5 Agent OS files updated:** Removed hardcoded `tsc --noEmit` from AGENTS.md, final-checklist.md, capability-registry.json, and quality-gates.md. All now reference `project/testing-config.md` for project-specific commands.
- System version bumped to V8.0.4 across all files.

# V8.0.3 (Hotfix Routing Enforcement + Metadata Sync)

Added & Upgraded:
- **Strict Skill Load Hook:** Added hard enforcement rule requiring agents to invoke `view_file` to physically load `SKILL.md` files upon executing slash commands, preventing "LLM Shortcut/Bypass" behaviors.
- **Auditable Execution Logs:** Registered `### 11. Skill Loading Verification` in `runtime-kernel.md` to force auditable tool calls before any plan generation.
- **3 New Skills Registered:** `context-engineering` (context optimization, anti-bloat), `doubt-driven-development` (adversarial fresh-context review), `api-and-interface-design` (API contract design) — all governed under Governed Symbiosis.
- **Metadata Desync Fix:** Synchronized `runtime-state.md` from V8.0.0 → V8.0.3. Updated `ide-policy.json` from V7.7.4 → V8.0.3 with dual vendor support (anthropic-skills + addy-agent-skills).
- System version bumped to V8.0.3 across all files: AGENTS.md, bootstrap.md, runtime-kernel.md, runtime-state.md, ide-policy.json, and capability-registry.json.

# V8.0.2 (Governed Symbiosis Edition)

Added & Upgraded:
- **Governed Symbiosis Integration:** Integrated `addyosmani/agent-skills` (24 production-grade engineering workflow skills) as a governed vendor package under `vendor/addy-agent-skills/`.
- **11 Curated Skills Registered:** `spec-driven-development`, `planning-and-task-breakdown`, `incremental-implementation`, `test-driven-development`, `code-review-and-quality`, `debugging-and-error-recovery`, `code-simplification`, `frontend-ui-engineering`, `security-and-hardening`, `performance-optimization`, `shipping-and-launch`.
- **Meta-Skill Router Disabled:** `using-agent-skills` decision tree router explicitly disabled to prevent dual routing (Architectural Invariant #7).
- **7 Governed Slash Commands:** `/spec`, `/plan`, `/build`, `/test`, `/review`, `/code-simplify`, `/ship` — all routed through `capability-registry.json` with `preflight_required` enforcement.
- **`/build auto` Safety Gate:** Auto-build permitted only after user plan approval; auto-commit remains FORBIDDEN.
- **Engineering Workflows Group:** New `engineering_workflows` capability group added to registry with STANDARD/DEEP mode assignments.
- **Updated `capability-catalog.md`** with full addy-agent-skills vendor documentation.
- System version bumped to V8.0.2 across AGENTS.md, bootstrap.md, runtime-kernel.md, and capability-registry.json.

# V8.0.1 (Anti-Breakage Edition)

Added & Upgraded:
- Anti-Breakage Design Implementation: Addressed Paralysis by Analysis, Context Blind Spot, and Preflight Deadlock.
- Delta-Scope Radar & Severity Filter: Prevent Alert Fatigue by logging passive tech debt silently.
- Assumed Failure Prompting & Static Hard-Validator: Prevent Validator Collusion by mandating static analysis and an adversarial prompt.
- Soft-Gate Objective Metric Validation: Prevent Soft-Gate Exploitation by checking Complexity Density and Coupling Index in `v8_preflight.py`.
- Transaction Boundary & Auto-Rollback: Prevent Timeout Assassination via Git checkpointing and rollback hooks upon subagent termination.
- Anti-Breakage Semantic Routing: Prevent Semantic Hallucination via Dual-Context Filters and Pre-Execution Dry Runs.
- Language Purification: Enforced 100% Professional Technical English for all core OS rule files, configuration, and documentation, reserving Vietnamese strictly for user runtime interaction.

# V8.0.0 (The Robustness Update)

Added & Upgraded:
- Semantic Routing: Added `semantic_indicators` to `capability-registry.json` to reduce static keyword dependency.
- Multi-Agent Orchestration: Enforced a `Validator Subagent` cross-checking rule in `executor.md` to eliminate blind spots.
- Subagent Lifecycle Management: Introduced active subagent lifecycle & timeout rules in `runtime-kernel.md`.
- Manifest Enforcement: Added integrity check hooks to `final-checklist.md`.
- Bumped Agent OS to Version 8.0.0.

# V7.8.0
Clean-up & Restructuring:
- Consolidated routing by moving `routers/` and `optional-skill-registry.json` into `routing/`.
- Modified `vendor/capability-catalog.md` to remove 10 phantom vendor skills.
- Merged `pre-implementation-review-framework` into `architecture-challenge-framework` and migrated it to a Skill with YAML frontmatter.
- Standardized frontmatter for `constitution-first` to improve skill discoverability.
- Removed obsolete redundant JSON SHA manifest files.
- Synchronized the entire system version to `V7.8.0`.

# V7.7.6

Added:
- Thinking Layer
- Constitution First skill
- Architecture Challenge skill refinement
- AGENT_OS_HISTORY
- LESSONS_LEARNED

No new vendors.
No new tool automation.
No new memory automation.


## V7.7.6 Task Documentation Skill

Added:
- Optional task-documentation skill.
- Optional routing rule for user-requested documentation.

No automatic reporting behavior added.
