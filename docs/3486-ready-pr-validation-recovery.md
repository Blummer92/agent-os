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

Recovery invocations for the same PR/head share a concurrency group.
Run-history count includes unsuccessful attempts.

## Execution

The existing aggregate executor validates the exact candidate commit.
No second validation engine or alternative authoritative status is added.

The run must produce real validation jobs and terminal evidence.
Auxiliary green checks do not substitute for the authoritative aggregate.

## Current canary

PR #3486, candidate head
`868bd7e46a682adb9c31a215b829c25c0dc130f8`.

Source Validation Gate run: `38164744779`.

The repair is implemented separately on
`agent/3486-ready-validation-recovery`.

The candidate PR must remain unchanged.

## Acceptance limitations

Focused tests and a Draft repair PR are not live acceptance.

Before operational use, independently verify GitHub Actions
expression parsing, workflow-ref binding, permission handling,
run-history freshness, job execution, authoritative status
publication, and rejection of stale or forged evidence.

No merge, issue closure, lifecycle change, credential mutation,
or protected-setting change is authorized.
