# Sprint Reporting Schema

## Status And Authority

- Schema version: `0.1.0`
- Owner: Integration Manager
- Source of truth: GitHub
- Execution authorization: false
- Validation companion: this document; no inferred fields

This contract governs the Sprint Dashboard and Sprint Governance Report. Reporting evidence never authorizes execution.

## Top-Level Record

| Field | Type | Rule |
|---|---|---|
| `schema_version` | string | required; exactly `0.1.0` |
| `sprint_id` | string | required; stable within reruns |
| `sprint_goal` | string | required; non-empty |
| `sprint_state` | enum | planned, active, review, blocked, complete |
| `evidence_mode` | enum | supplied-evidence, connected-read-only |
| `execution_authorized` | boolean | required; always false |
| `evaluated_at` | RFC3339 UTC | required |
| `freshness` | enum | current, stale, incomplete, conflicting |
| `manual_review_reasons` | string[] | required; sorted, may be empty |
| `sources` | source[] | required; may be empty only in supplied mode |
| `lanes` | lane[1..3] | unique issue numbers |
| `risks` | risk[] | unique stable risk IDs |
| `risk_delta` | object | computed by the rules below |
| `decisions` | decision[] | deterministic order |
| `recommendations` | recommendation[] | bounded action vocabulary |
| `validation` | validation | unknown values preserved |
| `final_handoff` | handoff | required review report fields |

## Record Contracts

`lane` requires issue, title, mode, compatibility, reason codes, pull request or unknown, changed files, tests, docs, blockers, and referenced risk IDs. Modes are implementation, planning-only, review, and blocked. Compatibility is compatible, sequential-only, unknown, or rejected.

`source` requires object type, object ID, repository, retrieved time, source updated time or unavailable, result status, permission status, pagination status, and optional evidence digest.

`risk` requires risk ID, summary, category, severity, status, owner, affected issue/roadmap/ADR references, evidence references, recommended action, due phase, and optional previous severity/status. Categories are architecture, implementation, dependency, validation, compute, documentation, governance, security, and technical-debt. Severities are critical, high, medium, and low. Statuses are new, active, mitigated, blocked, and closed.

`decision` requires decision ID, summary, rationale, and affected references.

`recommendation` requires recommendation ID, action, targets, rationale, and related risk IDs. Actions are update-existing-issue, update-roadmap, create-adr, create-new-issue, close-or-merge-duplicate, needs-decision, and no-action.

`validation` requires tests run, docs updated, repository-validation status, status-check state, Cloud Build runs or unknown, builds avoided or unknown, and evidence references.

`handoff` requires files changed, tests run, docs updated, unresolved blockers, handoff recommendations, and remaining risks.

## Validation And Decision Rules

- Every lane risk ID must resolve to exactly one top-level risk.
- Every risk must have an owner and at least one affected reference.
- Use owner `needs-decision` only with action `needs-decision`; count it as unowned until resolved.
- `create-new-issue` requires a distinct owner, implementation boundary, validation requirement, or release decision.
- Missing validation is pending or unknown, never passing.
- Confidence percentages are forbidden until a separate evidence-based scoring contract exists.
- Stale, incomplete, or conflicting evidence forces sprint state `review` unless all lanes are blocked.
- Non-empty manual-review reasons force a visible manual-review section.

## Risk Delta

For each stable risk ID:

- `new`: no previous status and current status is new, active, or blocked;
- `mitigated`: current status is mitigated and previous status was neither mitigated nor closed;
- `closed`: current status is closed and previous status was not closed;
- severity increased/decreased: compare current and previous severity ranks;
- `unowned`: owner is `needs-decision`.

Missing prior evidence does not imply a severity or lifecycle change.

## Canonicalization And Compatibility

Serialize UTF-8 JSON with sorted keys and compact separators. Sort lanes by issue, risks by risk ID, sources by repository/object type/object ID, decisions and recommendations by ID, manual-review reasons and other string collections lexically. Reject duplicate identities, unresolved risk references, unknown required fields, and unsupported versions. Optional fields require an explicit schema revision.

## Output And Migration Handoff

The Dashboard shows sprint status, lanes, top risks, Risk Delta, issue impact, GitHub changes, validation, manual-review reasons, blockers, merge order, and next sprint. The Governance Report adds all sources, decisions, dependencies, and final handoff.

#375 must implement this record shape and mark supplied evidence honestly. #376 populates source, freshness, manual-review, and connected-read-only fields without changing schema ownership. Both preserve `execution_authorized=false`.
