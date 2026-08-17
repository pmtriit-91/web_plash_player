# Runtime State — V9.1.0

Runtime state is derived by:

```text
python3 .agents/_tools/agent_os_lifecycle.py doctor
```

This file does not store a current state. Static `BOUND`, `UNBOUND`, mode, or
verification flags would become stale and are not authoritative.

The doctor reports:

- Core manifest and vendor integrity;
- skill validation;
- project binding and command evidence;
- client bridge discovery;
- derived state and reason codes;
- allowed and blocked capability classes.

When lifecycle state is `BOUND`, project context has a separate derived diagnosis:

```text
python3 .agents/_tools/agent_os_context_memory.py doctor
```

`FRESH` permits the compact hot projection. `STALE` marks memory non-authoritative;
`DEGRADED` blocks it because of contamination, conflict, invalid evidence, or task
scope collisions. Context Memory state never changes the Core lifecycle state.
