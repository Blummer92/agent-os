# Routine Repository Coding Hot Path

## Purpose

Define the minimum Agent OS context and transitions for ordinary Tier 0/1 `no-external-write` repository coding while preserving existing authorization, exact-head validation, and ownership contracts.

This is a composition rule, not a new router, state model, cache, agent, Scheduler, or authorization system.

## Minimum hot path

For a direct bounded implementation request whose current evidence proves the ordinary path applies:

```text
canonical request interpretation
-> live issue + existing lineage acquisition
-> Safe Implementation Lane / IssueOperationalState admission
-> connector-native execution when sufficient
-> bounded implementation
-> smallest useful focused validation when applicable
-> Draft PR
-> one authoritative exact-head aggregate
-> final PR/head/review reconciliation
-> result
```

## Routine applicability

The minimum path applies only when current evidence proves all of the following:

- Tier 0 or Tier 1;
- `no-external-write`;
- one focused repository objective;
- GitHub Service Agent owns implementation;
- no active/ambiguous Scheduler lease;
- no resume/checkpoint lineage requiring recovery;
- no branch-behind/diverged condition requiring governed refresh;
- no red-CI/review remediation state;
- no runtime capability beyond the connected GitHub surface for the exact next action;
- no release-mode request;
- no finite multi-item mission;
- no classroom/PPUX routing requirement.

## Lazy paths

The following are conditionally activated and are not part of the routine hot context unless their canonical trigger is present:

- Coding Decision/ADR retrieval: call the existing CKR10 planner; `retrieval_required=false` means zero Decision reads.
- Lessons Learned retrieval: call the existing CKR6 planner; `retrieval_required=false` means zero Lessons Learned reads.
- execution-surface routing beyond connector-native: only when the exact next action needs runtime/process/local-Git capability.
- checkpoint/ResumePlan: only for an existing resumable execution lineage.
- Scheduler lease: only for governed runtime/concurrency execution.
- branch refresh: only for proven behind/diverged base state.
- PR remediation: only for actual CI/review repair.
- finite-mission reconciliation: only for an explicit finite multi-item mission.
- Terminal Fast Lane: only for the canonical structured `operating-mode=release` request.
- classroom/PPUX routing: only when canonical request/context evidence resolves there.

## Evidence reuse

Within one same-lineage operation, reuse immutable facts already proven for repository identity, canonical ownership, issue objective, and stable scope. Reacquire only freshness-sensitive evidence required by its existing owner, including current issue state, authorization applicability, PR/head/base, validation, reviews, and execution/lease state.

Do not introduce a new cache or Task State Capsule.

## Authority and validation

This hot path does not reduce authorization or validation. GitHub remains source of truth; GitHub Service Agent remains sole repository writer; QA/Test remains independent evidence owner; excluded surfaces remain separately gated; only current exact-head validation can satisfy readiness.

## Version

0.1.0
