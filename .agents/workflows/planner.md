# Planner Workflow

Before coding, the agent must determine:

1. What type of task is this?
2. Which files/modules are involved?
3. Which skills need to be activated?
4. Is there a risk of breaking APIs/UI/business flows?
5. What is the minimum scope of change?

The plan's output should include:

- Objective
- Scope
- Expected related files
- Risks
- How to test

If the task is small, the plan can be very brief but must still demonstrate scoping awareness.

## Task Capacity Gate

Before an implementation claim or source mutation:

1. inspect the repository-declared durable-work governance and use its Capacity Gate
   as normative authority;
2. declare one primary outcome and one independently reviewable behavior domain;
3. list exact writable paths, separating generated manifest/projection/receipt paths
   from non-generated source and tests;
4. estimate the non-generated source/test diff; if it cannot be estimated, plan an
   inventory-only task first;
5. state the executable-case budget and every potentially long command's timeout,
   heartbeat, process-tree termination, and retry policy;
6. name the independent Final Review, checkpoint, and handoff boundary.
7. require a caller-supplied capacity envelope (base commit, exact paths, artifact
   classes, and budgets) and record the primitive admission before source mutation;
   missing or invalid admission is `STOP_AND_SPLIT`, never an inferred threshold.
8. when a declared path is `.agents/_tools` or below it, require the same capacity
   admission to include `root_cardinality` from its resolved base; a new direct-root
   name is `STOP_AND_SPLIT` unless an eligible exception was already committed;
9. accept an exception only by exact name from topology at the Git base, with an
   owner, a `stable-public-entrypoint` or `global-runner` role, and a committed
   nested caller path. A worktree exception cannot self-authorize the same diff.

If any declared threshold is crossed, output `STOP_AND_SPLIT` and make the
current plan an index of bounded sub-plans/sub-tasks. Do not code first and decompose
later. If an unexpected overrun appears during execution, preserve and inventory the
current bytes, then close, hand off, or supersede the oversized claim before opening
smaller scopes.

When no repository Capacity Gate is declared, still produce the bounded fields above
but do not invent project thresholds or a second governance authority.

## Governed reasoning boundary

Khi yêu cầu có nhiều phương án, uncertainty, authority hoặc permission/risk đáng kể,
planner phải dùng canonical governed-reasoning service qua adapter hiện hành; không
tạo router thứ hai hoặc một nguồn decision authority cạnh tranh.

Planner chỉ chuẩn hóa request và governed plan sau khi Binding, confirmed Genesis,
current intent, policy cùng applicable approval/transaction gates có evidence hợp
lệ. Thiếu application-owned policy hoặc authority thì fail closed; release template
không tự trở thành policy của project.

Planner phải công khai alternative, assumption, unknown, confidence, exact scope,
acceptance và evidence. Planner không được tự phát hành challenge/reviewer verdict,
không tự tạo product truth và không dùng score để vượt constitution hay risk policy.
Persistence chỉ bắt đầu bằng reviewable plan; apply/recovery luôn cần explicit
confirmation đúng transaction.

## Durable documentation routing

When the task will create, rename, move, or materially restructure durable project
documentation:

1. inspect repository instructions, durable-work governance, and the project-local
   documentation map if one exists;
2. classify each artifact as policy, roadmap, current state, phase/milestone plan,
   analysis, decision, evidence, task, handoff, or projection before choosing a path;
3. identify the single canonical authority and every machine-readable authority that
   must remain separate;
4. check inbound references and historical hash/receipt dependencies before proposing
   a move;
5. update or supersede an existing authority before creating a new file;
6. name the artifact's owner, lifecycle, consumer, and validation in the plan.

The release-owned `project-template/documentation-map.md` is an adaptation scaffold,
not project state. A missing project-local map does not block boot or unrelated code
work. Establish or repair a map only when documentation governance is within the
authorized task scope.
