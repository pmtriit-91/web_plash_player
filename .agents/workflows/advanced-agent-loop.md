# Advanced Agent Loop

Use this workflow for complex tasks where basic implementation is not enough.

## Loop

1. **Orient**
   - Read current project memory.
   - Inspect real files.
   - Confirm framework, stack, architecture, and constraints.

2. **Route**
   - Select only the necessary skills.
   - Resolve at most one primary capability from the active registry.
   - Load a locked vendor skill only when its task procedure is directly relevant.

3. **Plan**
   - Produce a short implementation plan.
   - Identify impacted files.
   - Identify risks and rollback points.

4. **Execute**
   - Make focused changes.
   - Do not refactor unrelated files.
   - Preserve public APIs, routes, data contracts, and UI invariants.

5. **Verify**
   - Run available typecheck, lint, tests, and build.
   - If tools are unavailable, perform static review.

6. **Review**
   - Check architecture, UI consistency, performance, accessibility, and security.

7. **Learn**
   - Update project memory only with durable facts from the current project.
   - Never store stale assumptions or memory from another project.
