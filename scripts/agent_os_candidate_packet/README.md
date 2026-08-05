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
  `.acceptance_report_to_payload` / `.acceptance_report_from_payload`.

## Exact issue identity

`resolve_issue_snapshot` fails closed with `source.issue-number-mismatch` if
the returned item's `number` differs from the requested `issue_number`, and
with `source.malformed-issue-number` for a non-integer returned number.

## Outcomes

`IssueReadinessStageResult.status` is one of: `ready`, `blocked`,
`needs-decision`, `source-failure`, `incomplete-evidence`, kept distinct so a
source failure never masquerades as a readiness outcome. Every resolved
status requires all of `snapshot`, `issueplan_current_state_evidence`, and
`readiness_result`; unresolved statuses carry none. `execution_authorized`
and `side_effects_performed` are fixed `False` on every result.

## Dependency identity evidence

`DependencyIdentityEvidence` (#776) is this boundary's canonical record of
*which* dependencies an issue has. `DependencyIdentityStatus`: `resolved`
(structured source supplied canonical identities), `unresolved` (declared,
not resolved), `absent` (structured source reported none), `unavailable` (no
source). Only `resolved` carries `dependency_ids`, deduplicated and sorted;
a collapsed duplicate records `dependency-identity.duplicate-collapsed`.
`prepare_issue_readiness(..., dependency_identity_evidence=...)` is the only
entry point; nothing here derives an identity from prose or a repository-wide
guess. `STAGE_SCHEMA_VERSION` is `1.1`; schema `1.0` is rejected outright.

## Round trip

`issue_readiness_stage_result_to_dict` / `_from_dict` in `stage_models.py`
serialize and reconstruct every field with no semantic drift. Malformed
payloads fail closed rather than reconstructing partially.

Registry admission (module-version-map, ownership-matrix) is explicitly
deferred to the final integration issue and is out of scope here.

## Executable lane selection (AOS-QUEUE2, #864)

`executable_lane_selection.py` implements `agent-os-executable-lane-selection`
`1.0`: a pure, deterministic selector over supplied canonical
`IssueOperationalState` (#862) and `AgentOperatingModeDecision` (#863)
records, reached via `select_executable_lanes(campaign_id=..., requested_lane_count=1..3,
substitution_allowed=..., explicit_request_order=..., candidates=(CandidateIssueEvidence(...), ...))`.
It performs no execution or mutation.

Every issue receives exactly one descriptive queue: `ready-for-implementation`,
`ready-for-review`, `waiting-for-authorization`, `waiting-for-dependency`,
`merged-needs-closure`, `needs-reconciliation`, `planning-only`, `terminal`,
`invalid`. Precedence: explicit requests in caller order, then other
independently executable issues, then permitted ready-for-review, then
reconciliation work, then planning-only; waiting/terminal issues stay visible
but never consume a lane. Ties break on explicit request position, then
ascending dependency depth, then ascending issue number.

Replacement applies only to explicitly requested issues in a blocked queue:
with `substitution_allowed=True` and the candidate's own `substitutable=True`,
the next eligible `ready-for-implementation` issue fills the slot and records
a `ReplacementRecord`; `substitutable=False` is never silently replaced.
Multiple active primary claims classify `needs-reconciliation` and are always
excluded from selection. The result embeds only the source
`state_id`/`decision_id` identities. `execution_authorized` and
`side_effects_performed` are always `False`.
