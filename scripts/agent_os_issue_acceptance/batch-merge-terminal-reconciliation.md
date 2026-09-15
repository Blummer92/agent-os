# Batch Merge Terminal Reconciliation

Issue: #2458

A successful pull-request merge readback is not terminal for a finite batch candidate when that pull request has a linked implementation issue.

`batch_merge_execution.py` remains the finite sequential merge coordinator. After merge readback it now pauses at a post-merge reconciliation boundary for candidates with a canonical linked issue. The caller supplies the current projection from `batch_post_merge_reconciliation.py`; the coordinator does not duplicate issue-completion, closure-authorization, or lifecycle-admission rules.

A normal converged implementation candidate therefore reaches terminal accounting only after:

1. exact PR merge readback;
2. linked-issue post-merge reconciliation;
3. any separately admitted `status:ready` cleanup and/or issue closure through the existing GitHub Service Agent write path; and
4. canonical final readback proving the PR remains merged, the issue is closed, and stale readiness is absent.

Item-local lifecycle blockers (for example remaining issue scope, missing/stale closure authority, parent/tracking identity, or manual-review evidence) are recorded for that candidate and do not stop later independent PRs. Shared provider/currentness failures continue to halt the bounded batch.

This composition creates no `merge => close` shortcut. `batch_post_merge_reconciliation.py`, lifecycle mutation authorization/admission, `IssueOperationalState`, and the GitHub Service Agent remain the canonical owners of completion, authority, currentness, mutation, and readback. The coordinator only sequences those existing owners.
