# Agent OS Evolution History & Architectural Invariants

This document records the evolution journey, hard-earned lessons, and invariant architectural principles of **Agent OS** - a Project-Agnostic Agent Operating System.

All subsequent generations of Agents, upon booting into the system, must read and strictly adhere to this document to clearly understand why the Agent OS is structured the way it is, and absolutely avoid repeating past architectural mistakes.

---

## 📅 1. Version Timeline

*   **V1 - V3: Prompt Era (Static System Prompt)**
    *   The primitive system relied entirely on verbose static System Prompts, filled with general programming instructions.
    *   *Limitations:* Extremely high token overhead, lacking dynamic adaptability, and unable to scale efficiently across different projects.
*   **V4 - V6: Capability Expansion Era**
    *   Developed a massive array of independent skill files (`skills/`) to handle specialized tasks.
    *   *Limitations:* Loading all skills simultaneously into the Agent's context window caused severe context pollution and token waste.
*   **V7.x: Behavior Era (Standardizing Behavior)**
    *   Focused on establishing hard behavioral guardrails for the Agent in `AGENTS.md` (conversational language, test file naming conventions).
*   **V7.7: Quality Assurance & Memory Sustainability**
    *   Introduced the Core Quality Gates concept (`core/quality-gates.md`) and memory maintenance processes (`memory/memory-maintenance.md`). Codified principles: *Source of Truth First*, *Load Less, Think Better*, *Detect Before Apply*, *Observe Reality Before Reasoning*, and *Behavior Engineering Over Prompt Engineering*.
*   **V7.7.1: Tool-Neutral Runtime Verification**
    *   Formally established "Tool Invocation Discipline". De-biased the system from automatically invoking heavy DevTools MCP or browser automation. Enforced 4 strict pre-requisites for using system tools to prevent infinite self-correcting loops and preserve token budgets.
*   **V7.7.2: Vendor Capability Catalog**
    *   Integrated 18 Anthropic Skills as governed, optional vendor packages housed in `vendor/anthropic-skills/skills/`, registered via a dynamic routing map (`vendor/capability-catalog.md` and `routers/vendor-capability-router.md`) without bloat to the kernel.
*   **V7.7.3: Curated Capability Groups**
    *   Reduced capability catalog entropy by filtering out 10 redundant/unstable vendor skills, keeping 8 core capabilities (docx, frontend-design, mcp-builder, pdf, pptx, skill-creator, webapp-testing, xlsx). Codified the principle: *Capability Organization > Capability Expansion*.
*   **V7.7.4: Capability Registry & Routing Guide**
    *   Consolidated dynamic routing knowledge into `routing/capability-registry.json` and `routing/capability-routing-guide.md`. Enforced confidence-based routing path: *Task → Capability Group → Confidence Trigger → One Primary Skill → Supporting Skill only if needed*.
*   **V7.7.5: Structured Decisions & History Logging**
    *   Introduced the Architecture Challenge concept to challenge design decisions before execution. Established the first `AGENT_OS_HISTORY.md` file to preserve architecture evolution.
*   **V7.7.6: Thinking Layer & Task Documentation**
    *   Codified the **Thinking Layer** (including *Constitution First* and *Architecture Challenge Framework*) to ensure mission alignment before writing code. Added an optional `skills/documentation/task-documentation/` skill to write documentation *only* when explicitly requested by users, preventing automatic generation of logs after every task.
*   **V7.8.0: Cleanup & Stabilization Era (Lean Kernel)**
    *   Completely eliminated phantom paths, cleaned up virtual skills that did not physically exist on disk. Consolidated the entire routing layer into a single source (`routing/`) by deleting the legacy `routers/` directory, legacy registry JSONs, and duplicate cognitive frameworks. Ensure the system remains entirely **Project-Agnostic**.
*   **V7.9.0: Unified Routing Era**
    *   Consolidated `core/capability-map.json` and `routing/capability-registry.json` into a single source. Separated project-specific content out of AGENTS.md. Implemented Hard Enforcement via scripts and git hooks. Automated routing synchronization.
*   **V8.0.0: Robustness & Multi-Agent Maturity Era**
    *   Resolved structural vulnerabilities of V7.9.0. Introduced Semantic Indicators to overcome Static Keyword Routing limitations. Formalized Multi-Agent Orchestration by mandating Validator Subagents and enforcing Subagent Lifecycle Management (Timeout/Auto-kill) to prevent recursive stalling. Forced Manifest Sync via check-hooks.
*   **V8.0.1: Anti-Breakage & Language Purification Era**
    *   Resolved adversarial breakage vulnerabilities (Alert Fatigue, Validator Collusion, Soft-Gate Exploitation, Timeout Assassination, Semantic Hallucination). Implemented Delta-Scope Radar, Soft-Gate preflight logic, Assumed Failure prompting, Auto-Rollback subagent lifecycles, and Pre-Execution Dry Runs. Enforced 100% English Core Language Policy for maximum reasoning precision.
*   **V8.0.2: Governed Symbiosis Era (Vendor Skill Integration)**
    *   Integrated `addyosmani/agent-skills` (24 production-grade engineering workflow skills) as a governed vendor package. Established the "Shield + Sword" architecture: Agent OS governs safety/routing (Shield), agent-skills provides structured development workflows (Sword). Disabled the plugin's meta-skill router to prevent dual routing (Invariant #7). Registered 11 curated skills with FAST/STANDARD/DEEP mode assignments and preflight enforcement. Added 7 governed slash commands (`/spec`, `/plan`, `/build`, `/test`, `/review`, `/code-simplify`, `/ship`) routed through `capability-registry.json`.
*   **V8.0.3: Hotfix Routing Enforcement Era**
    *   Patched the "LLM Shortcut Bypass" vulnerability. Implemented the Strict Skill Load Hook in bootstrap and AGENTS.md, requiring agents to run the `view_file` tool to load `SKILL.md` before executing slash commands. Registered `### 11. Skill Loading Verification` in runtime-kernel.md to establish an auditable execution log and prevent LLM-based faking.
*   **V8.0.4: Vietnamese User Guide Policy Era**
    *   Established the Vietnamese User Guide Policy. Created `USER_GUIDE_VI.md` for all 23 active skills in the registry to help users utilize the system effectively. Enforced the Agent Bypass Rule in `AGENTS.md` preventing agents from reading Vietnamese guide files to maintain English reasoning purity and prevent context pollution.
*   **V8.0.5: Immutable Invariants & Self-Critique Era**
    *   Formally codified and integrated the 8 Architectural Invariants of Agent OS into the Core OS layer (AGENTS.md and runtime-kernel.md). Enforced absolute separation of layers, project-agnostic core guidelines, contextual sandboxing, active self-querying/boundary critique during boot, and search exclusions to prevent context overfitting and maintain system universality.
*   **V8.0.6: Agentic Design Patterns Era**
    *   Integrated advanced agentic design patterns based on production guidelines: Blast Radius Control sandbox constraints, Generator-Critic adversarial loops during planning, Context Triage (P0/P1/P3 priorities) to avoid Semantic Drift, Trajectory Metrics (CLEAR Framework) to optimize tool invocation pathways, and Relational State (SQL Memory) tabular layout for structured memory updates. Authored the `_ide/mcp-specification.md` standardizing IDE tool connections.
*   **V8.0.6 Hardening Patch: Contract & Portability Remediation**
    *   Removed local absolute paths from Core OS documentation, standardized the 8 Architectural Invariants, replaced destructive Subagent rollback wording with safe transaction boundaries, aligned MCP specification with CLI tool contracts, added manifest verification, and documented localized trigger strings as routing data only.
*   **V8.0.7: MCP Enforcement, Trace Telemetry & Behavioral Evals**
    *   Added local stdio MCP wrapper, deterministic routing resolver, redacted trace spans, behavioral eval registry/runner, and private release snapshots to move Agent OS from markdown governance toward auditable runtime enforcement.

---

## ⚠️ 2. Lessons Learned (Hard-earned past lessons)

### 📌 Lesson 01: Load All Skills
- **Consequence:** Caused Context Pollution and Token Waste. The Agent became diluted with information, inferred inaccurately, and responded slowly due to reading skills irrelevant to the current task.
- **Solution:** Established dynamic Capability Routing (`capability-registry.json`). Only load skills when truly necessary for the task.

### 📌 Lesson 02: Auto Tool Invocation
- **Consequence:** The Agent autonomously executed background processes, browsers, or commands outside the sandbox without the user's explicit consent. When encountering errors, the Agent easily fell into infinite self-correcting recursive loops, losing control and consuming massive amounts of tokens.
- **Solution:** Transitioned to User-Controlled Execution. The Agent must justify and obtain clear approval from the user before invoking tools that mutate state or interact with the system.

### 📌 Lesson 03: Vendor Skill Explosion
- **Consequence:** Rampant loading of third-party skill libraries (e.g., Anthropic skill packages) severely reduced the Signal-to-Noise ratio. The Agent became confused when selecting routing tools.
- **Solution:** Built a Curated Capability System. Kept only the most meticulously curated skills, fully isolated the Vendor layer in the `vendor/` directory, and loaded them dynamically via the registry.

### 📌 Lesson 04: Build First, Think Later
- **Consequence:** The Agent immediately wrote code or executed modification commands upon receiving a request without deeply analyzing the product architecture, resulting in patch-worked code, misdirection, and violations of system design.
- **Solution:** Made the Constitution First and Architecture Challenge workflows mandatory before performing any modifications.

### 📌 Lesson 05: Ignore Explicit Tool Request
- **Consequence:** When applying the restricted auto tool invocation rule from Lesson 02, Agents misinterpreted it as "not allowed to use tools even when clearly requested by the user". This entirely paralyzed visual debug testing scenarios (such as DevTools MCP or running E2E tests).
- **Solution:** Clearly defined the principle: Explicit Tool Request Routing - An explicit tool request from the user takes the highest routing priority.

### 📌 Lesson 06: Dual Routing Source of Truth
- **Consequence:** Coexistence of `core/capability-map.json` and `routing/capability-registry.json` with overlapping yet inconsistent data. Bootstrap.md pointed to one, while AGENTS.md declared the other as the single source. Different Agents reading in different orders resulted in divergent routing inference models.
- **Solution:** Consolidated everything into a single JSON file `routing/capability-registry.json` containing mode limits, internal capabilities, and vendor skills.

---

## 🏛️ 3. Architectural Invariants

Any upgrade proposal must strictly adhere to these invariant principles:

1.  **Project-Agnostic First:** Agent OS exists independently of the accompanying project source code. No local machine paths, project names, domain objects, environment variables, or project business logic may be introduced into Core OS files.
2.  **Layer Separation & Project Adapter Isolation:** Core OS and routing files must remain reusable. Project-specific testing commands, constraints, and memories belong in `project/` and `skills/project-memory/`.
3.  **Contextual Sandboxing:** Concrete project examples in Core OS documentation must be wrapped in `[Contextual Illustration]` blocks and remain removable.
4.  **Load Less, Think Better:** Keep context minimal to reserve high-quality reasoning space for the LLM.
5.  **Capability Is Not Default Behavior:** A registered capability does not grant permission to execute it automatically.
6.  **Tool Is Not Automatic Execution:** MCP tools, terminal commands, browser automation, memory systems, and runtime tools require user intent, task safety need, or explicit workflow justification.
7.  **Single Source of Truth for Active Routing:** `routing/capability-registry.json` is the only active routing authority. Subordinate metadata catalogs are allowed only when referenced by the registry and cannot independently decide skill loading.
8.  **Safe Transaction Boundaries:** Write-capable subagents, benchmark runs, and automated rollback workflows must preserve developer-owned uncommitted work. Default behavior is to abort when the worktree is not clean unless the developer explicitly approves a checkpoint/stash strategy.

---

## 🚫 4. Anti-patterns Never Return

Absolutely never allow the following components to return to the Agent OS:

*   `load all skills`: It is forbidden to automatically load all files in the `skills/` directory into the system upon boot.
*   `auto invoke tool`: It is forbidden to silently run shell commands, browser agents, or environment setups without presenting them for user approval.
*   `duplicate registry`: It is forbidden to create a parallel active routing authority causing routing conflicts.
*   `phantom paths`: It is forbidden to declare virtual paths or files that do not physically exist in the system structure.
*   `dual routing registry`: It is forbidden to create two overlapping routing JSON files (e.g., `capability-map.json` alongside `capability-registry.json`).
*   `stale catalog`: It is forbidden to leave the `capability-catalog.md` documenting deprecated or removed skills.
*   `project-specific hardcoding in core`: It is forbidden to introduce source code or specific project business logic (e.g., product configurations, DB connections, app-specific build commands) into the `.agents/core/` or `.agents/routing/` directories.
*   `vendor explosion`: It is forbidden to arbitrarily install supplementary vendor packages that have not passed quality review.
*   `documentation bloat`: It is forbidden to write verbose documentation re-explaining code or describing obvious features. Agent OS documentation must be extremely concise and dense.

---

## 🧭 5. Future Upgrade Decision Framework

Before proposing any new skill (`skill`), capability (`capability`), router (`router`), or workflow (`workflow`) into the Agent OS, the Agent must answer and justify it via the following 7 questions:

1.  **What is the actual underlying problem?** (Is it a core problem of a Project-Agnostic Agent Operating System, or just a problem of a specific software project?)
2.  **Can the existing Capabilities of Agent OS solve this?** (If it can be resolved by optimizing Prompts or combining existing skills, absolutely do not add a new one).
3.  **Will this addition increase Context Pollution?**
4.  **Is this creating a second Source of Truth for routing?**
5.  **Is this a local optimization or hard-coded specifically for one project?**
6.  **Does this addition violate the "Load Less, Think Better" principle?**
7.  **If this capability is not added, does the Agent OS genuinely become weaker in supporting future Agents?**

*If the proposal cannot be justified and pass these 7 questions, the upgrade will be instantly rejected.*
