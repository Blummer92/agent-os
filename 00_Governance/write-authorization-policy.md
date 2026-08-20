# Write Authorization Policy

- Default Notion, Sheets, Drive, and memory review to read-only unless an explicit standing authorization below or separate per-action approval applies.
- Do not write to production systems without explicit approval.
- Do not modify readiness, approval, audit, or source-of-truth fields automatically.
- Confirm target, system of record, field ownership, and authorization before any write.
- If authorization is unclear, stop and ask.

## Routine Notion Write Authorization

The repository owner grants standing authorization for bounded, routine Notion
writes only when they stay within all of these categories:

- non-governed teacher planning;
- lesson-candidate records;
- working knowledge;
- handoff notes and comments;
- non-authoritative attachments; and
- already-approved linked-view navigation updates.

Sensitive student or private data is excluded from this standing authorization.
Any action involving such data requires explicit per-action approval.

Before each routine write, identify the Agent OS task owner; resolve any legacy
agent alias; verify that the executing agent is a canonical agent listed in
`04_Registry/agent-inheritance-registry.md`; review that owner's overlay and its
referenced standards; verify the live Notion destination, the owner database or
owner page, field ownership when properties are involved, the source-of-truth
boundary, audit safety, and that the exact mutation remains inside this
routine-write lane.

This standing authorization does not override a stricter agent overlay, shared
standard, destination rule, or blocked write surface. An agent whose canonical
overlay blocks direct Notion writes does not gain that capability from this
policy alone.

The following remain approval-gated and are not standing-authorized: readiness
fields or decisions; approval fields; audit fields; source-of-truth or ownership
fields; schema changes; property additions, removals, renames, or type changes;
formulas or relations; source authority; provenance or safe-use authority; Unit
Generation Approval; Modeling Handoff Ready; Evidence Handoff Ready; Assessment
Handoff Ready; Source-Control Gate; Packet Generation Gate; Production
Authorized; verification status; sharing or permissions; page or database moves;
deletion, archive, or trash actions; duplicate cleanup or merges; historical-label
rewrites; bulk synchronization; automated row-writing; and scheduled write
automation.

Technical access through a Notion connector is not authorization. Unattended,
scheduled, bulk, synchronization-driven, or inference-driven row mutation is not
made routine by this policy. If task ownership, canonical agent identity or alias
resolution, destination, field ownership, source of truth, audit safety, or
authorization scope is missing, ambiguous, or unresolved, remain read-only and
route the action for explicit approval.

## Safe Repository Implementation

For an eligible open Tier 0 or Tier 1 GitHub issue, an explicit repository-owner
instruction may activate the bounded workflow in
`01_Shared_Standards/github/safe-implementation-lane.md`. Readiness alone does
not authorize implementation.

An ordinary implementation instruction may cover one non-protected branch, the
bounded scope envelope, corresponding offline tests and documentation, one draft
pull request, and Ready-for-Review after required exact-head validation passes
with no blockers. It does not authorize merge or issue closure.

For an eligible Tier 0 or Tier 1 GitHub issue whose canonical boundary is
`no-external-write`, the distinct repository-owner instruction
`work on #<issue> in fast lane` may also serve as the separate explicit owner
decision for merge and closure of that same implementation issue only when the
canonical `request-interpretation-v1` record carries `operating-mode=release`
for the exact issue. The request record remains non-authorizing evidence: record
the owner decision through the existing content-bound merge-authorization and
lifecycle-mutation authorization contracts, then let `IssueOperationalState`
project those current results. Never set merge/closure authority directly from
the request constraint. `operating_mode.py`, exact-head validation, server-side
review/merge rules, and terminal reconciliation must still independently admit
the action.

Tier 2 work cannot self-bootstrap through Terminal Fast Lane. Auto-merge, direct
protected-branch writes, protected settings/rulesets/required checks, workflow
changes, credentials/secrets/IAM/permissions, production, external-system writes,
governed-field mutation, source-of-truth changes, persistence-path changes,
irreversible actions, and other surfaces in
`01_Shared_Standards/github/excluded-surface-baseline.md` remain separately
authorized.
