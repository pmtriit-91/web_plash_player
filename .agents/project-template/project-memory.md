# Project Memory Projection Template

Do not maintain a second handwritten memory catalog here. Initialize the
project-owned Context Memory stores from `project-template/context/**`, then let the
Context Memory engine generate `skills/project-memory/SKILL.md` as a compact hot/warm
projection.

The generated skill is discoverable by compatible clients but is not the database.
It becomes authoritative only when Agent OS is `BOUND` and Context Memory is `FRESH`.
