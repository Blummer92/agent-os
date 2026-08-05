# Write Authorization Policy

- Default Notion, Sheets, Drive, and memory review to read-only.
- Do not write to production systems without explicit approval.
- Do not modify readiness, approval, audit, or source-of-truth fields automatically.
- Confirm target, system of record, field ownership, and authorization before any write.
- If authorization is unclear, stop and ask.

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
