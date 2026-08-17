---
name: architecture-challenge-framework
description: Adversarially review product, UX, architecture, scale, operations, cost, compliance, and black-swan risks before a major implementation, migration, or refactor.
---

# Architecture Challenge Framework

Challenge a major proposal before implementation.

## Failure vectors

Evaluate only the proposed change and its direct dependencies:

1. Product: real user need, mission fit, and feature-bloat risk.
2. UX: discoverability, cognitive load, recovery, and failure clarity.
3. Architecture: ownership, coupling, compatibility, and technical debt.
4. Scale: bottlenecks, concurrency, storage, and growth limits.
5. Operations: diagnostics, observability, rollback, and maintainability.
6. Cost: infrastructure, API, storage, support, and migration cost.
7. Compliance: secrets, privacy, licenses, permissions, and supply chain.
8. Black swans: compromised sources, partial migrations, unavailable tools,
   corrupt state, and unsupported platforms.

## Outcome

Classify findings as blocker, material risk, or follow-up. Resolve blockers
before implementation. Report other findings in the task handoff; do not
silently mutate a project debt log or unrelated documentation.
