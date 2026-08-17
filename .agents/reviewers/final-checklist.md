# Final Checklist

Before completing the task:

- Meets user requirements exactly.
- No modifications outside the scope.
- Does not violate current repository contracts or active skill boundaries.
- Does not break memory/project conventions.
- No obvious type/import errors.
- Clearly reports changed files and remaining risks.
- **Static Hard-Validator:** You MUST pass static analysis (TSC, ESLint) before any LLM (Validator Subagent) begins its code review. Use the project-specific TSC command from `project/testing-config.md` (default: `tsc --noEmit -p tsconfig.app.json` for Project References configs). Do not let the LLM override or ignore static testing failures.
- **Manifest Sync Enforcement:** If any `.agents/` OS files were modified, you MUST update the Changelog and run `update-manifest.py` (or the equivalent integrity scripts) before finalizing.
