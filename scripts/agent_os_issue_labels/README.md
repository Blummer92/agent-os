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

For #1076, successful authorized Draft PR creation is explicitly bound to this
existing lifecycle seam as an immediate bounded follow-up. The GitHub Service Agent
must reacquire the new PR and exact live head, invoke `draft-pr-created`, reconcile
only the managed-label delta, preserve unmanaged labels, reread for convergence, and
keep PR-creation evidence separate from label-reconciliation evidence. This is an
operator/connector execution contract; it does not add an unattended trigger surface.

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
for PR-label reconciliation or lifecycle integration.

## Validation

Focused lifecycle and PR reconciliation tests:

```bash
python -m pytest tests/agent_os_issue_labels/test_pr_lifecycle.py -q
python -m pytest tests/agent_os_issue_labels/test_github_service_agent_draft_pr_contract.py -q
python -m pytest tests/agent_os_issue_labels -q
```

Repository acceptance still requires the executable `Agent OS Validation Gate`,
including repository structure validation and the authoritative exact-head
aggregate, plus required PR review checks.

## Boundary

The lifecycle helper only reports reconciliation evidence and never grants authority.
For write authorization and excluded surfaces, follow
`00_Governance/write-authorization-policy.md` and
`01_Shared_Standards/github/excluded-surface-baseline.md`.