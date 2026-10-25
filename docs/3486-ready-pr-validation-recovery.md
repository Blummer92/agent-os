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

## Ingress-origin recovery (#2410)

A governed issue-comment dispatch is admitted as an alternative to direct
owner dispatch, under verification that is strictly stronger than actor
alone:

- The comment grammar is fixed: `/agent-os recover-ready <pr> <head>
  <main> <workflow> <source-run-id>`, admitted for the repository owner
  and the ChatGPT service actor for this operation only.
- The governed ingress job re-verifies the PR, live main, workflow
  revision, source-run identity, zero-job evidence, and the two-attempt
  budget, then dispatches the validation workflow on `main` with the
  ingress run id and trigger id as correlation inputs.
- The validation workflow admits an ingress dispatch only when its actor
  is the ingress job's token identity (`github-actions[bot]`) AND it
  independently fetches the ingress run record and receipt artifact from
  GitHub and verifies every binding, the recomputed trigger id, and the
  content-derived receipt id (`scripts/agent_os_ready_recovery_ingress.py`).
  Forged, stale, mismatched, duplicated, or unavailable evidence fails
  closed. Direct owner dispatch is unchanged; supplying ingress inputs
  never upgrades it, and no blanket service-actor admission exists.
- Fork pull requests are rejected on both sides: the ingress dispatch
  and the validation-side ingress check both require the PR head to
  live in the same repository.
- Receipt-publication race (#3732): the ingress job dispatches validation
  before it publishes its receipt artifact, so validation may check
  before the evidence exists. The validation side therefore waits, via
  the script's `wait-and-verify` mode, only for the already-identified
  ingress run and its single receipt artifact, with fixed bounds (300s
  run wait at 10s polls, 60s artifact grace at 5s polls). Pending
  evidence (run queued/in_progress, artifact not yet listed) is awaited;
  terminal failure (completed run with a non-success conclusion,
  duplicate artifacts) fails immediately; timeout, provider failure,
  forged evidence, or mismatch fails closed. No workflow is dispatched
  while waiting, and every trust check runs in full after the evidence
  arrives. The direct owner-dispatch path is unchanged and never waits.

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
