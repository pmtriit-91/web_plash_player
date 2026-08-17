# Intelligence Preservation Contract — V9.1.0

V9.1.0 must not be a "dumber but cheaper" system.
V9.1.0 must be an "intelligent when needed, frugal where appropriate" system.

## 1. Token saving is not intelligence reduction

Token saving is allowed by:
- not reading irrelevant files,
- not loading vendor skills when core reasoning suffices,
- not enabling unnecessary reviewers,
- not summarizing verbosely,
- not running the full creative/security/research pipeline for small tasks.

Token saving is NOT allowed by:
- skipping necessary analysis,
- ignoring architectural risks,
- skipping quality gates,
- providing shallow solutions for complex tasks,
- avoiding creative direction when the user requests "premium/cinematic/better" experiences,
- avoiding deep security/debugging when the task carries risks.

## 2. Quality floor

Every mode has a quality floor.

### FAST
Fast but not sloppy.
Must preserve:
- correctness of the request,
- not breaking other files,
- not breaking TypeScript/build,
- not worsening the UI.

### STANDARD
Balances speed and quality.
Must preserve:
- concise planning,
- reading the exact relevant skills,
- review-lite,
- appropriate safety.

### DEEP
Utilizes full necessary capabilities.
Cannot avoid:
- architecture reviewer,
- creative/motion reviewer,
- security/debugging workflow,
- a task-scoped vendor skill when the active registry resolves it and its lock verifies.

## 3. Escalation is mandatory

If in FAST/STANDARD but discovering the task is more complex than anticipated, you must escalate.

Do not attempt to complete a complex task using a lower mode just to save tokens.

## 4. De-escalation after deep work

After handling the difficult parts, minor follow-ups must revert to a lighter mode.
