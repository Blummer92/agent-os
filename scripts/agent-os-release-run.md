# Agent OS Release Run

`agent-os-release-run.py` is the deterministic, offline policy/state evaluator for the governed release lifecycle in #903. It does not call GitHub, merge, close issues, rerun workflows, dismiss reviews, delete branches, enable auto-merge, or change protected settings.

## Contract

An operator or connector gathers fresh GitHub evidence, writes it as JSON, and runs:

```bash
python scripts/agent-os-release-run.py evidence.json
```

Required evidence includes repository, pull request number, issue number, expected and observed PR head SHA, current `main` SHA, current branch freshness state, the SHA to which authoritative validation is bound, bounded changed-file scope, authorized merge method, observed check conclusions, the canonical required-check set, the authoritative aggregate validation identity, current PR lifecycle state, review-thread state, and the current #1038 managed-label reconciliation receipt.

The evaluator consumes the public receipts produced by the existing lifecycle contracts instead of duplicating them:

- #1038: `PullRequestLifecycleReconciliationResult`-shaped evidence, including `reconciliation_status`, `invocation_reason`, and `verified_head_sha`;
- #1187: `PullRequestBranchRefreshResult`-shaped evidence, including old/new head identity, head-evidence invalidation, refreshed-head validation, and post-refresh lifecycle reconciliation.

Managed labels such as `pr:*`, `validation:*`, `branch:*`, and `review:*` are derived cache only. They never grant Ready-for-Review, merge, closure, refresh, or any other authority.

## Phase-boundary reacquisition

The release operator must reacquire live PR state at every phase boundary and rebuild the evidence object. A checkpoint may carry only the prior `checkpoint_phase`, `checkpoint_head_sha`, and `checkpoint_pr_lifecycle_state`; those values are comparison evidence, not authority.

The evaluator fails closed when reacquisition proves:

- unexpected head movement not explained by a converged #1187 receipt;
- Draft -> Ready outside the current governed operation;
- merge or closure outside the current governed operation;
- lifecycle state inconsistent with the prior checkpoint.

Draft -> Ready outside Agent OS returns an `external-transition` result and requires a fresh reclassification from the current Ready state. External merge/closure is terminal for the stale release-run checkpoint.

## Branch freshness and #1187

`branch_state` must be `current`, `behind`, `conflicted`, or `unknown` and must be derived from current GitHub evidence against the supplied current `main` SHA.

- `behind` is always `BLOCKED` and routes only to `route-through-gh-life3-1187`;
- `conflicted` and `unknown` fail closed;
- green validation on a behind head is never release-ready;
- a `branch:current` managed label cannot substitute for live freshness evidence.

After #1187 advances the PR head, the release-run requires the refresh receipt to prove the old/new head transition, required head-bound evidence invalidation, green validation on the refreshed head, and converged post-refresh lifecycle reconciliation. The top-level `validation_head_sha` must equal the current observed PR head; prior-head green validation is stale by definition.

## #1038 managed-label reconciliation

Before governed Ready-for-Review or release classification, current terminal validation must be followed by a current #1038 reconciliation receipt. The receipt must be converged, bound to the exact observed head, and have a release-current invocation reason such as `validation-terminal`, `draft-ready-transition`, `branch-state-rechecked`, or `final-state-readback`.

A missing, failed, or stale reconciliation blocks. Stale managed labels never compensate for a stale receipt. Unmanaged taxonomy, human, security, dependency, and third-party labels remain outside the release evaluator and are not mutated by it.

## Validation

The canonical required-check set is source-backed evidence, not a caller-controlled shortcut. If it is missing, if the authoritative aggregate identity is unavailable, if the aggregate is omitted, or if `validation_head_sha` differs from the live PR head, the evaluator blocks. Unrelated green checks never substitute for the required aggregate lane.

The release evaluator reuses completed #988 validation-failure classification. `pr_regression` may produce `NEEDS_FIX` inside existing scope; inherited-main failure, CI infrastructure/configuration failure, and insufficient evidence remain `BLOCKED`. Green CI is evidence only and never creates merge authorization.

## Ready-for-Review and merge

A Draft PR with all gates green and `ready_for_review_authorized=true` stops at `ready-for-review` with `perform-ready-for-review-at-exact-head`. The operator performs that already-authorized GitHub transition, reacquires live state, runs/requires #1038 `draft-ready-transition` reconciliation, and evaluates again. Only then may the run reach `merge-authorization-pause`.

Merge still requires separate `merge_authorized=true` and exact-head execution with the approved method. Issue closure remains a separate authorization after post-merge verification and completion-record publication.

## Mobile and desktop usage

Use `03_Templates/prompts/agent-os-release-run.md` on mobile or desktop. Gather the same fresh evidence with the GitHub connector or CLI, run the evaluator, perform only its bounded next action, and reacquire before the next phase. Never continue from a stale checkpoint after a human or another tool changes head, Draft/Ready state, merge state, or closure state.

## Safety

This tool is evidence evaluation, not a privileged release bot. It never infers merge or issue-closure authority. Workflow reruns, review dismissal, branch deletion, auto-merge, merge queue, bypass, protected settings, required-check configuration, credentials, production, billing, Scheduler lease changes, and external-system writes remain separately unauthorized.
