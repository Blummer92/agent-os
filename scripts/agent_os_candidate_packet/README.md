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
`scripts.agent_os_github_issue_provider.revision` (source-revision binding),
`scripts.agent_os_issue_acceptance.issueplan_scanner.scan_issueplan_source`,
`scripts.agent_os_issue_acceptance.issueplan_current_state`
`.build_issueplan_current_state_evidence`,
`scripts.agent_os_issue_acceptance.readiness.evaluate_issue_readiness_with_labels`,
and `scripts.agent_os_issue_acceptance.acceptance_report_transport`
`.acceptance_report_to_payload` / `.acceptance_report_from_payload`.

## Outcomes

`resolve_issue_snapshot` fails closed with `source.issue-number-mismatch` if
the returned item's `number` differs from the requested `issue_number`, and
with `source.malformed-issue-number` for a non-integer returned number.
`IssueReadinessStageResult.status` is one of: `ready`, `blocked`,
`needs-decision`, `source-failure`, `incomplete-evidence`, kept distinct so a
source failure never masquerades as a readiness outcome. Every resolved
status requires `snapshot`, `issueplan_current_state_evidence`, and
`readiness_result`; unresolved statuses carry none. `execution_authorized`
and `side_effects_performed` are fixed `False`.

## Dependency identity evidence

`DependencyIdentityEvidence` (#776) is this boundary's canonical record of
*which* dependencies an issue has: `resolved` (structured identities
supplied), `unresolved` (declared, not resolved), `absent` (none reported),
`unavailable` (no source). Only `resolved` carries `dependency_ids`,
deduplicated and sorted. `prepare_issue_readiness(...,
dependency_identity_evidence=...)` is the only entry point; nothing derives
an identity from prose or a repository-wide guess. `STAGE_SCHEMA_VERSION` is
`1.1`; schema `1.0` is rejected outright.

## Round trip

`issue_readiness_stage_result_to_dict` / `_from_dict` in `stage_models.py`
serialize and reconstruct every field with no semantic drift; malformed
payloads fail closed. Registry admission is deferred to the final
integration issue.

## Executable lane selection (AOS-QUEUE2, #864)

`executable_lane_selection.py` implements `agent-os-executable-lane-selection`
`1.0`: a pure, deterministic selector over supplied canonical
`IssueOperationalState` (#862) and `AgentOperatingModeDecision` (#863)
records, via `select_executable_lanes(campaign_id=..., requested_lane_count=1..3,
substitution_allowed=..., explicit_request_order=..., candidates=(...))`.
Performs no execution or mutation.

Every issue receives exactly one descriptive queue: `ready-for-implementation`,
`ready-for-review`, `waiting-for-authorization`, `waiting-for-dependency`,
`merged-needs-closure`, `needs-reconciliation`, `planning-only`, `terminal`,
`invalid`. Precedence: explicit requests in caller order, then other
independently executable issues, then permitted ready-for-review, then
reconciliation work, then planning-only; waiting/terminal issues stay visible
but never consume a lane. Ties break on explicit request position, then
ascending dependency depth, then ascending issue number.

Replacement applies only to an explicitly requested issue in a blocked
queue, one finite `reason_codes` entry per outcome:

- eligible substitute found: fills the slot, records a `ReplacementRecord`
  (`replacement.blocked-preferred-substituted`);
- `substitutable=False`: never silently replaced
  (`replacement.blocked-exact-required-not-substituted`);
- `substitution_allowed=False`: blocked globally, no record
  (`replacement.blocked-substitution-disabled`);
- no eligible `ready-for-implementation` issue remains: slot stays empty
  (`replacement.blocked-no-eligible-replacement`).

Multiple active primary claims classify `needs-reconciliation`, always
excluded from selection. The result embeds only the source
`state_id`/`decision_id` identities; `execution_authorized` and
`side_effects_performed` are always `False`.

## Implementation Packet projection (#934)

`implementation_packet_projection.py` is a pure-local bridge from supplied
current canonical readiness/IssuePlan evidence, `IssueOperationalState`, and
`AgentOperatingModeDecision` into the **existing** Agent Memory & Context
Budget Manager handoff packet. `Implementation Packet` is only a usage/profile
name; this package does not define a second packet schema.

The projection calls the existing public Memory Manager
`build_handoff_packet(...)`, `assert_valid_handoff_packet(...)`, and
`handoff_packet_source_fingerprint(...)` contracts. Because Memory Manager is
an independent `src` package, callers that use this optional projection must
make `agent_memory_context_manager` importable (install the local package or
include `08_Tooling/agent-memory-context-manager/src` on `PYTHONPATH`). The
import is lazy so unrelated candidate-packet callers gain no new runtime
dependency.

`project_implementation_packet(...)` fails closed unless the supplied evidence
is READY, open, current, repository/issue/source-revision consistent, and the
operating-mode decision is bound to the exact operational-state identity. It
copies canonical IssuePlan `required_tests` exactly into
`validation_commands`, preserves forbidden paths as context guidance, and
permits `allowed_inspect_first` only as a subset of canonical `allowed_files`.
Context hints therefore cannot widen authorization.

The returned `ImplementationPacketProjection` contains the canonical Memory
Manager packet plus `ImplementationPacketSourceIdentities`: bounded provenance
(repository/issue/source revision, IssuePlan evidence, evaluated repository
SHA, operational-state ID, mode-decision ID, Memory Manager packet source
fingerprint, and a domain-separated source-identity fingerprint). Those
identities are evidence only; they do not create readiness, implementation,
execution, GitHub-write, Ready-for-Review, merge, or closure authority.

This projection performs no issue parsing, filesystem I/O, network access,
GitHub mutation, subprocess execution, Scheduler dispatch, provider invocation,
persistence, or external write.
