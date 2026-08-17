# Memory Maintenance — V9.1.0

Purpose:
Preserve knowledge without growing context indefinitely.

Rules:
- Do not delete important decisions.
- Prefer summarize → archive over delete.
- Preserve architecture decisions, conventions, business rules.
- Remove duplicate notes and temporary debugging details.

When memory becomes large:
1. Select only cold `research` or `historical` records.
2. Create an evidence-backed summary record with `supersedes` references.
3. Mark every original `archived`; do not remove it.
4. Apply the exact diff through a reviewed transaction.
5. Keep source evidence and active decisions unchanged.

Compaction of identity, current state, guardrails, active decisions, tasks, or
handoffs is blocked. Archive growth is bounded by project budgets and remains
application-owned.
