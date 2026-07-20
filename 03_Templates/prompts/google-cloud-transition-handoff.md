# Google Cloud Transition Handoff

Use this template for proposed Agent OS work involving Google Cloud runtime,
cache, build, storage, messaging, observability, or deployment surfaces.

This template extends `03_Templates/prompts/github-change-request.md`. It does not
authorize cloud provisioning, production activation, credentials, external writes,
or repository implementation by itself.

## Request Summary

- Request title:
- Requesting agent and overlay:
- Responsible owner:
- Target repository and base branch:
- Related issue or approved change request:
- Intended outcome:

## Systems Involved

List every affected system and its role.

| System | Role | Read operations | Proposed write operations |
|---|---|---|---|
| GitHub | | | |
| Notion | | | |
| Google Drive | | | |
| Google Cloud service | | | |

## Source Of Truth And Authority

Reference the boundary decision in issue #173 and the current governance files.
Do not redefine their policy text here.

| Data or decision | Authoritative system | Derived/cache location | Live verification required |
|---|---|---|---|
| Agent OS governance and contracts | GitHub | | Yes before governed changes |
| Planning, review, approvals, and handoffs | Notion or named approved source | | Yes before writes |
| Student-facing artifact identity and permissions | Google Drive | | Yes before writes |
| Runtime or cache evidence | Named Google Cloud service | | Yes before authority-dependent action |

Explain how conflicts between cached cloud data and an authoritative system will
stop the workflow and route to manual review.

## Google Cloud Target

- Project identifier or runtime-supplied reference:
- Region:
- Services involved:
- Runtime purpose:
- Data retained:
- Retention period:
- Network or connector dependencies:
- Expected cost boundary:

Do not include private project identifiers when they are not approved for
repository storage.

## Runtime And Cache Classification

Classify every proposed cloud record as one of:

- ephemeral runtime state;
- derived non-authoritative cache;
- audit or observability evidence;
- approved configuration;
- prohibited authoritative duplicate.

State why the record cannot independently authorize readiness, approval,
ownership, sharing, schema changes, duplicate merging, production activation, or
write-back to another system.

## Read And Write Boundary

- Allowed reads:
- Proposed writes:
- External systems receiving writes:
- Idempotency or duplicate-prevention method:
- Live-state checks immediately before writing:
- Governed fields or records explicitly protected:
- Operations that remain report-only:

Any production or external-system write requires separate explicit approval.

## Credentials And Secrets Plan

Record names and approved storage locations only. Never paste secret values,
tokens, keys, cookies, private certificates, or service-account credentials.

- Authentication method:
- Secret names:
- Approved secret store:
- Least-privilege roles required:
- Credential owner:
- Rotation and revocation owner:
- Local-development fallback:
- Missing-credential behavior:

The workflow must fail closed when credentials or permissions are missing,
ambiguous, expired, or broader than approved.

## Private Runtime Values

List values supplied outside GitHub, such as project IDs, folder IDs, account
identifiers, callback URLs, or deployment names. State how each value is
validated without committing it to the repository.

## Repository Change Scope

- Files to add:
- Files to edit:
- Files to remove:
- Forbidden paths:
- Reused standards, templates, or tooling:
- Duplicate implementation checked:

Only the GitHub Service Agent may perform approved repository writes.

## Approval Gates

Name the required decision maker and evidence for each applicable gate.

- Repository implementation:
- Google Cloud resource creation:
- IAM or service-account changes:
- Secret creation or access:
- Production deployment:
- External-system write-back:
- Schema or governed-field changes:
- Rollout expansion:

Issue readiness, passing validation, cached evidence, and successful dry runs are
evidence only. They are not approval or execution authorization.

## Validation Plan

- Focused tests:
- Offline or synthetic fixtures:
- Repository structure validation:
- Aggregate validation:
- Cloud configuration validation or dry run:
- Exact branch-head SHA evidence:
- Synthetic-merge SHA evidence:
- Runtime smoke test, if separately authorized:
- Evidence location and retention:

Validation must use synthetic or sanitized fixtures and must not expose secrets or
private identifiers.

## Rollout Plan

- Initial environment:
- Maximum scope or concurrency:
- Dry-run behavior:
- Pilot success criteria:
- Manual review points:
- Expansion decision:
- Production activation owner:

Do not skip staged rollout levels or infer production approval from a successful
lower environment.

## Disablement And Rollback

- Immediate disablement method:
- Repository rollback:
- Cloud resource rollback:
- Data/cache cleanup:
- Credential revocation:
- External-system correction:
- Owner responsible for verification:
- Evidence proving rollback completion:

Rollback must preserve authoritative records and avoid destructive cleanup unless
that cleanup is separately approved.

## Observability And Audit

- Required logs and metrics:
- Exact repository, branch, source SHA, and tested SHA fields:
- Cloud build or execution identifier:
- Failed-step and exit-code evidence:
- Permission or pagination completeness evidence:
- Redaction requirements:
- Audit retention and owner:

Unknown, incomplete, stale, malformed, or permission-denied evidence must remain
unknown and route to manual review.

## Stop Conditions

Stop and return `needs-decision` when any of the following is unclear or required
outside the approved scope:

- target project, service, repository, branch, or resource;
- system of record or authority boundary;
- owner or approval path;
- credentials, secret storage, or least-privilege role;
- governed fields, permissions, sharing, or schema changes;
- production activation or external write-back;
- exact file or resource allowlist;
- validation, rollback, cost, or audit evidence;
- a competing source of truth or duplicate framework;
- a conflict between cloud cache and live authoritative state.

## Required Final Report

Report:

- branch and pull request;
- cloud resources changed, or `none`;
- files changed;
- tests and validation run;
- documentation updated;
- external writes performed, or `none`;
- approvals used;
- exact tested SHA and runtime/build identifiers;
- unresolved blockers;
- rollback status;
- handoff recommendations;
- remaining risks.
