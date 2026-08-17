# Frontend Runtime Verification Loop — V9.1.0

## Goal

Preserve runtime awareness without forcing tool usage.

## Principle

Runtime verification is capability-based and cost-aware.

Use:

```txt
Observe → Analyze → Implement → Retest
```

only when runtime evidence is necessary or explicitly requested.

## Decision Rule

Before invoking tools, ask:

1. Can this be solved safely from source/project evidence?
2. Is runtime behavior actually relevant?
3. Is there cheaper evidence already available?
4. Has the user explicitly requested browser/tool verification?
5. Would tool invocation cost more than it helps?

## Tool Priority

1. Source/project files
2. User screenshots/logs/URLs
3. Existing running app/session
4. DevTools MCP or browser tooling
5. Advanced CDP fallback
6. State limitation

## Completion

A runtime-visible task may be completed with:

- source-level verification,
- runtime verification,
- build/lint/typecheck,
- or an explicit limitation statement.

Do not claim browser verification if it was not performed.
