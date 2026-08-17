# Agent OS Lessons Learned

This document serves as the repository of hard-earned engineering lessons and architectural paradigms accumulated across all versions of **Agent OS**.

---

## 🛠️ 1. Tool Invocation & Automation Discipline

### Lesson 01: Tool Availability ≠ Tool Permission
*   **The Problem:** In V7.x, introducing DevTools MCP and browser automation tools caused the agent to automatically trigger browser launches and search tools at every step, creating expensive execution loops.
*   **The Lesson:** Just because a tool exists in the environment does not mean the agent is permitted to execute it. Auto-invocation must be restricted.
*   **The Standard:** The agent must only invoke system tools if:
    1. The user explicitly requests it.
    2. No low-cost static evidence exists.
    3. The agent explicitly states the rationale to the user beforehand.

### Lesson 02: Tool Infinite Loop Loopback (Self-Correction Trap)
*   **The Problem:** When running automated build or test scripts autonomously, agents often enter infinite self-correcting loops upon encountering errors, consuming massive token budgets without achieving a solution.
*   **The Lesson:** Runtime processes must have hard stop boundaries. The user must remain the ultimate orchestrator who reviews plans before execution.

---

## 🎛️ 2. Capability & Routing Governance

### Lesson 03: Context Pollution & Skill Bloat
*   **The Problem:** V4-V6 loaded all specialized skill files (`skills/`) into the context window by default, which diluted the LLM's reasoning and caused semantic drift.
*   **The Lesson:** System memory must remain lean. **Load Less, Think Better**.
*   **The Standard:** Introduced dynamic routing via `routing/capability-registry.json`. A skill is only loaded into the active context if its confidence trigger matches the user task threshold.

### Lesson 04: Duplicate Routing & Dual Sources of Truth
*   **The Problem:** Coexistence of `core/capability-map.json` and `routing/capability-registry.json` created conflicting routing patterns for different agent instances.
*   **The Lesson:** Every system configuration must have a single source of truth. Dual routing systems lead to behavioral divergence.
*   **The Standard:** Consolidated all paths, mode configurations, and vendor packages into `routing/capability-registry.json`.

### Lesson 05: Vendor Skill Entropy
*   **The Problem:** Importing raw, uncurated third-party skill sets (e.g., all 18 Anthropic skill packages) degraded the routing precision because of overlapping functionalities.
*   **The Lesson:** Curating and limiting skills (e.g., reducing vendor packages to 8 core workflows in V7.7.3) is more effective than expanding catalog sizes. **Capability Organization > Capability Expansion**.

---

## 🧠 3. Cognitive & Planning Philosophy

### Lesson 06: Build First, Think Later (Failure to Challenge)
*   **The Problem:** Early agents immediately began coding or modifying files upon user request, leading to severe architectural violations and patch-worked code.
*   **The Lesson:** Upfront planning is mandatory. An implementation plan must be reviewed against constraints before any file modifications occur.
*   **The Standard:** Codified the **Thinking Layer** (Constitution First & Architecture Challenge Framework) — enforce "Build the right thing before building things right".

### Lesson 07: Unstructured Memory Hallucinations
*   **The Problem:** Storing project-specific rules as loose narrative prose in `project-memory` resulted in agents misinterpreting, forgetting, or hallucinating rules.
*   **The Lesson:** Memory updates must be structurally rigid to prevent semantic drift.
*   **The Standard:** Implemented **Relational State Memory (SQL Memory Standard)**, forcing all discoveries and operational rules to be structured in 1-to-1 relational markdown tables.

---

## 🏛️ 4. Clean Architecture & Boundaries

### Lesson 08: Context Bleed & Hardcoding
*   **The Problem:** Mixing local project specific code (such as database config, app pages) into the core `AGENTS.md` or `core/` files made the OS non-portable.
*   **The Lesson:** Absolute boundary separation must be maintained between the project layer and the Agent OS layer.
*   **The Standard:** Extracted all project configurations to `project/` and `skills/project-memory/`. Enforced contextual sandboxing for illustrative documentation.

---

## 🧠 5. Key Takeaways (Quick Reference Checklist)

For rapid retrieval and cognitive alignment, the core tenets of Agent OS are summarized below:

*   **Tool Discipline:** Never execute mutating terminal commands or automated browsers unless explicitly requested by the user, or after a plan has been explicitly approved.
*   **Context Control (Load Less, Think Better):** Dynamically load only the primary skill matching the confidence trigger. Do not pollute the context window with uncurated vendor skill packages.
*   **Clean Architecture (Strict Layering):** Core OS files (`AGENTS.md`, `core/*`, `routing/*`) must remain 100% project-agnostic. All project-specific configurations must reside in `project/` or `skills/project-memory/`.
*   **Planning Paradigm:** Always complete the **Constitution First** and **Architecture Challenge** workflows before performing any file edits or executing implementation steps.
*   **Structured Memory (Relational Standard):** Do not write loose narrative prose in project-memory. Always record discoveries and operational rules in 1-to-1 relational markdown tables.
*   **Routing Integrity:** Trust only `routing/capability-registry.json` as the single source of truth for active routing. Subordinate metadata catalogs are allowed only when referenced by the registry and unable to decide active skill loading independently.
*   **Manifest Validation:** After any file changes (addition, modification, deletion) in `.agents/`, you must immediately execute the sync scripts to validate system integrity and update SHA-256 hashes.
