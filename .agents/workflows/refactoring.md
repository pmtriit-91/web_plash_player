# Refactoring Workflow

Refactoring is only allowed when:

- Explicitly requested by the user, or
- Necessary to complete the task, and the scope is strictly bounded.

Before refactoring:

- Identify the current behavior.
- Identify the related public APIs/types/schemas.
- Identify tests or verification methods.

During refactoring:

- Do not change business behavior.
- Do not unnecessarily rename fields/APIs.
- Do not merge modules from different domains.
- Do not break the existing UI/UX.
