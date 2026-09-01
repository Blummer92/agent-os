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
## Activation Preflight
Treat lane activation as one consolidated decision over live issue eligibility, current readiness, direct repository-owner operational authorization, excluded surfaces, and existing branch/PR/checkpoint/lease lineage. Durable issue or handoff text such as `execution_authorized=false` means that artifact does not grant authority by itself; it is not a permanent veto on a later fresh direct repository-owner instruction that this standard recognizes as authorization. `status:ready` remains readiness metadata, not execution authority.
If an otherwise eligible Tier 0/1 issue is missing only the mechanical `status:ready` prerequisite, the issue is not yet lane-eligible. Surface the required readiness intervention at most once when policy requires owner approval. After that authorized mutation converges to canonical `status:ready`, reuse the same still-current direct implementation instruction and continue without asking for `continue`, `authorized`, or a second `work on` instruction. Do not carry the instruction across `status:blocked`, `status:needs-decision`, stale/conflicting scope or ownership, an excluded surface, or an active/ambiguous execution lease.
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
Follow the canonical validation-obligation and execution-location policy in
`01_Shared_Standards/global-engineering/testing-and-release.md`.
Required validation must be routed to a capable authorized executor; it is not
inherently a local/manual pre-Draft-PR command. Prefer the active/local route when
available. When runtime capability is unavailable there, reuse the canonical
executor-routing contract. If an existing governed CI route is the capable route,
Draft PR creation may stage the validation and the lane may remain Draft while
that evidence is pending. Do not require the user to copy/paste shell commands
solely because the active connector cannot execute them. If no capable authorized
local, governed-runner, or existing governed CI route exists, stop with
`needs-decision`.
A CI-routed pending state grants no Ready-for-Review or later authority. Only
required evidence bound to the current exact head may satisfy Ready-for-Review;
stale-head CI is insufficient. When the existing exact-head CI aggregate subsumes
the focused checks, one clean exact-head aggregate may satisfy both obligations
without duplicate local execution. Preserve the repository's current CI trigger
policy: this lane does not require aggregate validation on ordinary Draft PR
updates and does not create or modify a workflow to obtain validation.
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
## Bounded Diagnosis Correction
A corrected diagnosis, target component, or implementation seam discovered during
an already-authorized issue is not by itself a material scope change. Reacquire the
live issue, current authorization, source of truth, objective, owner, bounded scope,
and excluded-surface evidence before deciding whether to continue.

Classify the discovery as a bounded correction and continue under the same current
implementation instruction when all of these remain true:
- the underlying issue objective is unchanged;
- the corrected target is directly necessary to solve the same proven defect;
- GitHub remains the source of truth and the same canonical implementation owner
  applies;
- directly corresponding tests and documentation remain behaviorally subordinate;
- no new subsystem, material architecture/schema/compatibility/ownership change,
  persistence path, credential, workflow, protected setting, production action,
  external write, irreversible action, merge authority, or issue-closure authority
  is required; and
- no stale, conflicting, blocked, or ambiguous evidence invalidates the current
  authorization envelope.

For a bounded correction, update the issue or handoff with the corrected root
cause, target, and authorization-basis evidence when GitHub is the canonical source
of truth, then continue without requiring ritual user phrases such as `re-scope and
continue`, `continue`, or a second `work on` instruction. The correction must be
reported in the pull request so the changed implementation seam remains auditable.

Classify the discovery as a material scope change and stop with `needs-decision`
when it changes the underlying objective, source of truth, canonical owner,
authority envelope, architecture/schema/compatibility contract, persistence or
external effects, or enters an excluded surface. Conversation continuity never
converts a material scope change into authorization.
## Terminal Fast Lane
The exact repository-owner instruction `work on #<issue> in fast lane` is interpreted only through the canonical `request-interpretation-v1` path. The ChatGPT Orchestrator must not re-parse raw language downstream. For the exact already-bound GitHub issue, a fresh direct-user interpretation may carry the structured constraint `operating-mode=release`; ordinary `work on #<issue>`, `continue`, `next step`, `keep going`, a mismatched target, Tier 2, or any declared external write must not produce that constraint.

The structured release request is consumed by `scripts/agent_os_issue_acceptance/operating_mode.py`, which remains the single mode/authority ceiling. `RequestedMode.RELEASE` never creates authority. When the request is the repository-owner decision for merge or implementation-issue closure, preserve its validated request identity/provenance as decision evidence and use the existing content-bound authorization owners: the normal merge-authorization candidate/decision/applicability path for merge and the normal lifecycle-mutation authorization/admission path for `close-issue`. `IssueOperationalState` projects those canonical results; no Fast-Lane code may set merge/closure authorization booleans directly.

Terminal progression then reuses the existing `scripts/agent-os-release-run.py` release/reconciliation state machine and existing lifecycle, branch-refresh, validation, and label-reconciliation contracts rather than introducing another Fast-Lane parser or terminal controller. A release request removes duplicate prompting only while the existing authorization records remain current; head/base/scope drift, expiry, review blockers, stale lifecycle evidence, or any other canonical invalidation still stops progression.

Within an active Terminal Fast Lane authorization envelope, a safely admitted `branch:behind` refresh through the existing #1187 `pr_branch_refresh.py` contract needs no second user prompt solely because `main` advanced; its exact base/head identity, scope, mergeability, authorization, and validation checks remain fail-closed. Terminal Fast Lane never widens Tier-2, protected-setting, workflow, credential, production, or other excluded-surface authorization.

## Branch Names
A harness- or environment-assigned branch name is acceptable when it is
non-protected, linked to the issue, and used consistently. A preferred branch
name is guidance, not an authorization boundary.
Ordinary Safe Implementation Lane: It does not authorize merge, auto-merge, issue closure, protected-setting changes, or production or external writes. A fresh eligible Terminal Fast Lane interpretation may carry merge and implementation-issue closure intent only through the existing canonical authorization gates; every other surface listed in `01_Shared_Standards/github/excluded-surface-baseline.md` remains separately unauthorized unless explicitly approved through its governing path.
## Operational Authorization Comments
The open issue body remains authoritative for durable objective, ownership,
scope, non-goals, and protected surfaces. When the body explicitly permits
comment-routed operational authorization, a dated repository-owner comment may
activate or pause implementation, smoke testing, or Ready-for-Review. A comment
may not broaden durable scope, contradict the body, reactivate a closed issue, or
bypass the canonical request-interpretation and operating-mode authority gates.
## Stop Conditions
Stop for `needs-decision` when evidence is ambiguous, stale, blocked, closed, or
conflicting, or when work would materially change architecture, ownership,
schema, compatibility, authority, external effects, protected settings, or the
issue objective. Do not stop solely for a registered-owner transition, a directly
corresponding test, in-scope repair, bounded diagnosis correction under the
contract above, mechanical registration, required changelog entry, or
environment-assigned non-protected branch.
## Reporting
The pull request records the actual branch, all files changed, why each support
file was necessary, tests and exact-head evidence, docs, blockers, handoffs,
risks, rollback, and the applicable authorization boundary. Prefer one
consolidated user-facing result for routine internal routing while preserving
required handoff artifacts for owners and auditability.
## Version
0.9.0
## Changelog
- 0.9.0 defines evidence-backed bounded diagnosis correction (#1594): same-objective corrections may update the canonical issue/handoff and continue under the still-current implementation instruction, while objective, authority, source-of-truth, ownership, architecture/schema/compatibility, persistence/external-effect, and excluded-surface changes still fail closed with `needs-decision`.
- 0.8.0 separates required validation from its execution location, allows Draft PR staging when existing governed CI is the capable executor, forbids false manual-command stops, preserves current Draft/Ready CI trigger semantics, and keeps exact-head evidence mandatory before Ready-for-Review (#1595).
- 0.7.0 adds opt-in Terminal Fast Lane (#1309) by composing the canonical `request-interpretation-v1` record, existing content-bound merge/lifecycle authorization records, `operating_mode.py` release ceiling, #1187 branch refresh, and `agent-os-release-run.py` terminal progression. No second raw-language parser, lifecycle stage, router, authority model, or terminal controller is introduced.
- 0.6.0 distinguishes artifact non-authority from later direct-owner authorization, consolidates activation preflight, and carries one current instruction across a single mechanical readiness intervention without weakening fail-closed stops (#1274).
- 0.5.0 makes existing authorized branch/PR/checkpoint lineage resumable through the canonical #895 ResumePlan and #758 Scheduler lease, separates same-branch `HEAD_ADVANCED` from #1187 base-behind refresh, and requires current replacement evidence before cancelled stale-head validation is classified as superseded (#1188).
- 0.4.0 requires issue-defined developer-loop validation on a capable route before Draft PR creation while preserving one final exact-head aggregate (#1077).
- 0.3.0 adds the focused-local -> authoritative exact-head aggregate validation loop without weakening final validation.
- 0.2.0 adds continuous internal routing and consolidated reporting for already-authorized Safe Lane work.