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

## Validation Loop

For routine Safe Implementation Lane work, use the smallest relevant focused local
validation first. A focused pass means `aggregate-pending`; it is useful developer
feedback but is not final validation success.

Do not require a duplicate local full aggregate solely before pushing when the
repository's clean exact-head GitHub CI will run the required full aggregate on
the exact final pull-request head. One clean exact-head CI aggregate may satisfy
the full-suite requirement.

Expand local validation only when focused tests fail, exact-head CI reports a
specific failure that needs diagnosis, CI is unavailable, or the governing issue
explicitly requires broader local validation. Focused success never suppresses,
replaces, or impersonates the required final aggregate, and Ready-for-Review still
requires all required exact-head checks to pass.

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
0.3.0

## Changelog
- 0.3.0 adds the focused-local -> authoritative exact-head aggregate validation loop without weakening final validation.
- 0.2.0 adds continuous internal routing and consolidated reporting for already-authorized Safe Lane work.
