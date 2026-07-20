# Google Cloud Transition Handoff
Use with `03_Templates/prompts/github-change-request.md` for proposed Agent OS
cloud runtime, cache, build, storage, messaging, observability, or deployment work.
It does not authorize implementation, external changes, or production activation.

## Request
- Title, issue, requesting agent, and responsible owner:
- Repository, base branch, and exact files:
- Intended outcome and non-goals:
- Cloud project reference, region, and services:
- Private runtime values supplied outside GitHub:

## Systems And Authority
Reference issue #173 and current governance; do not duplicate their policy text.

| Data or decision | Authoritative system | Derived or cache surface | Live check |
|---|---|---|---|
| Agent OS governance, contracts, tests, templates | GitHub | | Required |
| Planning, review, approval, working knowledge | Notion or approved named source | | Required |
| Artifact identity, content, and permissions | Google Drive | | Required |
| Runtime, logs, metrics, and cached lookup evidence | Named cloud service | | Required before authority-dependent action |

- Conflict and drift handling:
- Record classification: runtime, non-authoritative cache, audit evidence, approved
  configuration, or prohibited authoritative duplicate:
- Explain why cloud evidence cannot decide readiness, approval, ownership, sharing,
  schema, duplicate merging, production activation, or provider write-back.

## Read, Write, And Data Boundary
- Allowed reads and verification method:
- Proposed writes and receiving systems:
- Duplicate-prevention method:
- Protected governed fields, records, and permissions:
- Retained data, retention period, and cleanup owner:
- Report-only operations and expected cost boundary:
Any production or external-system write requires separate explicit approval.

## Access Plan
Record reference names and approved storage locations only. Never place private
values, tokens, keys, or certificates in this document.
- Authentication method and access owner:
- Approved private-value storage location:
- Minimum permissions required:
- Rotation, revocation, and missing-access behavior:
- Permission-completeness check:
Fail closed when identity, access, permissions, or scope are unclear or broader
than approved.

## Approval Gates
Name the decision maker and evidence for each applicable gate:
- repository implementation;
- cloud resource or access changes;
- schema or governed-field changes;
- external write-back or production deployment;
- rollout or concurrency expansion.
Readiness, cache state, dry runs, and passing validation are evidence only.

## Validation And Audit
- Focused tests and sanitized fixtures:
- Structure and aggregate validation:
- Cloud configuration validation or dry run:
- Exact branch-head and synthetic-merge SHAs:
- Build or execution ID, tested SHA, failed step, result, and exit code:
- Logs, metrics, redaction, retention, and evidence owner:
- Incomplete, stale, malformed, ambiguous, permission-denied, or paginated evidence
  handling:
Unknown evidence remains unknown and routes to manual review.

## Rollout And Rollback
- Initial environment, maximum scope, and dry-run behavior:
- Pilot criteria and manual review points:
- Immediate disablement:
- Repository and cloud rollback:
- Cache or data cleanup and access revocation:
- External-system correction and rollback evidence:
Do not infer production approval from a lower-environment result. Preserve
canonical records unless destructive cleanup is separately approved.

## Stop Conditions
Return `needs-decision` when target, authority, owner, access, permissions,
file or resource allowlist, governed fields, cost, validation, rollback, audit,
production activation, external write-back, or cache/live-state conflict is unclear.
Stop if the request creates a competing source of truth or duplicate framework.

## Final Report
Report branch and PR; cloud resources changed or `none`; files changed; tests and
validation; docs; external writes or `none`; approvals; exact tested SHA and
runtime or build IDs; blockers; rollback status; handoffs; and remaining risks.
