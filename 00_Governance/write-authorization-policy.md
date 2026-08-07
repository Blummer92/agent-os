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

Before each routine write, verify the canonical or otherwise authorized agent,
the live Notion destination, the owner database or owner page, field ownership
when properties are involved, the source-of-truth boundary, and that the exact
mutation remains inside this routine-write lane.

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
made routine by this policy. If agent identity, destination, field ownership,
source of truth, or authorization scope is ambiguous, remain read-only and route
the action for explicit approval.

## Safe Repository Implementation

For an eligible open Tier 0 or Tier 1 GitHub issue, an explicit repository-owner
instruction may activate the bounded workflow in
`01_Shared_Standards/github/safe-implementation-lane.md`. Readiness alone does
not authorize implementation.

That instruction may cover one non-protected branch, the bounded scope envelope,
corresponding offline tests and documentation, one draft pull request, and
Ready-for-Review after required exact-head validation passes with no blockers.

Excluded surfaces listed in
`01_Shared_Standards/github/excluded-surface-baseline.md` remain separately
authorized.
