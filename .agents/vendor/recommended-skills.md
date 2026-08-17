# Vendor admission policy — V9.1.0

There is no popularity-based recommended list. A repository appearing on GitHub
Trending is a research lead, not an installation decision.

Admit the smallest useful subset only after all gates pass:

1. redistribution-compatible license verified at the pinned revision;
2. immutable 40-character commit recorded;
3. exact path allowlist and SHA-256 hashes recorded;
4. content, instruction, script, secret, and dependency review completed;
5. routing conflict and behavioral evals passed.

Candidates without clear redistribution rights remain study-only and must not be
copied into the release.

When a repository is a competing agent harness, prefer adapting a small general
principle into an existing Core contract over importing its bootstrap, hooks, router,
memory, subagent, Git, or installation behavior. Record the inspected commit and local
influence in `vendor/vendor-lock.json`.
