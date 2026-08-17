# Token Budget — V9.1.0

`core/bootstrap.md` is the primary source deciding the mode. This file specifies behavioral budget.

## Token philosophy

- Do not read files just because they "might be useful".
- Only read files because they are "necessary for the current task".
- Do not use DEEP mode to handle FAST tasks.
- Do not enable the full creative pipeline if `creative-lite.md` is sufficient.
- Do not load vendor skills without a direct task match and valid vendor lock.

## Practical caps

### FAST
- Plan: 0–3 lines.
- Files context: file being edited + max 1 relevant skill.
- Reviewer: `review-lite.md` or no reviewer.
- Optional pack: forbidden.

### STANDARD
- Plan: short.
- Files context: workflow + skill + appropriate safety.
- Reviewer: lite first, deep only when necessary.
- Optional pack: metadata/registry only if needed.

### DEEP
- Plan: phased.
- Files context: selectively via router.
- Reviewer: deep per domain.
- Optional pack: whitelist/registry, do not read entire pack.

## Stop conditions

Stop opening additional files once you have enough to:
- understand the request
- know the files to edit
- know the constraints
- have appropriate checklists

If still lacking information, ask or search within the project instead of loading the entire OS.
