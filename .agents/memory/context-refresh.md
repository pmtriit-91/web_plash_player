# Context Refresh Protocol — V9.1.0

Context Memory is a project-bound index of verified records, not a transcript and
not a substitute for current source.

When starting a new session or large task:

1. Follow the root bridge and run the Agent OS lifecycle doctor.
2. Continue only when the lifecycle state permits project context.
3. If `project/context/context-manifest.json` exists, run:

   ```bash
   python3 .agents/_tools/agent_os_context_memory.py doctor
   ```

4. Load hot context only when the diagnosis is `FRESH`. A `STALE` result may be
   inspected as non-authoritative evidence; `DEGRADED` blocks memory authority.
5. Reconcile every relevant record with its source refs, current Git, and direct
   dependencies before mutation.
6. Load warm context just in time. Load cold research only when the task needs it.

NotebookLM and other external memory surfaces are cold research inputs. They cannot
provide project identity, active-task authority, or completion evidence.
