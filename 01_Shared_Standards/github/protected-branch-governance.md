# Protected Branch Governance

## Purpose

Define one shared Agent OS policy for protected repository branches. This file
governs behavior only; it does not configure GitHub settings or enforcement.

## Applicability

This standard applies to human operators, registered agents, scripts, and approved
automation acting on Agent OS repositories that adopt it.

## Protected Branches

`main` is the default protected branch. Additional protected branches require an
approved governance change naming the branch, owner, reason, and enforcement path.

## Normal Change Path

Changes to a protected branch must:

1. begin on a descriptive non-protected branch;
2. link to an approved issue or GitHub Change Request;
3. use a pull request;
4. include the required implementation or review report;
5. run relevant available validation; and
6. resolve blocking review conversations before merge when supported.

A passing report is evidence, not merge authorization.

## Prohibited Ordinary Operations

Without an approved emergency exception, do not:

- commit or push directly to a protected branch;
- force-push or perform another non-fast-forward update;
- delete a protected branch;
- bypass required pull-request or review controls;
- weaken protection to complete ordinary work; or
- treat `--no-verify` or another local bypass as authorization.

## Local Safeguards

Hooks and local checkers are advisory controls. They may be absent, bypassed, or
misconfigured and are not equivalent to server-side GitHub enforcement.

Local safeguards must implement this policy by reference, avoid secrets and
unnecessary network access, preserve unrelated hooks or fail safely, and support
installation, verification, bypass warning, and removal documentation.

## Emergency Exceptions

An exception is allowed only for urgent repository recovery when normal pull-
request flow cannot safely meet the need. It requires explicit repository-owner
or authorized-administrator approval whenever feasible.

Record the exact branch, change, actor, reason, available validation, rollback,
and audit location before the action when feasible. Afterward, record the result,
validation, rollback status, unresolved risks, and corrective follow-up.

An exception must be narrow, time-bounded, and limited to the approved action. It
does not create a standing bypass.

## Settings And Required Checks

Changing rulesets, branch protection, required checks, merge queues, bypass actors,
permissions, or related settings requires a separate approved GitHub Change
Request. Documentation does not authorize activation.

A separate approved Change Request supplies protected-setting authority; it does
not by itself require a second execution identity. After exact authorization is
current, the canonical GitHub Service Agent may execute an existing finite,
content-bound protected-setting implementation when repository/target/operation
identity is fixed, fresh pre-state is bound immediately before mutation, stale or
expanded input fails closed, canonical post-write readback is immediate, and
rollback is bounded. This path must not accept arbitrary API paths, commands,
ruleset IDs, check names, permissions, credentials, or payload expansion. Missing
capability or any invariant remains a stop.

Required-check decisions remain governed by issue #216. CI diagnosis and exact
check-identity evidence remain governed by issue #228.

## Ownership

- GitHub Service Agent owns approved repository implementation and PR execution.
- QA / Test Agent owns validation evidence and safeguard test quality.
- Integration Manager supports cross-system and required-check coordination.
- Repository owner or authorized administrator approves emergency exceptions and
  protected-setting changes.

## Reporting

Report files changed, tests run, docs updated, unresolved blockers, handoff
recommendations, and remaining risks.

## Version

0.2.0

## Changelog

- 0.2.0 narrows #2644's redundant execution-surface gate for already-authorized finite protected-setting operations without granting generic administration.

## Authoritative aggregate commit status (#2589)

The Agent OS Validation Gate publishes the commit status
`agent-os/authoritative-aggregate`, the canonical future required-check identity
for `main`. Lifecycle:

- Ordinary Draft PR runs publish nothing under this context, so Draft or
  deferred validation can never satisfy it.
- An authoritative run (non-Draft PR run or admitted final-candidate dispatch)
  publishes `pending` before checkout and tests, then exactly one terminal state:
  `success` only after a real aggregate success, `failure` for an aggregate
  failure, `error` for cancellation or infrastructure failure, and `pending`
  (non-authorizing) when exact-current main health withholds authority.
- Ready-for-Review reuse consults only the newest status for the exact head.
  Only a newest `success` is reusable; a newer `failure`, `error`, or `pending`
  defeats an older `success`, and a missing status requires a run (#2761).
- `statuses: write` is granted only to the `validate` and `aggregate-gate`
  jobs. Decision logic lives in `scripts/agent_os_aggregate_gate.py`.

Publishing the status does not enforce it. Adding it to the live `Protect main`
ruleset is a protected-setting change that needs its own authorization (#2234).
