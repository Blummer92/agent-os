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

0.1.0
