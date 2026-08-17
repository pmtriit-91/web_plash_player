# Executor Workflow

During execution:

- Modify only within the defined scope.
- Follow existing patterns before creating new ones.
- Do not make large structural changes unless required by the task.
- Do not arbitrarily clean up unrelated code.
- Do not add abstractions just to make it "look nicer".
- Prioritize clear code over clever code.

After making changes:

- Check imports/exports.
- Check type safety.
- Ensure the UI does not deviate from established patterns.
- Ensure the logic does not change beyond the requirements.

## Multi-Agent Orchestration

When delegating tasks to Subagents:
- **Mandatory Validation:** The Orchestrator (Parent Agent) MUST either act as a Validator or delegate a specific Validator Subagent to independently verify the output of Worker Subagents.
- Never blindly trust a Subagent's completion report without programmatic or manual cross-checking.
- **Assumed Failure Prompting:** To prevent Validator Collusion, do not ask the Validator "Is this code correct?". Instead, enforce an adversarial prompt: *"Assume this code contains at least 2 critical logic errors (e.g., memory leaks or data flow issues). Find them. If you conclude the code is safe, you must provide proof why these errors cannot occur."*
