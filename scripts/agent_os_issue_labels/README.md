# Agent OS Issue Label Checker

Local, fixture-first tooling for issue taxonomy evidence, safe application planning,
and bounded pull-request label reconciliation.

## Pull-request reconciliation

`scripts/agent_os_issue_labels/pr_reconciler.py` consumes the canonical PR-label
planner from `scripts/agent_os_issue_labels/pr_planner.py`; it does not define a
second label-state engine.

The reconciliation contract is:

- read exact live PR evidence and compute the canonical managed-label plan;
- verify every desired managed label exists in the supplied repository catalog;
- default to dry-run and perform zero writes;
- require separate `label_write_authorized=True` before managed-label mutation;
- reread the exact head immediately before mutation and fail closed if it moved;
- add only `labels_to_add` and remove only canonical managed `labels_to_remove`;
- preserve all unmanaged, human, security, dependency, and third-party labels;
- reread the PR after mutation and prove managed-label convergence;
- report partial/write/readback failures without claiming synchronization;
- continue finite batch reconciliation past item-local blockers.

Managed PR labels are disposable projections only. They never become lifecycle,
validation, review, merge, closure, production, or authorization truth. Authorization
remains governed by `00_Governance/write-authorization-policy.md` and
`01_Shared_Standards/github/excluded-surface-baseline.md`.

The executor never creates labels. If a required managed label is absent from the
repository label catalog, reconciliation returns `managed-label-unavailable` and
performs no mutation. Label creation remains a separately governed action.

## Lifecycle integration

`scripts/agent_os_issue_labels/pr_lifecycle.py` is the thin operator/connector
integration seam for #1038. It delegates label planning and mutation to the existing
#1022 planner and #1023 reconciler instead of defining new lifecycle or label logic.

Supported invocation reasons represent the normal GitHub Service Agent follow-ups:
Draft PR creation, head-SHA change, validation terminal state, Draft/Ready transition,
review-thread state change, branch freshness/conflict recheck, and final-state readback.

For #1076, an authorized Draft PR creation immediately reacquires the live PR/head, invokes `draft-pr-created`, reconciles only the managed delta while preserving unmanaged labels, rereads for convergence, and keeps creation/reconciliation evidence separate; this adds no unattended trigger.

Each invocation validates optional caller evidence before touching the provider, then
reacquires live PR evidence through the existing provider boundary. If the head moves
before any label mutation, the wrapper discards that stale result and recomputes once
from fresh evidence. A head move after mutation remains visible as stale evidence and
is not silently retried.

The lifecycle result preserves caller operation/result evidence separately from the
underlying reconciliation result, reports whether reconciliation was required, and
keeps explicit non-authority fields false. Repeated unchanged calls perform zero
writes because the existing reconciler computes an empty managed delta.

This layer is connector/operator driven. Future unattended trigger surfaces are not
implemented here; their authorization remains governed by the canonical policies
linked above.

## Governed stale-branch refresh

`scripts/agent_os_issue_labels/pr_branch_refresh.py` is the bounded #1187 seam for an
eligible PR that has already been classified `branch:behind`. Behind state is evidence,
not mutation authority. The caller must supply current explicit refresh authorization,
exact base/head/current-main identities, changed-path bounds, forbidden paths, and the
required validation command identities.

The refresh provider owns the concrete rebase transport. The orchestration contract
admits exactly one rebase attempt and fails closed on moved head/base evidence,
conflicted or unknown branch state, stale authorization, forbidden or expanded scope,
remote-head mismatch, ambiguous transport, or inability to prove the refreshed branch
is current. It does not fall back to merging `main`, retry automatically, change the
repository Update Branch setting, or revive the retired connector-only #568 method.

A successful refresh creates a new exact head. The result explicitly invalidates the
old head's validation, tested-SHA, branch-freshness, review/approval applicability,
merge-authorization, lifecycle-reconciliation, candidate-runtime, and Ready-for-Review
evidence. The changed-file scope is checked again before validation.

Required post-refresh order is fixed:

1. prove the new exact head and authorized changed-file scope;
2. run the supplied required validation commands against that head;
3. invoke the existing #1038 lifecycle hook for the terminal validation state;
4. use the existing #1022/#1023 reconciler to converge managed labels while preserving
   unmanaged taxonomy/human labels;
5. prove `branch:current` against the same current-main identity.

If `main` moves again before final proof, the result is stale and no second refresh is
attempted. A failing validation may reconcile `validation:failing` / `pr:blocked`, but
it never grants Ready-for-Review, merge, closure, workflow, or repository-setting
authority.

## Issue-label tooling

The checker reads Agent OS issue-form output and the declarative label map,
computes expected labels, compares them with supplied labels, and renders an
IA-style report.

The issue application planner is side-effect free. It consumes an issue body,
current labels, and an explicit repository-label catalog. Its initial policy can
approve only missing `agent-os`; owner/status and other findings remain governed
by their existing contracts.

## Read-only workflows

Existing issue-label workflows remain read-only. No workflow is added or modified
for PR-label reconciliation, lifecycle integration, or branch refresh.

## Validation

Focused lifecycle and PR reconciliation tests:

```bash
python -m pytest tests/agent_os_issue_labels/test_pr_branch_refresh.py -q
python -m pytest tests/agent_os_issue_labels/test_pr_lifecycle.py -q
python -m pytest tests/agent_os_issue_labels/test_github_service_agent_draft_pr_contract.py -q
python -m pytest tests/agent_os_issue_labels -q
```

Repository acceptance still requires the executable `Agent OS Validation Gate`,
including repository structure validation and the authoritative exact-head
aggregate, plus required PR review checks.

## Boundary

The lifecycle and branch-refresh helpers only report bounded evidence and never grant
merge, Ready-for-Review, closure, workflow, repository-setting, production, or external
system authority. For write authorization and excluded surfaces, follow
`00_Governance/write-authorization-policy.md` and
`01_Shared_Standards/github/excluded-surface-baseline.md`.
