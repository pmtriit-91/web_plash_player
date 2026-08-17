# Agent OS Architecture Report & Evaluation (V8.0.7)

This tailored report provides a comprehensive overview of the architectural principles, core features, strengths, weaknesses, and structural evaluations of **Agent OS** version **V8.0.7 (Runtime Enforcement Era)**.

---

## 1. Executive Summary

**Agent OS** is a project-agnostic, markdown-driven agent operating system designed to run on top of advanced IDE environments. Its primary goal is to reduce orchestration cognition overhead while preserving and maximizing LLM reasoning depth.

Version **V8.0.7** turns the prior markdown governance model into a more auditable runtime enforcement layer. It adds a local stdio MCP wrapper, deterministic workflow/capability resolver, redacted trace telemetry, behavioral eval runner, and private release snapshot governance for `.agents/` installations that intentionally remain outside application Git history.

---

## 2. Core Architectural Philosophy & Invariants

Agent OS operates on a **"Shield + Sword"** architectural model:
*   **The Shield (Agent OS Core):** Governs behavioral constraints, security boundaries, and capabilities. It remains strictly project-agnostic.
*   **The Sword (Vendor/Developer Workflows):** Houses optional development workflow packages (e.g., `addyosmani/agent-skills`) which execute specific engineering tasks.

### The 5-Layer Abstraction
To prevent architectural drift and project code leakage into core rules, the system enforces a strict 5-layer abstraction:
1.  **Core OS Layer (`AGENTS.md`, `core/*`):** Houses system rules, bootstrap sequences, and runtime kernels. Must remain 100% project-independent.
2.  **Project Adapter Layer (`project/`):** Contains specific project configurations, test execution settings (`testing-config.md`), and custom hooks.
3.  **Routing Layer (`routing/*`):** Domain-separated registries for workflow selection and capability/skill loading.
4.  **Vendor / Extension Layer (`vendor/`):** Third-party or auxiliary skill packages loaded on-demand.
5.  **Tooling, History & Telemetry Layer (`_tools/`, `_manifest/`, `_telemetry/`, `evals/`):** Enforces preflight/routing checks, records redacted traces, runs behavioral evals, and tracks file signatures.

---

## 3. Key Capability Features of V8.0.7

### A. Blast Radius Control (Sandbox Enforcement)
*   **Mechanism:** Prevents agents from altering codebase structures outside the specific list of files declared and approved in the `implementation_plan.md`.
*   **Rationale:** Early agents frequently over-implemented features, leaking edits into unrelated components, causing cascading breakage. Blast Radius confines all writes to a declared sandbox.

### B. Generator-Critic Adversarial Loop
*   **Mechanism:** Splitting agent cognition into two adversarial phases during planning:
    1.  *Generator:* Drafts the technical solution, focusing on functionality.
    2.  *Critic:* Reviews the proposed plan from a security, style, compliance, and regression perspective before submitting it to the user.
*   **Rationale:** Prevents silent LLM pass-throughs of buggy code and bypasses static code checkers.

### C. Context Triage Pipeline
*   **Mechanism:** A strict filtering pipeline prioritizing loaded files to prevent context window saturation:
    *   **P0 (Supreme Context - Always Load):** Core kernel instructions and current task instructions.
    *   **P1 (Conditional Context - Load if Relevant):** Primary task skill, direct imports, and dependency interfaces.
    *   **P3 (Discarded Context - Never Load):** Stale files, duplicate registries, and inactive assets.
*   **Rationale:** Directly combat **Semantic Drift** caused by context pollution, reserving reasoning budget for actual problem-solving.

### D. MCP Enforcement Wrapper
*   **Mechanism:** `_tools/agent_os_mcp_server.py` exposes Agent OS capabilities through stdio JSON-RPC MCP-compatible tools: preflight, routing validation, routing resolution, telemetry, trace, and optional skill fetch.
*   **Rationale:** Reduces reliance on agent self-discipline by giving IDE wrappers a structured enforcement surface.

### E. Redacted Trace Telemetry
*   **Mechanism:** `_tools/trace_collector.py` records operational spans for routing, skill loading, tool calls, validation, guardrails, and completion without storing raw prompts, secrets, code, or chain-of-thought.
*   **Rationale:** Creates a reusable debugging/eval/training-readiness signal while preserving privacy and context hygiene.

### F. Behavioral Eval Runner
*   **Mechanism:** `evals/agent-os-evals.json` and `_tools/run-agent-os-evals.py` validate routing behavior, context firewall decisions, manifest integrity, and MCP wrapper readiness.
*   **Rationale:** Converts architectural expectations into repeatable regression checks.

### G. Private Release Snapshot
*   **Mechanism:** `_tools/private_release_snapshot.py` creates a manifest-independent aggregate hash for private Agent OS releases.
*   **Rationale:** Protects IP by keeping `.agents/` out of public Git while preserving local release integrity.

### H. Relational State Memory (SQL Memory Standard)
*   **Mechanism:** Mandates that all project discoveries, architecture rules, and conventions stored in `skills/project-memory/SKILL.md` be documented inside structured, 1-to-1 relational markdown tables.
*   **Rationale:** Replaces unstructured prose logs, which are highly prone to hallucination, with rigid schemas that future agents can parse deterministically.

---

## 4. Strengths, Weaknesses, and Evaluation Scores

### A. Core Strengths
*   **Unrivaled Portability:** Due to strict project separation rules, the entire `.agents/` folder can be copied into any codebase (React, Go, Python) and begin functioning immediately without modification.
*   **High Token Economy:** Dynamic routing and context triage guarantee that the agent operates within a minimal context window, keeping latency low and accuracy high.
*   **Deterministic Safety:** The strict preflight checks and subagent transaction rollback rules ensure that incomplete or buggy agent runs do not corrupt the working git tree.

### B. Current Weaknesses & Risks
*   **Soft Enforcement Reliance:** When running without an IDE/CLI wrapper, all constraints (like Blast Radius and Context Triage) depend on the agent's self-discipline. A malicious or highly corrupted model could theoretically bypass these rules unless hard-blocked by external IDE wrappers.
*   **Registry Over-Escalation:** In complex tasks, the confidence-based triggers might occasionally misroute and load multiple supporting skills, increasing prompt sizes slightly.

### C. Architectural Maturity Evaluation (V8.0.7)

| Assessment Category | Score (1-10) | Key Justification |
| :--- | :--- | :--- |
| **Security & Safety** | **9.0 / 10** | Blast Radius Control, safe transaction preconditions, and strict Git Auto-Commit bans keep final control in human hands. |
| **Token & Context Efficiency** | **9.0 / 10** | Context Triage, `.agentignore`, and registry load hooks minimize context footprints. |
| **System Portability** | **9.1 / 10** | Core OS is project-agnostic and protected by manifest/private release snapshots. |
| **Multi-Agent Robustness** | **9.0 / 10** | Subagent lifecycle rules, safe transaction boundaries, and wrapper tools reduce orchestration drift. |
| **Cognitive Reliability** | **9.2 / 10** | Generator-Critic planning, routing resolver, redacted traces, and evals improve repeatability. |
| **Observability & Eval Readiness** | **8.6 / 10** | Trace spans and behavioral evals exist; richer trajectory scoring can still improve this layer. |

### 📊 Overall Architecture Health Index: **9.1 / 10** (Strong, Enforcement-Ready)

---

## 5. Maintenance and Future Evolution

When upgrading this architecture to future versions (e.g., V8.1.0 or V9.0.0):
1.  **Do not delete this file:** Maintain and update this report by adding new versions to the timelines and updating the evaluation scores.
2.  **Strict Manifest Sync:** After editing this report or any file in `.agents/`, the developer or agent MUST execute the synchronization scripts to calculate the new SHA-256 signatures:
    ```bash
    python3 .agents/_tools/update-manifest.py && python3 .agents/_tools/validate-routing-sync.py
    ```
