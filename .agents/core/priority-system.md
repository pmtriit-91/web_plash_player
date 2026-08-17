# Priority System

When rules conflict, apply the following priority order:

1. Safety / do not break the system
2. Direct user requests
3. Project-specific memory
4. Existing architecture/conventions
5. Task-scoped release or locked vendor skills
6. Performance optimization
7. Creative Direction / Taste layer when tasks involve UI, brand, motion, landing page, product experience
8. General style preferences

## Conflict protocol

Read more:

- `.agents/core/conflict-resolution.md`
- `.agents/core/agent-intelligence-hierarchy.md`

## Remember

- Do not sacrifice business logic for minor render optimizations.
- Do not change API contracts unless explicitly requested.
- Do not redesign stable UIs if the task does not request it.
- If the user explicitly requests upgrading the UI/UX/landing page experience, the creative layer is allowed to propose new layouts/motion within the task scope.
- Do not apply React Native skills to web projects unless the task involves mobile/native.
