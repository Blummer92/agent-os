# Sprint Evidence Ingestion Contract

## Status

- Contract version: `0.1.0`
- Reporting schema: `0.1.0`
- Read owner: GitHub Service Agent
- Interpretation owner: Integration Manager
- Source of truth: GitHub
- Execution authorization: false

This contract defines bounded, read-only evidence collection for explicitly supplied
Sprint candidates.

## Inputs

Required inputs are repository, base branch, candidate issue numbers, collection
timestamp, sprint ID, and supported reporting schema version. Candidate issues must be
explicitly supplied; repository-wide discovery or queueing is out of scope.

## Allowed Reads

For each candidate, collection may read:

- issue state, labels, timestamps, dependencies, and blockers;
- linked pull requests, exact head SHAs, state, and timestamps;
- changed-file names when available;
- current check or validation summaries when available;
- source object identifiers and retrieval timestamps.

No content remains current after its source object changes.

## Source Record

Every normalized source requires:

- `object_type`: issue, pull-request, check, or file-list;
- `object_id`, repository, and `retrieved_at`;
- source `updated_at` or unavailable;
- result, permission, and pagination status;
- evidence digest when canonical bytes are available.

## Freshness Rules

- `current`: required evidence was collected consistently;
- `stale`: a source changed after collection began;
- `incomplete`: evidence was missing, unavailable, or not fully paginated;
- `conflicting`: sources disagree about identity, SHA, dependency, or state.

Stale, incomplete, conflicting, or permission-denied evidence adds a bounded
manual-review reason and routes the Sprint to review.

## Normalized Output

The adapter populates these canonical #379 fields:

- `schema_version: 0.1.0`;
- stable `sprint_id`;
- `evidence_mode: connected-read-only`;
- `execution_authorized: false`;
- `evaluated_at`, repository, and supplied candidate issue IDs;
- normalized `sources` and lane evidence;
- `freshness` and sorted `manual_review_reasons`.

It must not add competing reporting fields or alter schema ownership.

## Identity And Consistency

- Bind pull-request evidence to exact repository, PR number, and head SHA.
- Preserve issue and PR timestamps and detect head movement during collection.
- Reject repository mismatch and ambiguous linked PR identity.
- Treat missing changed-file or check evidence as unknown, not empty or passing.
- Reruns against unchanged GitHub state normalize identically except for retrieval
  timestamps.

## Failure Handling

Bounded reason codes distinguish missing permission, incomplete pagination, source
change, repository mismatch, PR ambiguity, SHA mismatch, malformed response,
unsupported schema version, and unavailable evidence.

No automatic retry loop, scheduled polling, persistent worker, or Cloud Build run is
allowed.

## Write Boundary

The adapter may not create or update issues, labels, comments, branches, pull requests,
approvals, checks, Scheduler tasks, or production settings. Compatibility evidence
cannot authorize execution.

## Test Matrix And Handoff

Fixtures cover complete evidence, source mutation, missing permissions, incomplete
pagination, conflicting dependencies, no linked PR, closed candidates, changed PR head,
unavailable checks, deterministic normalization, and unsupported schema versions. One
bounded connected read-only smoke test is permitted after offline fixtures pass.

#375 renders the normalized contract. #379 owns schema vocabulary and validation. #376
stops when schema version, source identity, pagination completeness, or permission status
cannot be proven.
