# Reviewer Workflow

After any significant change, self-review in the following order:

1. Does it meet the user's requirements?
2. Were changes made outside the scope?
3. Did it break API contracts?
4. Did it break UI patterns?
5. Is there duplicated logic/types/components?
6. Was any task-relevant skill applied without overriding repository evidence?
7. Is there a need to update memory/known decisions?

If risks are detected, report them clearly before continuing to expand the changes.

## Task capacity review

When the repository declares a Capacity Gate:

1. compare the whole workstep diff and executed verification with its original
   capacity envelope;
2. reject hidden extra behavior domains, writable paths, source/test size, case count,
   runtime, retry, or checkpoint expansion;
3. verify generated manifest/projection/receipt paths were listed separately and did
   not conceal non-generated scope;
4. require watchdog evidence for long commands and confirm descendant processes
   cannot keep the terminal open after timeout;
5. classify an exceeded threshold without `STOP_AND_SPLIT` as a blocker.
6. replay the same caller-supplied capacity envelope against the final diff and
   compare the primitive `reason_codes` and `offending_paths`; missing, invalid, or
   mismatched admission is a `STOP_AND_SPLIT` blocker.
7. when the envelope touches `.agents/_tools`, replay `root_cardinality` from the
   same resolved base and compare its `approved_direct_files`, `reason_codes`, and
   exact `offending_paths` with the final worktree;
8. allow an approved name only when the exact stable public entrypoint or global
   runner exception, owner, role, and nested caller path were committed at the Git base.
   A self-authorized worktree exception is a blocker.

The remedy for a capacity blocker is to preserve/inventory current bytes and create
bounded sub-plan/sub-task claims. Review must not waive or raise project thresholds
merely because implementation is already in progress.

## Governed reasoning review boundary

Với governed challenge hoặc decision review, reviewer dùng cùng canonical
governed-reasoning service nhưng giữ ownership khác planner. Reviewer phải khai báo
`critic relation`; cùng model, context hoặc acceptance oracle phải được ghi là
`correlated`, không được gọi là independent chỉ vì đổi vai trò.

Review phải chủ động falsify bằng counterexample, current source/Git và applicable
test/runtime evidence; kiểm mission drift, circular success criteria, outcome không
đo được, scope quá rộng, invariant không enforce được và product truth bị suy diễn.
Rubric hay research chỉ là challenge input và không tự tạo authority.

Reviewer không tự cấp authority, không tự apply persistence/recovery, không thay
matching intent/approval hoặc transaction gate. Kết quả challenge/decision giữ
nguyên reason semantics của service. Cumulative Phase Review Gate vẫn là gate riêng
theo work-governance contract; một governed challenge không thay thế gate đó.

## Documentation integrity review

When durable project documentation changed, verify:

1. placement matches the project-local documentation map or an evidence-backed
   existing convention;
2. the map owns navigation only and does not duplicate roadmap, current state, task,
   decision, or evidence authority;
3. human-readable summaries link to machine-readable task, handoff, receipt, or
   manifest authority instead of copying it;
4. new artifacts have a stable path, lifecycle, owner, consumer, and inbound link;
5. renames or moves preserve historical references, supersession, and affected
   hash/receipt validity;
6. raw conversation, chain-of-thought, secrets, cache, and ordinary command output did
   not enter durable documentation;
7. implementation and completion claims still have current source, Git, test, hosted,
   or runtime evidence.

Do not fail unrelated work merely because a project-local documentation map is absent.
Report the gap, and require map establishment only when documentation creation or
restructuring is part of the authorized scope.

## Cumulative phase review

Use the project's declared work-governance authority as the normative gate. This
workflow is an enforcement projection and must not create a second roadmap, phase
state, or review policy.

Trigger this review:

- before opening or decomposing a dependent major phase;
- before a phase release or final phase handoff;
- when verified hot context says the gate is due, missing, or
  `REMEDIATION_REQUIRED`;
- when the user explicitly asks for a cumulative roadmap or phase review.

Review from the last accepted cumulative checkpoint through the current phase. Cover
unresolved findings, all phase workstreams, current source, release provenance,
durable-evidence reachability, privacy/redaction, schema/runtime parity,
portability, recovery, and hosted evidence required by a claim. Apply the exact
acceptance criteria declared by project governance.

Persist one of `PASS`, `PASS_AFTER_REMEDIATION`, or `REMEDIATION_REQUIRED` in the
project's existing phase/current-state authorities. A blocker or
`REMEDIATION_REQUIRED` result prevents release, final handoff, and dependent-phase
activation. A report file or previous self-review is not sufficient without current
verification evidence.

## Receiving review feedback

Treat external feedback as a hypothesis to evaluate, not an instruction that
automatically widens scope. For each material item:

1. Restate the technical requirement and clarify interdependent unclear items.
2. Check it against current source, tests, supported versions, architecture, and
   prior user decisions.
3. Accept it when evidence supports it; push back with technical evidence when
   it is incorrect, unused, incompatible, or unnecessary.
4. Implement one coherent group at a time and verify the affected behavior.

Prefer a concise technical response over performative agreement. If the evidence
is insufficient, say what cannot be verified before changing code.
