# Post-PR State Audit Contract

## Purpose

Audit one terminal pull-request state and rank the best next issue from
normalized PR-health, subsystem, blocker, replacement, and candidate
evidence, without granting execution authority.

## Terminal States

- `merged`: the head landed with required checks verified.
- `review-complete`: review finished; a human lifecycle decision is next.
- `blocked`: work stopped before completion.
- `closed-unmerged`: the PR closed without landing anything.

## Contract

The audit is pure and deterministic. It consumes supplied normalized
evidence only and returns one typed result with stable reason codes and a
deterministic `audit_id`. It performs no GitHub, network, filesystem,
subprocess, environment, or credential I/O, executes no work, and mutates no
lifecycle state.

Repository/PR health (`healthy`/`degraded`/`unknown`) is reported separately
from subsystem maturity (`early`/`progressing`/`near-complete`/`complete`); a
healthy merge does not imply subsystem completion.

## Next-Issue Ranking

Eligible candidates are ranked in this order: an explicit dependency
unblocked by the completed PR, the current executable-lane/queue selection,
the same-subsystem architectural sequence, then the highest-leverage
end-to-end validation prerequisite. Closed, blocked, stale, claimed,
unauthorized, or superseded candidates are rejected before ranking.

Exactly one best issue is returned when confidence is high. At most one
alternate is returned only for a material tie at the best rank tier; a tie
across three or more candidates, or any incomplete or conflicting evidence
(a merged PR with no named capability, a closed-unmerged PR that claims a
landed capability, or an actionable blocker/replacement missing its issue
number), fails closed to `human_decision` instead.

## Terminal-State Behavior

- `merged`: prefer the highest-ranked unblocked issue in the same
  dependency chain, or `human_decision` if none is eligible.
- `review-complete`: always recommends `human_decision`.
- `blocked`: recommends the controlling blocker issue only when it is
  itself actionable; otherwise `human_decision`.
- `closed-unmerged`: recommends a verified replacement issue only when
  supplied; otherwise `human_decision`.

## Output

One typed result containing: what finished, repository/PR health, affected
subsystem and maturity, the recommended issue and at most one alternate, a
recommended executor route reused from the existing `ExecutorRoute`
vocabulary (never authority), a one-sentence rationale, the smallest next
action, and the governance footer fields (files changed, tests run, docs
updated, unresolved blockers, handoff recommendation, remaining risks)
echoed from supplied evidence. The compact formatted report is ordinarily
12-18 lines and always contains one next issue, one blocker, and one next
action line.

## Side Effects

None. The contract performs no network, GitHub, filesystem, subprocess,
environment, credential, Scheduler, lifecycle, or external-system operation.

## Version

1.0

## Changelog

- 1.0: initial deterministic post-PR state audit contract for #910.
