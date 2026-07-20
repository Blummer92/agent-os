# Issue Lifecycle Standard

## Purpose

Define the three-level Agent OS work lifecycle and remove duplicated
coordination text. It governs how work is described, not what is
authorized, and changes no readiness, approval, capability, execution,
ownership, or write-authorization rule.

## Boundary

Inherits `00_Governance/write-authorization-policy.md`,
`issue-acceptance-automation.md` (tiers, readiness, acceptance evidence),
and `protected-branch-governance.md`. Readiness, approval, capability, and
execution authorization remain separate states; stale, blocked, invalid,
or ambiguous evidence stays fail-closed.

## Three Work Levels

Normal work uses exactly three levels; more require a governance decision.

### Level 1 — Roadmap issue

Contains only: objective, ownership, major sequence, major dependencies,
active child implementation issues, current next step, major unresolved
decisions, and links to canonical risk owners in
`04_Registry/risk-owner-map.md`. Durable phase definitions stay in
`05_Roadmap/`; the roadmap issue owns live sequencing. Must not contain:
implementation allowlists, full test commands, full authorization
language, PR evidence, full child bodies, copied risk text, or embedded
"current main SHA" claims that go stale on the next merge.

### Level 2 — Implementation issue

Contains: one objective, dependencies, exact allowed files, required
behavior, acceptance tests, issue-specific stop conditions, authorization
state, and a reference to the required final report. Canonical boilerplate
is linked, not pasted. One normal implementation issue is completed by one
focused PR.

### Level 3 — Pull request

Owns implementation evidence: files changed, exact source head, tested SHA
or synthetic-merge SHA, tests and results, required checks, review
findings, unresolved blockers, rollback, and remaining risks. The PR does
not repeat the issue specification. Exactly one open primary PR may claim
an implementation issue; a superseded PR is closed with a pointer comment.
Two active PRs claiming the same issue is a `needs-decision` stop.

## Child-Issue Creation Test

Split a child issue only when all are true: independent objective;
different allowlist; independently mergeable; standalone value; combining
would make one PR unsafe or oversized. Otherwise use acceptance criteria,
checklist items, or regression tests in the existing issue.

## Canonical Boilerplate By Reference

Link, do not paste: write authorization
(`00_Governance/write-authorization-policy.md`), final report
(`01_Shared_Standards/global-engineering/final-report-standard.md`),
validation commands (`scripts/validate-all.sh`,
`07_Agent_Tests/validate-repo-structure.sh`), protected-branch and
exact-SHA rules (`protected-branch-governance.md`), and PR evidence
headings (`.github/PULL_REQUEST_TEMPLATE.md`). Issue-specific stop
conditions and acceptance criteria always stay in the issue body.

## Issue-Body Maintenance

The issue body is authoritative. When a decision changes the contract,
edit the body and add one concise dated comment naming what changed and
why; edit history preserves prior text. Do not leave a stale body behind
contradictory comments, and do not treat comments as outranking the body.

## Risk Ownership

Each cross-cutting risk has exactly one canonical owner issue, recorded
in `04_Registry/risk-owner-map.md`; other issues and PRs link to the
owner instead of copying risk text.

## Closure And Supersession

Close a planning issue with one dated handoff comment once its
implementation-ready children exist. Close duplicates with a pointer to
the canonical item. Preserve links; never rewrite closed historical bodies.

## Label Policy

Minimal set: `agent-os`, one `owner:*`, one `status:*`
(`ready|blocked|needs-decision`), optionally one `type:*` and one
`epic:*`. Treat `planning`, `type:documentation`, `phase-4`,
`adapter-migration`, and bare `workflow-scheduler` as legacy aliases of
`type:planning`, `type:docs`, and `epic:workflow-scheduler`; do not add
them to new issues. Do not delete or rename any label until
`.github/labeler/agent-os-issue-label-map.yml` and its workflows are
migrated by a separate bounded change.

## Version
0.1.0
