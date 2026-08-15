# Safe Implementation Lane
## Purpose
Reduce procedural stops for routine repository work without weakening merge,
protected-branch, credential, production, external-write, or governed-field
controls.
## Eligibility
The lane is available only when all of these are true:
- the work is Tier 0 or Tier 1;
- the canonical issue is open and currently `status:ready`;
- GitHub is the source of truth and the issue declares `no-external-write`;
- the issue has one focused objective, resolved ownership, and no material blocker;
- exactly one primary pull request will claim the implementation issue; and
- the repository owner gives an explicit implementation instruction such as
  “work on #123.”
Tier 2, closed, blocked, stale, conflicting, cross-system, production,
credential, workflow, governed-field, source-of-truth, and irreversible work is
not eligible.
## Authorization Effect
For an eligible issue, the explicit implementation instruction authorizes:
- one non-protected branch;
- implementation within the issue's bounded scope envelope;
- corresponding offline tests and required documentation;
- one draft pull request; and
- Ready-for-Review after required exact-head validation passes and no blocker or
  unresolved blocking review conversation remains.
Excluded surfaces listed in
`01_Shared_Standards/github/excluded-surface-baseline.md` remain separately
unauthorized unless explicitly approved through the governing path.
A registered-owner transition is internal routing, not by itself a user-visible
handoff or stop. While this authorization, source of truth, and bounded scope
remain applicable, route to the responsible owner and continue in the same
interaction. Ownership and authority do not transfer: GitHub Service Agent stays
the sole repository writer and QA / Test Agent retains validation-evidence
ownership. Already-authorized tests, docs, in-scope repair, exact-head validation,
Draft PR maintenance, and Ready-for-Review may continue without a new user prompt.
Conversation continuity, including `continue`, `next step`, or `keep going`, never
authorizes a previously excluded surface.
## Execution Continuation
For a currently authorized Safe Implementation Lane issue, discovery of one existing valid issue-linked branch, Draft PR, or checkpoint lineage is normally a resume target, not a stop condition. Reacquire current repository, authorization, scope, ownership, checkpoint, exact-head, and canonical Scheduler lease evidence; consume the existing `ResumePlan`; and continue from the newest valid checkpoint when no active conflict exists.

An existing active Scheduler lease is the concurrency authority. Do not create a competing branch, PR, execution, or lease; do not steal, force-release, expire by age, or automatically retry an active or ambiguous lease. When the same authorized branch advances from SHA A to SHA B, reacquire B, inspect the head change, rebind current exact-head evidence, invalidate only the head-bound evidence required by existing contracts, and continue when authorization, ownership, and bounded scope remain valid. If `main` advanced and the PR branch is behind, route to the separately governed branch-refresh path rather than treating base drift as ordinary `HEAD_ADVANCED`.

Cancelled validation on stale SHA A may be projected as `SUPERSEDED_BY_NEW_HEAD` only when bounded evidence proves the old run was cancelled, the current PR head is different SHA B, a newer run/check for B exists in the same validation lane/concurrency group, and replacement/supersession evidence is current. A genuine test or configuration failure on A remains genuine failure evidence. Only validation bound to the current exact head may satisfy Ready-for-Review.
## Validation Loop
Follow the canonical focused-local and authoritative exact-head aggregate policy in
`01_Shared_Standards/global-engineering/testing-and-release.md`.
Issue-required focused or other developer-loop validation must be proven before
Draft PR creation. When those checks require runtime capabilities unavailable on
the active connector, reuse the canonical executor-routing contract and reroute to
a capable authorized surface before opening the PR; if no such route exists, stop
with `needs-decision`. `aggregate-pending` means only the authoritative final
exact-head aggregate remains pending, never an unexecuted issue-required
pre-PR check. Ready-for-Review still requires all required exact-head checks to pass.
## Bounded Scope Envelope
An eligible issue may name bounded areas instead of an exhaustive file list. The
envelope includes only changes directly necessary for the stated objective:
- implementation files in the named module or bounded area;
- directly corresponding tests and documentation;
- minimum package exports when the objective requires a public interface;
- architecture registration or classification required by existing tests; and
- generated manifests or changelog entries required by repository policy.
A support change must remain behaviorally subordinate and be listed in the pull
request report. It may not introduce a new subsystem, owner, schema,
compatibility break, credential, workflow, persistence path, or external effect.
Those are material changes and require `needs-decision`.
## Branch Names
A harness- or environment-assigned branch name is acceptable when it is
non-protected, linked to the issue, and used consistently. A preferred branch
name is guidance, not an authorization boundary.
Authorization boundary: It does not authorize merge, auto-merge, issue closure, protected-setting changes, or production or external writes; every other surface listed in `01_Shared_Standards/github/excluded-surface-baseline.md` remains separately unauthorized unless explicitly approved through the governing path.
## Operational Authorization Comments
The open issue body remains authoritative for durable objective, ownership,
scope, non-goals, and protected surfaces. When the body explicitly permits
comment-routed operational authorization, a dated repository-owner comment may
activate or pause implementation, smoke testing, or Ready-for-Review. A comment
may not broaden durable scope, authorize an excluded surface, contradict the
body, reactivate a closed issue, or authorize merge.
## Stop Conditions
Stop for `needs-decision` when evidence is ambiguous, stale, blocked, closed, or
conflicting, or when work would materially change architecture, ownership,
schema, compatibility, authority, external effects, protected settings, or the
issue objective. Do not stop solely for a registered-owner transition, a directly
corresponding test, in-scope repair, mechanical registration, required changelog
entry, or environment-assigned non-protected branch.
## Reporting
The pull request records the actual branch, all files changed, why each support
file was necessary, tests and exact-head evidence, docs, blockers, handoffs,
risks, rollback, and confirmation that merge and excluded surfaces remain
unauthorized. Prefer one consolidated user-facing result for routine internal
routing while preserving required handoff artifacts for owners and auditability.
## Version
0.5.0
## Changelog
- 0.5.0 makes existing authorized branch/PR/checkpoint lineage resumable through the canonical #895 ResumePlan and #758 Scheduler lease, separates same-branch `HEAD_ADVANCED` from #1187 base-behind refresh, and requires bounded proof before cancelled stale-head validation is classified as superseded (#1188).
- 0.4.0 requires issue-defined developer-loop validation on a capable route before Draft PR creation while preserving one final exact-head aggregate (#1077).
- 0.3.0 adds the focused-local -> authoritative exact-head aggregate validation loop without weakening final validation.
- 0.2.0 adds continuous internal routing and consolidated reporting for already-authorized Safe Lane work.
