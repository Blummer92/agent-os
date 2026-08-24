# Agent OS Release Run Prompt

Use high accuracy and medium thinking. Do not use deep research.

Repository: `<owner/repo>`
Pull request: `<number>`
Issue: `<number>`
Expected/observed head SHA: `<sha40>`
Current main SHA and branch freshness: `<sha40> / <current|behind|conflicted|unknown>`
Validation head SHA: `<sha40>`
Current PR/issue lifecycle state: `<state>`
Prior checkpoint comparison evidence: `<values | none>`
Bounded changed-file scope: `<scope>`
Authorized merge method: `<merge|squash|rebase>`
Current Ready-for-Review / merge / closure authorization projections: `<booleans + evidence refs>`
Canonical required checks and authoritative aggregate: `<source-backed identities>`
Observed check conclusions: `<name -> conclusion>`
#1038 lifecycle reconciliation receipt: `<current receipt>`
#1187 branch-refresh receipt when applicable: `<receipt | none>`
#988 failure-attribution evidence when applicable: `<bounded evidence | none>`
Terminal checkpoint/ResumePlan and exact lease-disposition receipts after merge: `<receipts | not yet applicable>`

Run the governed release lifecycle with freshly reacquired evidence and `scripts/agent-os-release-run.py` as the deterministic ordering contract.

At every phase boundary, reacquire live head/base/freshness, Draft/Ready/merged/closed state, validation, reviews, and lifecycle reconciliation. Checkpoints are comparison/resume evidence, not authority. A behind branch routes only through #1187; stale or prior-head validation never satisfies the refreshed head.

Green CI and managed labels never create authority. Ordinary Safe Lane normally has no merge/closure authorization and therefore stops at those boundaries. An eligible Terminal Fast Lane request may already carry current merge/closure authorization through the canonical `request-interpretation-v1` -> `IssueOperationalState` -> `operating_mode.py` path; when that evidence is present, do not ask for a duplicate user prompt solely because the phase changed.

After verified governed merge, follow terminal reconciliation in order: completion pointer, checkpoint/ResumePlan lineage terminalization, exact lease disposition/release when required, implementation-issue closure, `final-state-readback` lifecycle reconciliation, and one final report. Never force-release or steal a lease, infer authority from continuation language, rerun workflows, dismiss reviews, delete branches, enable auto-merge, bypass protection, change protected settings/required checks, or touch credentials/production/external systems without their separate governing authorization.
