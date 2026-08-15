# Agent OS Issue Label Checker

Local, fixture-first tooling for issue taxonomy evidence, safe application planning,
and bounded pull-request label reconciliation.

## Pull-request reconciliation

`scripts/agent_os_issue_labels/pr_reconciler.py` consumes the canonical PR-label
planner from `scripts/agent_os_issue_labels/pr_planner.py`; it does not define a
second label-state engine. The contract reads exact live PR evidence, verifies desired
managed labels exist, defaults to dry-run, requires separate label-write authorization,
rereads the exact head before mutation, changes only the canonical managed delta,
preserves unmanaged/human/security/dependency/third-party labels, proves convergence,
and reports partial failures without claiming synchronization. Finite batch processing
continues past item-local blockers.

Managed PR labels are disposable projections only; they never become lifecycle,
validation, review, merge, closure, production, or authorization truth. The executor
never creates labels. Missing managed labels fail closed as `managed-label-unavailable`.
Authorization remains governed by `00_Governance/write-authorization-policy.md` and
`01_Shared_Standards/github/excluded-surface-baseline.md`.

## Lifecycle integration

`scripts/agent_os_issue_labels/pr_lifecycle.py` is the thin operator/connector seam for
#1038 and reuses the #1022 planner plus #1023 reconciler. Supported invocations cover
Draft PR creation, head changes, terminal validation, Draft/Ready transitions, review
threads, branch freshness/conflict checks, and final-state readback.

For #1076, authorized Draft PR creation reacquires the live PR/head, invokes
`draft-pr-created`, reconciles only the managed delta, preserves unmanaged labels,
rereads for convergence, and keeps creation/reconciliation evidence separate. Optional
caller evidence is validated before provider access. A pre-mutation head move triggers
one fresh recomputation; a post-mutation move remains stale evidence and is not retried.
Repeated unchanged calls perform zero writes.

This layer is connector/operator driven; unattended trigger surfaces are not implemented.

## Governed stale-branch refresh

`scripts/agent_os_issue_labels/pr_branch_refresh.py` is the bounded #1187 seam for an
eligible `branch:behind` PR. Behind state is evidence, not mutation authority. Callers
must provide current explicit refresh authorization, exact base/head/current-main IDs,
allowed and forbidden path evidence, and required validation command identities.

The provider owns concrete rebase transport. Exactly one rebase attempt is admitted.
Moved head/base evidence, conflicted or unknown state, stale authorization, scope drift,
remote-head mismatch, ambiguous transport, or failure to prove `branch:current` all
fail closed. There is no merge-main fallback, automatic retry, Update Branch setting
change, or revival of retired connector-only #568 behavior.

A successful refresh creates a new exact head and invalidates prior validation,
tested-SHA, branch-freshness, review/approval applicability, merge authorization,
lifecycle reconciliation, candidate-runtime, and Ready-for-Review evidence. Scope is
rechecked before validation. Post-refresh order is fixed: prove the new head and scope;
run required validation; invoke #1038 for terminal validation state; converge managed
labels through #1022/#1023 while preserving unmanaged labels; then prove
`branch:current` against the same current-main identity.

If `main` moves before final proof, the result is stale and no second refresh occurs.
Failing validation may reconcile `validation:failing` / `pr:blocked`, but grants no
Ready-for-Review, merge, closure, workflow, repository-setting, production, or external
system authority.

## Issue-label tooling

The checker reads Agent OS issue-form output and the declarative label map, computes
expected labels, compares them with supplied labels, and renders an IA-style report.
The side-effect-free issue planner consumes an issue body, current labels, and an exact
repository-label catalog; its initial policy may approve only missing `agent-os`.

## Read-only workflows

Existing issue-label workflows remain read-only. No workflow is added or modified for
PR-label reconciliation, lifecycle integration, or branch refresh.

## Validation

```bash
python -m pytest tests/agent_os_issue_labels/test_pr_branch_refresh.py -q
python -m pytest tests/agent_os_issue_labels/test_pr_lifecycle.py -q
python -m pytest tests/agent_os_issue_labels/test_github_service_agent_draft_pr_contract.py -q
python -m pytest tests/agent_os_issue_labels -q
```

Repository acceptance still requires the executable `Agent OS Validation Gate`,
including repository structure validation, authoritative exact-head aggregate, and
required PR review checks.

## Boundary

Lifecycle and branch-refresh helpers report bounded evidence only. They grant no merge,
Ready-for-Review, closure, workflow, repository-setting, production, or external-system
authority. Follow the canonical write-authorization and excluded-surface policies above.
