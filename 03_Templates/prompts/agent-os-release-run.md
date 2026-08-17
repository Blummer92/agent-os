# Agent OS Release Run Prompt

Use high accuracy and medium thinking. Do not use deep research.

Repository: `<owner/repo>`
Pull request: `<number>`
Issue: `<number>`
Expected head SHA: `<sha40>`
Allowed changed files or bounded scope: `<scope>`
Authorized merge method: `<merge|squash|rebase>`
Canonical required workflow/check names: `<source-backed names>`
Authoritative aggregate check: `<exact check identity>`
Observed workflow/check conclusions: `<name -> conclusion>`
#988 validation-failure evidence when a required check failed: `<bounded evidence | unavailable>`

Run the governed Agent OS release lifecycle using current GitHub evidence and `scripts/agent-os-release-run.py` as the deterministic state contract.

Reacquire the canonical required validation set from current issue/repository policy; do not let this prompt or a shorter caller-supplied list weaken it. Fail closed when the canonical set or authoritative aggregate identity cannot be proven. A missing, stale, pending, cancelled, timed-out, `not_triggered`, unexpectedly skipped, failed, or unknown required check is not success. Unrelated green checks do not substitute for the authoritative aggregate.

When a required validation check fails, use the existing #988 classifier rather than guessing from a red banner. A proven PR regression may route to bounded in-scope repair. Inherited-main, CI infrastructure/configuration failure, or insufficient evidence blocks. If setup or infrastructure fails before aggregate validation runs, report that validation did not complete; do not call it a code/test regression.

Continue automatically through read-only verification and transitions already authorized by the issue. Reacquire exact-head evidence after every write. Fail closed on head drift, scope drift, requested changes, unresolved blocking review conversations, ambiguous linked issue, or stale evidence.

Stop separately for merge authorization and issue-closure authorization. Never infer either from green CI, review completion, implementation authorization, or conversation continuity. Do not rerun workflows, dismiss reviews, delete branches, enable auto-merge, bypass protection, change required checks/repository settings, or touch credentials/production/billing/external systems without separate explicit authorization.

At each stop return the current phase, classification, exact head, validation classification when available, blockers, side effects performed, and one compact next-action/approval request. After authorized merge, verify the merge commit and resulting `main`. After separately authorized issue closure, post the completion record before closing the issue.
