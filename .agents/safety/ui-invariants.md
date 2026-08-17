# UI Invariants

Do not arbitrarily break the project's UI invariants.

Always maintain:

- The existing visual hierarchy.
- The existing spacing rhythm.
- The existing component density.
- The existing modal/table/card patterns.
- The existing design tokens/themes.

Do not:

- Redesign the entire screen when only requested to modify a minor feature.
- Hardcode colors if the project uses a theme/token system.
- Mix multiple styling systems within the same module.
