# agent_os_candidate_packet

AOS-AUTO1A (#750): the first read-only candidate-packet stage. Resolves one
exact GitHub issue snapshot, binds it to a source revision and body digest,
and produces canonical IssuePlan current-state evidence plus a readiness
result -- all read-only, with no network calls in this package itself.

## Public interface

```python
from scripts.agent_os_candidate_packet import (
    IssueReadinessStageRequest,
    prepare_issue_readiness,
)

result = prepare_issue_readiness(
    request, issue_reader, repository_reader, dependency_identity_evidence=None
)
```

`issue_reader` and `repository_reader` are injected, read-only dependencies
(see `IssueSourceReader` and `RepositoryEvidenceReader` protocols in
`stage_models.py`). Neither protocol declares a write method.

## Reuse, not reimplementation

This package composes, and never replaces:

- `scripts.agent_os_github_issue_provider.revision` for source-revision binding.
- `scripts.agent_os_issue_acceptance.issueplan_scanner.scan_issueplan_source`.
- `scripts.agent_os_issue_acceptance.issueplan_current_state`
  `.build_issueplan_current_state_evidence`.
- `scripts.agent_os_issue_acceptance.readiness`
  `.evaluate_issue_readiness_with_labels`.
- `scripts.agent_os_issue_acceptance.acceptance_report_transport`
  `.acceptance_report_to_payload` / `.acceptance_report_from_payload` --
  the canonical owner of AcceptanceReport payload shape. This package holds
  no second AcceptanceReport serializer.

## Exact issue identity

`resolve_issue_snapshot` verifies that the returned item's `number` equals the
requested `issue_number` before binding a source revision. A mismatch fails
closed with `source.issue-number-mismatch` and returns no snapshot, so a
revision can never be bound to an identity the snapshot does not describe. A
non-integer returned number fails closed with
`source.malformed-issue-number`; a boolean requested `issue_number` is
rejected outright rather than coerced.

## Outcomes

`IssueReadinessStageResult.status` is one of: `ready`, `blocked`,
`needs-decision`, `source-failure`, `incomplete-evidence`. These are kept
distinct -- a source failure never masquerades as a blocked or
needs-decision readiness outcome, and vice versa.

Every resolved status (`ready`, `blocked`, `needs-decision`) requires all of
`snapshot`, `issueplan_current_state_evidence`, and `readiness_result`.
Unresolved statuses must carry none of them.

`execution_authorized` and `side_effects_performed` are fixed `False` on
every result. This stage never authorizes execution and performs no writes.

## Dependency identity evidence

`DependencyIdentityEvidence` (#776) is this boundary's canonical record of
*which* dependencies an issue has. Status-only `DependencyEvidence` is
unchanged. `DependencyIdentityStatus`:

- `resolved` -- a structured source supplied canonical identities;
- `unresolved` -- dependencies declared, identities not resolved;
- `absent` -- a structured source reported none; `unavailable` -- no source.

Only `resolved` may carry `dependency_ids`, so a partial set never reads as
complete. Identities are stripped, deduplicated, and sorted deterministically;
a collapsed duplicate records `dependency-identity.duplicate-collapsed` to keep
provenance truthful. Empty, whitespace-only, control-character, non-string, and
Boolean identities are rejected; `provenance` keeps its order and multiplicity.

`prepare_issue_readiness(..., dependency_identity_evidence=...)` is the only way
identities enter a stage result; the caller must already hold them structured.
Nothing here derives an identity from issue prose, `Depends on:` text, comments,
PR text, labels, reason codes, evidence details, or a repository-wide guess. A
caller supplying nothing gets `unavailable` (`dependency-identity.not-supplied`);
resolved statuses always carry evidence, unresolved statuses never do.

`STAGE_SCHEMA_VERSION` is `1.1`; schema `1.0` payloads are rejected, not
reinterpreted, since a legacy payload cannot prove whether identities were
absent or never captured. Both payloads are closed schemas and fail closed.

## Round trip

`issue_readiness_stage_result_to_dict` / `_from_dict` in `stage_models.py`
serialize and reconstruct every field with no semantic drift, including the
nested `IssuePlanCurrentStateEvidence` and `AcceptanceReport`. Malformed
payloads fail closed rather than reconstructing partially.

Registry admission (module-version-map, ownership-matrix) is explicitly
deferred to the final integration issue and is out of scope here.
