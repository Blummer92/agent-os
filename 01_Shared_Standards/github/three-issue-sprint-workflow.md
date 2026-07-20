# Three-Issue Sprint Workflow

## Purpose

Define one repeatable Agent OS pattern for selecting, executing, reviewing, and refining three compatible GitHub issues as a coordinated sprint.

## Sprint Cycle

```text
select three compatible issues
-> execute coordinated lanes
-> publish sprint dashboard
-> investigate risks and update related issues
-> recommend the next sprint
```

## Selection Rules

A sprint should contain up to three issues that:

- have compatible dependencies;
- can use separate branches or clearly separated file surfaces;
- do not require conflicting source-of-truth changes;
- have a safe merge order;
- can be validated without unnecessary compute;
- include planning-only work when a dependency blocks implementation.

Do not treat three issues as parallel-safe merely because they are all open. File overlap, shared interfaces, workflow changes, and downstream dependencies must be checked first.

## Execution Prompt Contract

The coordinated execution prompt must:

- name the three issues and repository;
- assign one lane per issue;
- create separate branches and draft pull requests for implementation work;
- allow planning or contract work when an issue is not implementation-ready;
- prevent overlapping edits where practical;
- minimize Cloud Build use through fixture-first and focused validation;
- avoid merge, approval, branch-protection, required-check, and production-setting changes;
- track shared files, interface dependencies, blockers, stale assumptions, missing tests, and discovered risks;
- finish with one combined sprint dashboard.

## Risk Review And Backlog Refinement Contract

After execution, review the three issue lanes and directly related open issues.

Update existing issues when:

- dependencies changed;
- scope is stale;
- acceptance criteria need clarification;
- risks or test requirements are missing;
- implementation order changed;
- work was already satisfied elsewhere.

Create a new issue only when the work has a distinct owner, implementation boundary, validation requirement, or release decision. Do not create duplicate follow-up issues.

Risk-review work does not implement code or change production settings.

## Sprint Dashboard Contract

Every sprint dashboard must report:

- sprint goal and state;
- the three issue lanes;
- issue and pull-request status;
- completed and deferred scope;
- files changed;
- tests run;
- documentation updated;
- Cloud Build runs triggered;
- builds avoided when evidence exists;
- file overlap and merge-conflict risk;
- blockers and dependencies;
- risks discovered;
- issues that should be updated;
- recommended merge order;
- recommended next three-issue sprint;
- issues that must remain sequential.

Unknown values must be shown as unknown or not yet measurable. Do not invent build savings, cost, test, or readiness evidence.

## Low-Compute Default

Use this validation order unless an issue requires stricter evidence:

1. offline fixtures and unit tests;
2. static and configuration checks;
3. focused package tests;
4. one focused remote smoke test when required;
5. aggregate validation once on the final implementation head.

Avoid scheduled polling, persistent runners, duplicate remote builds, and repeated aggregate validation during iteration.

## Merge And Review Rules

- Keep implementation lanes on separate branches.
- Open draft pull requests by default.
- Do not merge from the coordinated sprint prompt.
- Reconcile interface changes before dependent implementation begins.
- Report the recommended merge order, but do not treat it as approval.

## Required Final Report

- files changed
- tests run
- docs updated
- unresolved blockers
- handoff recommendations
- remaining risks
