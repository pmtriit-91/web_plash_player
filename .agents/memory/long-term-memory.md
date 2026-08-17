# Long-Term Memory Protocol

Durable project memory uses the machine-readable Context Record contract. Store an
item only when it is supported by current files, Git evidence, a project decision,
or explicit user confirmation.

Use warm records for decisions, architecture, conventions, and known issues. Use
cold records for research and history. Every record must include evidence paths and
their current hashes; the engine marks drift instead of allowing stale memory to win.

Do not store raw conversations, prompts, reasoning traces, temporary debugging logs,
unconfirmed speculation, secrets, or copied NotebookLM answers. A milestone update
is a two-phase proposal and apply operation; it never commits or pushes.
