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

Managed PR labels are disposable projections only. They never authorize Ready for
Review, merge, issue closure, review resolution, production, publication,
protected-setting changes, credentials/IAM, or external-system writes.

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

Each invocation reacquires live PR evidence through the existing provider boundary.
If the head moves before any label mutation, the wrapper discards that stale result
and recomputes once from fresh evidence. A head move after mutation remains visible
as stale evidence and is not silently retried.

The lifecycle result preserves caller operation/result evidence separately from the
underlying reconciliation result, reports whether reconciliation was required, and
keeps all Ready-for-Review, merge, issue-closure, review-resolution, protected-setting,
production, and external-system authority fields false. Repeated unchanged calls
perform zero writes because the existing reconciler computes an empty managed delta.

This layer remains connector/operator driven. Future webhook, GitHub Actions,
scheduled, polling, or persistent automation must call the same package contract but
requires separately governed authorization and is intentionally not implemented here.

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
python -m pytest tests/agent_os_issue_labels -q
```

Repository acceptance still requires the executable `Agent OS Validation Gate`,
including repository structure validation and the authoritative exact-head
aggregate, plus required PR review checks.

## Boundary

Repository implementation does not itself authorize live managed-label writes.
Callers must separately authorize the triggering PR operation and any label mutation.
Live backfill, workflow/scheduled automation, merge, issue closure, Draft/Ready
mutation, review resolution, protected settings, credentials/IAM, production,
Notion, Drive, and classroom-artifact writes remain separately governed.
