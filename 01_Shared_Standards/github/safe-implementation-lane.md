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

## Internal Owner Routing

A transition between registered Agent OS owners is internal routing, not by
itself a user-visible handoff or stop. While the same Safe Implementation Lane
authorization remains applicable, ChatGPT may continue the interaction through
the responsible owners instead of returning serial copy/paste prompts.

Ownership does not transfer: the GitHub Service Agent remains the sole repository
write owner, QA / Test Agent remains the validation-evidence owner where
applicable, and other registered owners retain their governed responsibilities.
Internal routing creates no new authority and does not widen the issue scope.

The lane may continue through directly corresponding implementation, tests,
documentation, in-scope failure diagnosis and repair, exact-head validation,
Draft PR maintenance, and Ready-for-Review when those actions are already covered
by the current authorization.

Conversation continuity is not authorization. Phrases such as `continue`,
`next step`, and `keep going` may continue only actions already covered by the
current authorization; they never authorize a previously excluded surface.

Surface a user-visible stop when authorization, source of truth, bounded scope,
or a material decision changes. Preserve internal handoff artifacts when a
canonical owner or audit trail requires them, but prefer one consolidated
user-facing result for successful routine work.

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
corresponding test, in-scope failure diagnosis or repair, mechanical registration,
required changelog entry, or environment-assigned non-protected branch.

## Reporting

The pull request records the actual branch, all files changed, why each support
file was necessary, tests and exact-head evidence, docs, blockers, handoffs,
risks, rollback, and confirmation that merge and excluded surfaces remain
unauthorized. User-facing completion should consolidate routine internal routing
rather than require separate owner-by-owner handoff prompts.

## Version

0.2.0

## Changelog

- 0.2.0 adds continuous internal owner routing for already-authorized Safe Implementation Lane work while preserving all existing ownership, scope, and excluded-surface boundaries (#986).
- 0.1.0 established the bounded Tier 0/1 Safe Implementation Lane.
