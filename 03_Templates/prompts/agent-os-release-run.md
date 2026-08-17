# Agent OS Release Run Prompt

Use high accuracy and medium thinking. Do not use deep research.

Repository: `<owner/repo>`
Pull request: `<number>`
Issue: `<number>`
Expected head SHA: `<sha40>`
Observed live PR head SHA: `<sha40>`
Current main SHA: `<sha40>`
Branch freshness: `<current|behind|conflicted|unknown>`
Validation head SHA: `<sha40>`
Current PR lifecycle state: `<draft|ready|merged|closed>`
Prior checkpoint phase/head/lifecycle state: `<values | none>`
Allowed changed files or bounded scope: `<scope>`
Authorized merge method: `<merge|squash|rebase>`
Canonical required workflow/check names: `<source-backed names>`
Authoritative aggregate check: `<exact check identity>`
Observed workflow/check conclusions: `<name -> conclusion>`
#1038 lifecycle reconciliation receipt: `<current receipt>`
#1187 branch-refresh receipt when a refresh occurred: `<receipt | none>`
#988 validation-failure evidence when a required check failed: `<bounded evidence | unavailable>`

Run the governed Agent OS release lifecycle using freshly reacquired GitHub evidence and `scripts/agent-os-release-run.py` as the deterministic state contract.

At every phase boundary, reacquire live PR head, current main, branch freshness/conflict, PR Draft/Ready/merged/closed state, validation evidence, review conversations, and managed-label reconciliation. Treat checkpoint values only as comparison evidence.

If the branch is behind, stop and route exclusively through #1187. Do not treat green CI, `branch:behind`, `branch:current`, or any other managed label as refresh or release authority. After #1187 changes the head, invalidate prior head-bound evidence, require exact-head validation on the new head, and require current #1038 reconciliation before continuing.

Terminal validation must have a converged #1038 receipt bound to the current exact head before Agent OS performs Ready-for-Review. After governed Draft -> Ready, reacquire live state and reconcile with the `draft-ready-transition` lifecycle hook before release classification.

If reacquisition shows Draft -> Ready, unexpected head movement, merge, or closure outside the current governed operation, do not continue from the old checkpoint. Reclassify from current evidence or return the deterministic external-transition stop emitted by the evaluator.

Green CI is evidence only. Stop separately for merge authorization and issue-closure authorization. Never infer either from implementation authorization, review completion, managed labels, or conversation continuity. Do not rerun workflows, dismiss reviews, delete branches, enable auto-merge, use merge queue, bypass protection, change required checks/repository settings, alter Scheduler lease semantics, or touch credentials/production/billing/external systems without separate explicit authorization.
