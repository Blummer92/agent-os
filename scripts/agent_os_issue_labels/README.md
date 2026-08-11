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

### Trigger seam

Phase 1 is connector/operator driven. A caller may invoke one PR or a finite PR
batch during normal creation/cleanup or an explicitly authorized audit. Future
webhook, GitHub Actions, scheduled, or persistent reconciliation should call the
same executor, but those trigger/permission surfaces require separate approval and
are intentionally absent here.

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
for PR-label reconciliation.

## Validation

Focused PR reconciliation tests:

```bash
python -m pytest tests/agent_os_issue_labels/test_pr_reconciler.py
python -m pytest tests/agent_os_issue_labels
```

Repository acceptance still requires the executable `Agent OS Validation Gate`,
including repository structure validation and the authoritative exact-head
aggregate, plus required PR review checks.

## Boundary

Repository implementation does not itself authorize a live label backfill. Live
managed-label mutation, backfill, workflow/scheduled automation, merge, issue
closure, protected settings, credentials/IAM, production, Notion, Drive, and
classroom-artifact writes remain separately governed.
