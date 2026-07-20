# Three-Issue Sprint Workflow

## Purpose

Define one repeatable pattern for selecting, executing, reviewing, and refining up to three compatible GitHub issues.

## Sprint Cycle

```text
select compatible issues
-> execute coordinated lanes
-> publish sprint dashboard
-> investigate risks and update related issues
-> recommend the next sprint
```

## Selection Rules

A sprint may contain up to three issues that:

- have compatible dependencies and source-of-truth boundaries;
- use separate branches or clearly separated file surfaces;
- have a safe merge order;
- can be validated without unnecessary compute;
- use planning-only work when implementation is dependency-blocked.

Open issues are not automatically parallel-safe. Check dependencies, shared files, governed surfaces, interfaces, and validation needs first.

## Execution Contract

The coordinated prompt must:

- name the repository and issue lanes;
- preserve implementation, planning-only, review, and blocked modes;
- use separate branches and draft pull requests for implementation;
- minimize Cloud Build through fixture-first and focused validation;
- avoid merge, approval, branch-protection, required-check, and production-setting changes;
- track shared files, dependencies, blockers, missing tests, and discovered risks;
- finish with one combined Sprint Dashboard.

## Risk And Backlog Contract

Every risk must include category, severity, status, owner, affected issue or roadmap references, evidence, recommended action, and due phase.

Allowed actions are:

- update an existing issue;
- update the roadmap;
- create an ADR;
- create a new issue for distinct work;
- close or merge duplicate work;
- mark needs-decision;
- take no action.

Unowned risks must route to needs-decision. Create a new issue only for a distinct owner, implementation boundary, validation requirement, or release decision.

## Dashboard Contract

Every dashboard must report:

- sprint goal, state, evidence mode, freshness, and provenance;
- lane and pull-request status;
- files changed, tests run, docs updated, and validation evidence;
- Cloud Build runs and builds avoided when evidenced;
- risk register with severity and affected issues;
- Risk Delta and unowned-risk count;
- issue impact and recommended GitHub changes;
- blockers, dependencies, merge order, and sequential-only work;
- recommended next sprint.

Unknown values remain unknown. Do not invent build savings, confidence, test, readiness, or cost evidence.

## Low-Compute Default

1. Offline fixtures and unit tests.
2. Static and configuration checks.
3. Focused package tests.
4. One focused remote smoke test when required.
5. Aggregate validation once on the final implementation head.

Avoid polling, persistent runners, duplicate remote builds, and repeated aggregate validation during iteration.

## Merge And Reporting Rules

- Keep implementation lanes on separate branches.
- Open draft pull requests by default.
- Reconcile interface changes before dependent implementation begins.
- A recommended merge order is not approval.
- Do not merge from the coordinated sprint prompt.

Every final report includes files changed, tests run, docs updated, unresolved blockers, handoff recommendations, and remaining risks.
