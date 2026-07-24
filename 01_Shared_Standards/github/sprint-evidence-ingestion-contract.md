# Sprint Evidence Ingestion Contract

## Status

- Contract version: `0.1.0`; reporting schema: `0.1.0`
- Read owner: GitHub Service Agent; interpretation: Integration Manager; QA: QA / Test Agent
- Source of truth: GitHub; execution authorization: false

This contract defines bounded, read-only evidence collection for explicitly supplied Sprint candidates. It authorizes no discovery, scheduling, execution, mutation, or publication.

## Inputs And Limits

Require exact repository identity, base branch, supplied issue numbers, collection timestamp and correlation ID, sprint ID, supported schema version, and fixed candidate, page-count, and page-size limits. Repository-wide discovery, polling, inferred candidates, and queue consumption are out of scope.

## Allowed Reads

For each supplied candidate, read only bounded schema evidence: issue identity/state/labels/timestamps/dependencies/blockers; linked PR identity/state/timestamps/base/exact head SHA; changed-file names and current checks when available; source revisions and retrieval timestamps. Evidence is stale after its bound source revision changes.

## Repository Identity

Every request and pagination transition stays bound to one canonical repository. Owner/name text alone is insufficient for numeric `/repositories/{id}/...` paths. A numeric ID is trusted only when verified during the same invocation from bounded installation-repository evidence obtained with the same installation token. Cached, persisted, caller-entered, or previously retrieved mappings are untrusted. Mismatch, lookup failure, fork/upstream ambiguity, rename/transfer uncertainty, or unverified numeric identity stops collection.

## Source Record

Record object type and ID, canonical repository, retrieval and source-update timestamps, revision or exact-head evidence, result, permission, pagination and terminal-proof state, evidence digest when canonical bytes exist, and bounded reason codes. Unknown evidence remains unknown; it never normalizes to empty, current, passing, or complete.

## Pagination And Retry

- Freeze candidate, page, and page-size bounds before collection.
- Next links preserve API authority, endpoint, repository identity, state, page size, and increasing page number.
- Require positive terminal proof; missing proof is incomplete.
- Duplicate, regressing, ambiguous, malformed, cross-host, cross-repository, encoded, or unsupported links fail closed.
- Hitting a bound before terminal proof is incomplete.
- A 403 or 429 stops collection and routes to review.
- Permit at most one retry only when an explicit safe transient signal is present; never loop automatically.

## Freshness

Use `current` only when required evidence is consistent and terminal pagination is proven. Use `stale` for source or PR-head movement, `incomplete` for missing evidence/permission/terminal proof, `conflicting` for identity/SHA/dependency/state disagreement, and `unavailable` when bounded reads fail. Every non-current result adds manual-review evidence and cannot authorize execution.

## Normalized Output

Populate only #379 fields: schema `0.1.0`, stable sprint/correlation IDs, `evidence_mode: connected-read-only`, `execution_authorized: false`, `side_effects_performed: false`, evaluation time, repository, supplied candidate IDs, normalized sources/lane evidence, freshness/completeness, and sorted manual-review reasons. Do not create competing report, approval, readiness, projection, identity, pagination, or reason-code models.

## Consistency And Failure

Bind PR evidence to repository, PR number, base, and exact head SHA. Detect source movement. Missing file/check evidence is unknown, not empty or passing. Unchanged reruns normalize identically except approved observation fields. Bounded reasons distinguish permission denial, quota exhaustion, incomplete pagination, source mutation, repository/numeric-ID mismatch, PR ambiguity, SHA mismatch, malformed response, unsupported version, unavailable evidence, and exceeded bounds. Never emit secrets, tokens, full responses, or unbounded errors.

## Write Boundary

Do not create or update issues, labels, comments, branches, PRs, approvals, checks, Scheduler tasks, queues, leases, workspaces, workers, validation runs, production settings, readiness, ownership, governance, sharing, branch protection, or source-of-truth records.

## Tests And Handoff

Offline fixtures cover complete evidence, incomplete pagination, absent terminal proof, denied permission, first/later-page quota exhaustion, safe/unsafe retry signals, source mutation, repository mismatch, unverified numeric identity, fork ambiguity, ambiguous/no linked PR, changed head, malformed/unavailable evidence, unsupported version, closed candidate, exceeded bounds, and deterministic reruns. One bounded connected read-only smoke test is allowed only after offline fixtures pass; it uses supplied candidates, records exact identity/revision evidence, performs no writes, and stops on any gap.

#375 renders supplied evidence; #379 owns schema vocabulary; #376 owns runtime and connected-evidence risk. Reuse the canonical GitHub pagination provider and identity hardening by reference.
