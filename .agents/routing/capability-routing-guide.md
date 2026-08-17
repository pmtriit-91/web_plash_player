# Capability routing guide — V9.1.0

The JSON authority files are canonical; this file is explanatory only.

1. Resolve one workflow from `workflow-registry.json`.
2. Exclude any capability whose descriptor is not `active`.
3. Rank active candidates from deterministic triggers plus semantic fit in their
   compact descriptors; never inspect all skill bodies during routing.
4. Resolve at most one primary capability and return confidence, evidence,
   alternatives, permissions, conflicts, and exclusions.
5. Fall back to `standard_feature` below the policy threshold and emit a read-only
   capability-gap event for later research.
6. Load the named files only after the capability is relevant to user intent.
7. Treat vendor skills as task procedures, never as boot or policy authorities.
8. Escalate mode when scope or risk grows; do not broaden context pre-emptively.

Authority is separated deliberately:

- `capability-registry.json` maps compact triggers and load paths.
- `capability-descriptors.json` explains purpose, non-use, lifecycle, permission,
  provenance, token cost, evals, and compatibility.
- `capability-policy.json` defines confidence and non-bypassable activation gates.
- `capability-decisions.json` preserves immutable integration rationale.
- `vendor/vendor-lock.json` proves exact vendored bytes; it does not activate them.

FAST allows at most 6 planned files, STANDARD 16, and DEEP 50. These are scope
guards, not permission to edit files the user did not place in scope.
