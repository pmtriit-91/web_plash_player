# Debugging Workflow

When debugging:

1. Reproduce using the available information.
2. Identify the symptom and the boundary.
3. Trace the data flow / render flow.
4. Fix the root cause, do not just mask the error.
5. Check for side effects.

Do not guess the cause of the error without reading the related files.
Do not rewrite an entire component just to fix a minor bug.

## Hosted verification failure discipline

Treat hosted CI, remote build farms, and cross-platform runners as scarce final
evidence surfaces. They are not interactive debuggers.

When a hosted verification attempt fails:

1. Stop. Never press rerun repeatedly, never configure automatic retries, and never
   dispatch the same failed evidence tuple merely to see whether it changes.
2. Read the bounded compact summary or compact artifact first. It should identify the
   failing job, shard or case, conclusion, exit status, timeout state, and a redacted
   diagnostic hash in a few lines. Do not download or ingest the full raw log by
   default.
3. If the compact summary is missing or insufficient, retrieve only a bounded,
   targeted excerpt for the named failing boundary. Record why that excerpt was
   necessary. Full-log ingestion is an explicit last resort, never routine triage.
4. Pause and isolate one failure boundary. Reproduce the smallest relevant case
   locally, fix the root cause, then run the focused local check again.
5. Run the full relevant local acceptance path after the focused check is clean.
   Hosted-only uncertainty must be stated explicitly; local success must not be
   described as certainty about a different operating system or remote service.
6. Pin the clean source head, range base, workflow/config digest, intended environment,
   and local evidence. Dispatch that new tuple exactly once with zero automatic retry.
7. Monitor sparsely from compact status. Do not repeatedly stream or fetch verbose
   logs while the run is merely in progress. Inspect compact terminal artifacts once.
8. If the new attempt fails, it is a new diagnostic input: stop the hosted loop and
   repeat local isolation. Another dispatch requires a material remediation or an
   evidence-backed classification that the prior failure was external to the product.

This contract forbids blind reruns; it does not hide failures. Every hosted attempt
must remain attributable to one exact tuple, one stated reason, and one bounded
acceptance claim.
