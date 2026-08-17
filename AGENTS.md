# Universal Agent OS bridge

Read `.agents/AGENTS.md` and follow its boot contract before project work.

Run the repository-local read-only doctor to derive Agent OS state. If the OS is
`UNBOUND` or `DEGRADED`, do not load Project Memory as authority, execute Project
Adapter commands, or mutate project source. Safe inspection, integrity verification,
and an explicitly approved repair remain allowed.

When the lifecycle state is `BOUND` and a Context Memory manifest exists, run its
read-only doctor. Load only a `FRESH` hot projection; stale, conflicting, or
contaminated memory never overrides current repository evidence.
