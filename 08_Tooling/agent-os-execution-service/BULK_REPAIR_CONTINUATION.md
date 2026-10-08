# Finite bulk-repair continuation

Issue: #2487. Canonical generic continuation owner: #2220. Shared-repair
continuation hardening: #2664. Population-proven shared stop: #3369 / #2602
Decision A (comment 6041308224).

## Purpose

`classify_agent_os_bulk_repair_continuation_tool` exposes the existing
`scripts.agent_os_issue_acceptance.batch_repair_continuation` projection to the
Agent OS execution-service host.

The tool freezes the requested PR set supplied by the caller, consumes only
per-candidate disposition and parent-authorization currentness evidence, and
returns the existing finite-batch next
action. It does not execute a repair, retry a blocked mutation, select a new
candidate population, create a scheduler/queue, or mutate GitHub.

## Item-local versus shared blockers

An item-local `blocked` disposition is recorded for that PR while later requested
PRs remain in `remaining_pull_requests`. The returned continuation action is
`reacquire-next-candidate`, so a safety-layer denial, conflict, or failed-repair
gate on one candidate does not become a parent-batch stop by itself.

A shared diagnosis is not automatically terminal. When affected candidates
identify one `shared_blocker_key`, one canonical `shared_repair_owner`, and
`shared_repair_available=true`, the projection returns
`advance-shared-repair`. This keeps the parent batch non-terminal while the
existing owner advances the one shared repair instead of encouraging unrelated
changes on every affected PR.

After canonical evidence says that shared repair completed, the same affected
candidate set returns `reacquire-shared-repair-candidates`. Callers must
reacquire the affected PR heads/checks and re-evaluate exact-head validation;
the old blocked classifications cannot satisfy batch completion.

A shared blocker terminates the parent batch only when no governed canonical
repair path is supplied and matching current evidence proves the blocker across
every remaining actionable candidate. An unvisited PR or a deferred/reacquire
candidate without that blocker defeats the halt and requires bounded
reacquisition. One candidate's shared claim never stops independent remaining
PRs.

`parent_authorization_current=false` is the deterministic equivalent for a
genuine whole-parent authorization invalidation. The caller supplies normalized
current evidence about the parent authorization, independently of candidate
reason codes. Invalidation prevents every requested repair under that parent
authorization and takes precedence even over an available shared repair. It
returns `halt-shared-blocker` and preserves unvisited PRs for final reporting.
The optional input defaults to `true` for existing callers and requires a built-in
boolean; neither value grants execution or write authority.

For example, with requested PRs `[30, 31, 32]`, one provider-blocked PR 30
leaves PRs 31 and 32 unproven and returns `reacquire-next-candidate`. Matching
unrepairable provider evidence for all three permits `halt-shared-blocker`.
Separately, `parent_authorization_current=false` with no candidate evidence
halts immediately, preserves all three unvisited PRs, and leaves delivered and
reconciled candidate counts at zero. A halt therefore never pads finite-batch
delivery accounting or bypasses the exact-attempt CKR6 retry boundary.

All current shared-blocker evidence in one projection must agree on blocker
identity, repair owner, availability, and completion state. Conflicting shared
repair evidence fails closed instead of guessing which repair path owns the batch.
Without an explicit blocker key, the candidate reason code identifies the
blocker, so distinct unkeyed diagnoses cannot be collapsed into one shared stop.

## Failed-repair boundary

Retry-specific Lessons Learned remain owned by the canonical CKR6 failed-repair
path. The bulk projection accepts the existing normalized retry-boundary evidence
and reports whether re-entry is required, admitted, or blocked for the exact
candidate. It never grants retry mutation authority.

## Partial Git-object effects

Partially created unattached Git objects are represented as candidate evidence,
not as a repaired disposition. The projection performs no Git-object mutation and
cannot convert those objects into completion or authority.

## Authority

The tool is classification-only. `execution_authorized`,
`github_writes_authorized`, `mutation_authorized`, `merge_authorized`, and
`side_effects_performed` remain false. A repairable-shared-blocker action names
continuation work only; it grants no repair or GitHub-write authority.

Merge, issue closure, workflows, protected settings, credentials, production,
and external-system writes remain outside this contract.
