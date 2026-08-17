# Quality Gates — V9.1.0

Purpose:
Task Done ≠ Code Written

Preferred completion flow:

Implement
↓
Runtime Verify (if relevant)
↓
Build
↓
Lint
↓
Typecheck
↓
Report

Rules:
- If build script exists, prefer running it.
- If lint script exists, prefer running it.
- If typecheck exists, prefer running it.
- **TSC Project References Warning:** If `tsconfig.json` has `"files": []` and `"references": [...]`, plain `tsc --noEmit` checks ZERO files. Use `tsc --noEmit -p tsconfig.app.json` or the project-specific command from `project/testing-config.md`.
- If verification cannot be performed, state limitation clearly.
- Do not falsely claim success.

Claim-specific evidence gate:

1. Identify the exact claim: test pass, build pass, bug fixed, requirement met,
   or artifact complete.
2. Select evidence that can prove that claim. Lint does not prove build; a diff
   does not prove runtime behavior; tests alone do not prove every requirement.
3. Run the full relevant check after the last relevant change and inspect its
   exit code, failure count, and complete result.
4. Verify requirements separately against the requested checklist.
5. If evidence is partial, stale, unavailable, or contradictory, report the
   narrower verified result and the remaining uncertainty.

Do not inherit completion claims from another agent, a document, NotebookLM, or
an earlier run without checking the current artifact and evidence.
