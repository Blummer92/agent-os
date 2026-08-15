# Agent OS Release Run Prompt

Use high accuracy and medium thinking. Do not use deep research.

Repository: `<owner/repo>`
Pull request: `<number>`
Issue: `<number>`
Expected head SHA: `<sha40>`
Allowed changed files or bounded scope: `<scope>`
Authorized merge method: `<merge|squash|rebase>`
Required workflow/check names: `<names>`

Run the governed Agent OS release lifecycle using current GitHub evidence and `scripts/agent-os-release-run.py` as the deterministic state contract.

Continue automatically through read-only verification and transitions already authorized by the issue. Reacquire exact-head evidence after every write. Fail closed on head drift, scope drift, missing/non-success required checks, requested changes, unresolved blocking review conversations, ambiguous linked issue, or stale evidence.

Stop separately for merge authorization and issue-closure authorization. Never infer either from green CI, review completion, implementation authorization, or conversation continuity. Do not rerun workflows, dismiss reviews, delete branches, enable auto-merge, bypass protection, change repository settings, or touch credentials/production/billing/external systems without separate explicit authorization.

At each stop return the current phase, classification, exact head, blockers, side effects performed, and one compact next-action/approval request. After authorized merge, verify the merge commit and resulting `main`. After separately authorized issue closure, post the completion record before closing the issue.
