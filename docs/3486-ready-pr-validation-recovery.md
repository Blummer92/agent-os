# Ready PR zero-job validation recovery

## Purpose

Recover authoritative exact-head validation for an already-Ready PR
whose original GitHub Actions validation run concluded
`action_required` without executing any jobs.

This is not a code-test repair, Draft promotion, merge authorization,
or permission to weaken required checks.

## Admission

The existing validation workflow accepts an explicit `ready_recovery`
dispatch only when:

- The PR is open and already non-Draft.
- The authenticated dispatch actor is the repository owner.
- The candidate head, current main SHA, and workflow revision are exact.
- The workflow runs on its identified, unchanged workflow branch.
- The source Validation Gate run belongs to the candidate PR/head.
- The source run concluded `action_required` with zero jobs.
- Provider-backed recovery history is available.
- The existing two-attempt recovery limit is not exceeded.

The workflow-wide concurrency group keeps manual runs distinct
before admission, using their unique GitHub run IDs.

The aggregate-validation job separately serializes all manual
workflow dispatches for this repository using trusted GitHub
event identity. Caller-supplied PR numbers do not select the group.

GitHub may replace a pending manual validation job with a newer
pending job; running jobs are not canceled by this rule.
Ordering is not guaranteed. Provider run history is still used
to enforce the bounded two-attempt recovery limit, including
unsuccessful and canceled attempts.

## Execution

The existing aggregate executor validates the exact candidate commit.
No second validation engine or alternative authoritative status is added.

The run must produce real validation jobs and terminal evidence.
Auxiliary green checks do not substitute for the authoritative aggregate.

## Current canary

No qualifying canary vehicle is currently identified (checked 2026-10-12):
none of the open Ready PRs exhibits an `action_required` zero-job
Validation Gate run. The live canary remains pending a qualifying Ready PR
and the repository owner's explicit canary authorization; a canary must not
be manufactured on an unsuitable PR.

The recovery mechanism itself is merged to main via PR #3523
(commit `d3a9a1e2`); it no longer lives on a separate branch.

## Acceptance limitations

Focused tests and a Draft repair PR are not live acceptance.

Before operational use, independently verify GitHub Actions
expression parsing, workflow-ref binding, permission handling,
run-history freshness, job execution, authoritative status
publication, and rejection of stale or forged evidence.

No merge, issue closure, lifecycle change, credential mutation,
or protected-setting change is authorized.
