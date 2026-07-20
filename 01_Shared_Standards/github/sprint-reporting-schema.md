# Sprint Reporting Schema

## Status

- Schema version: `0.1.0`
- Owner: Integration Manager
- Source of truth: GitHub
- Execution authorization: false

This contract governs both the concise Sprint Dashboard and detailed Sprint Governance Report.

## Top-Level Record

Required fields:

- `schema_version`
- `sprint_id`
- `sprint_goal`
- `sprint_state`
- `evidence_mode`
- `evaluated_at`
- `freshness`
- `sources`
- `lanes`
- `risks`
- `risk_delta`
- `decisions`
- `recommendations`
- `validation`
- `final_handoff`

Allowed sprint states are `planned`, `active`, `review`, `blocked`, and `complete`.
Evidence modes are `supplied-evidence` and `connected-read-only`.
Freshness values are `current`, `stale`, `incomplete`, and `conflicting`.

## Lane Record

Each lane requires issue number, title, mode, compatibility, reason codes, pull request, changed files, tests, docs, blockers, and risk IDs.

Modes are `implementation`, `planning-only`, `review`, and `blocked`.
Compatibility values are `compatible`, `sequential-only`, `unknown`, and `rejected`.

## Risk Record

Every risk requires:

- stable `risk_id` and summary;
- category and severity;
- lifecycle status;
- owner;
- affected issue, roadmap, or ADR references;
- evidence references;
- recommended action;
- due phase;
- previous severity and status when available.

Categories include architecture, implementation, dependency, validation, compute, documentation, governance, security, and technical debt.
Severities are critical, high, medium, and low.
Statuses are new, active, mitigated, blocked, and closed.
Unowned or orphaned risks are invalid and route to `needs-decision`.

## Risk Delta

Required counters are new, mitigated, closed, severity increased, severity decreased, and unowned.
Delta calculations compare stable risk IDs only. Missing prior evidence remains unknown.

## Recommendation Record

Allowed actions are `update-existing-issue`, `update-roadmap`, `create-adr`, `create-new-issue`, `close-or-merge-duplicate`, `needs-decision`, and `no-action`.

`create-new-issue` requires a distinct owner, implementation boundary, validation requirement, or release decision.

## Unknown And Confidence Rules

Unknown evidence remains `unknown`. Missing validation is never passing. Confidence percentages are forbidden until a separate evidence-based scoring contract is approved.

## Canonicalization

- Serialize as UTF-8 JSON with sorted keys and compact separators.
- Sort lanes by issue number, risks by risk ID, sources by object identity, and recommendations by action then target.
- Reject duplicate lane issue numbers and duplicate risk IDs.
- Reject unknown required fields for `0.1.0`; optional fields must be explicitly versioned.
- Unsupported versions fail closed.

## Output Views

The Dashboard shows sprint status, lanes, top risks, Risk Delta, recommended GitHub changes, blockers, merge order, and next sprint.
The Governance Report adds full provenance, decision log, issue impact, dependency changes, validation details, and final handoff.

## Migration Handoff

- #375 must mark its current model provisional and migrate fields to this contract.
- #376 must populate sources, freshness, provenance, and connected evidence without changing schema ownership.
- Neither issue may treat reporting evidence as execution authorization.
