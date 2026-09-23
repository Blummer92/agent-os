# Red-CI Continuation

Issue #1251 extends the existing #1188 Safe Implementation Lane continuation seam. A red authoritative CI result on the current PR head is a resumable checkpoint when the failure is classifiable, in scope, and repairable under the current authorization. Red CI does not itself require a new implementation prompt.

## Checkpoint identity

The bounded checkpoint preserves repository, issue, PR, branch, exact head SHA, failing check/run identity and conclusion, checkpoint lineage, last completed lifecycle action, and Scheduler execution/lease identity plus generation when applicable.

Head movement invalidates diagnosis and validation evidence bound to the older head. The caller must reacquire the live head before repair or readiness decisions.

## Finite lifecycle

The pure planner returns one next action:

```text
diagnose-existing-failure
repair-existing-lineage
run-focused-validation
reacquire-head
run-exact-head-aggregate
ready-for-review
blocked-diagnostic-surface
needs-decision
```

Failure classes are repository-repairable, stale-head, diagnostic-surface-unavailable, infrastructure-or-tooling, excluded-or-scope-expansion, and ambiguous.

Repository-repairable work stays on the existing issue/branch/PR/checkpoint/Scheduler lineage. The planner never creates or takes over a branch, PR, checkpoint, execution, or lease.

## Diagnostic boundedness

Diagnostic discovery is bounded to at most two distinct supplied surfaces. When one surface is unavailable and another already-authorized surface exists, the next action remains diagnosis through that alternative. Repeated surfaces and attempts beyond the bound are invalid input. If no actionable surface remains, the result is one explicit diagnostic blocker rather than an unbounded discovery loop.

## Validation ladder

After a repair, the planner requires focused validation first. A focused failure returns to diagnosis on the same lineage. A focused pass requires one authoritative aggregate bound to the live exact head. Aggregate evidence for another head is stale and cannot be combined with partial results to infer readiness.

A new red aggregate on the current head becomes the next durable checkpoint. A green current-head aggregate can reach `ready-for-review` only when no blocking review conversation remains. Ready-for-Review never implies merge or issue-closure authority.

## Ownership boundaries

This module does not implement #1235 general issue-gate recency reconciliation, #1237 execution-interface capability switching, #1200 semantic no-progress detection, #1201 cross-generation evidence compatibility, or #1187 base-branch refresh. It does not create a second CI system, validation authority, execution router, Scheduler, lease system, retry loop, or persistent checkpoint store.

The caller supplies current evidence and performs persistence, diagnosis, repair, validation, and lifecycle mutations through their existing owners.

## Authorization

The planner is non-authorizing. Its result keeps continuation, retry, merge, issue closure, and external-write authority false. Protected settings, workflows, credentials/IAM, cloud configuration, production, and external writes remain separately governed.

## Rollback

Remove `red_ci_continuation.py`, its focused tests, and this document. The existing #1188 continuation module, ResumePlan, Scheduler lease semantics, validation providers, issue lifecycle, and external systems remain unchanged.
