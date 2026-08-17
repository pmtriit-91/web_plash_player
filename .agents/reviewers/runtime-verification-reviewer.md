# Runtime Verification Reviewer — V9.1.0

## Purpose

Check whether runtime verification was used appropriately.

## Checklist

### Tool Discipline
- Was a tool actually necessary?
- Was cheaper evidence available?
- Did the user request runtime verification?
- Did the agent avoid auto-launching DevTools/browser tooling?

### Verification
- Was the issue verified through source, runtime evidence, build/lint/typecheck, or limitation statement?
- If browser/runtime tools were used, was the reason justified?
- If not used, was skipping them reasonable?

### Cost Awareness
- Did the agent avoid unnecessary browser sessions?
- Did the agent avoid duplicate servers/ports?
- Did the agent avoid advanced CDP fallback unless needed?

## Output

Use:

```txt
Verification method:
Tool use justified:
Risk:
Next action:
```
