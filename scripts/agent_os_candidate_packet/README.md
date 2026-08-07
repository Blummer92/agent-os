# agent_os_candidate_packet

AOS-AUTO1A (#750): the read-only candidate-packet stages. Resolve one exact GitHub issue
snapshot, bind it to a source revision and body digest, and produce canonical IssuePlan
current-state evidence, a readiness result, and a WSC3 draft proposal -- read-only, with
no network calls in this package.

## Public interface

```python
readiness = prepare_issue_readiness(
    request, issue_reader, repository_reader,
    dependency_identity_evidence=..., planning_context=...)
planning = prepare_planning_handoff(
    readiness, evaluator_sha=..., created_at=...)
result = prepare_repository_and_proposal(
    planning, repository_observation, created_at=...)
```

`issue_reader` and `repository_reader` are injected, read-only dependencies
(`IssueSourceReader` / `RepositoryEvidenceReader` in `stage_models.py`). Neither declares
a write method.

## Two-phase planning binding (#917)

`IssuePlanningContext` is the single authoritative pre-planning source for repository,
base branch, evaluated repository SHA, implementation-contract fingerprint, and
authorized scope. Readiness projects it into the IssuePlan evidence *before* that
evidence's identity is computed, so the identity covers it and is never revised. Nothing
probes Git, a worktree, a provider, or a clock to obtain it.

The IssuePlan leaves `graph_reference`, `planning_result_reference`, and
`handoff_reference` unset: those digests transitively embed its own evidence ID, so
carrying them would need a hash preimage (the #916 cycle). `PlanningBindingEvidence`
(`..agent_os_issue_acceptance.planning_binding`) carries them instead -- built after the
handoff exists, preserved by identity, forwarded as that exact object to WSC3 and
approval records. Supplying it selects the two-phase route; omitting it leaves the
original IssuePlan-reference route unchanged for legacy callers.

Binding identity is recomputed before it is believed, so a tampered binding, one from
another planning run, stale repository evidence, and a contract-fingerprint mismatch each
fail closed. The binding is verification input only: no persisted field is added to
`DraftTaskProposal` or `ApprovalBinding`.

## Reuse, not reimplementation

This package composes, and never replaces, `agent_os_github_issue_provider.revision`
(source-revision binding) plus these `agent_os_issue_acceptance` entry points:
`issueplan_scanner.scan_issueplan_source`, `issueplan_current_state`
`.build_issueplan_current_state_evidence`, `readiness`
`.evaluate_issue_readiness_with_labels`, and `acceptance_report_transport`
`.acceptance_report_to_payload` / `_from_payload`.

## Outcomes

`resolve_issue_snapshot` fails closed with `source.issue-number-mismatch` if the returned
item's `number` differs from the requested one, and `source.malformed-issue-number` for a
non-integer. `status` is one of `ready`, `blocked`, `needs-decision`, `source-failure`,
`incomplete-evidence`, kept distinct so a source failure never masquerades as a readiness
outcome. Every resolved status requires `snapshot`, `issueplan_current_state_evidence`,
and `readiness_result`; unresolved statuses carry none. Authority flags are fixed `False`.

## Dependency identity evidence

`DependencyIdentityEvidence` (#776) records *which* dependencies an issue has: `resolved`
(structured identities supplied), `unresolved` (declared, not resolved), `absent` (none
reported), `unavailable` (no source). Only `resolved` carries `dependency_ids`,
deduplicated and sorted. `prepare_issue_readiness(..., dependency_identity_evidence=...)`
is the only entry point; nothing derives an identity from prose or a repository-wide
guess. `STAGE_SCHEMA_VERSION` is `1.1`; schema `1.0` is rejected outright.

## Round trip

`issue_readiness_stage_result_to_dict` / `_from_dict`, and
`serialize_planning_binding_evidence` / `reconstruct_...`, reconstruct every field with no
semantic drift; malformed payloads fail closed. Registry admission is deferred.

## Executable lane selection (AOS-QUEUE2, #864)

`executable_lane_selection.py` implements `agent-os-executable-lane-selection` `1.0`: a
pure, deterministic selector over supplied canonical `IssueOperationalState` (#862) and
`AgentOperatingModeDecision` (#863) records, via
`select_executable_lanes(campaign_id=..., requested_lane_count=1..3,
substitution_allowed=..., explicit_request_order=..., candidates=(...))`. It performs no
execution or mutation, and gives each issue exactly one descriptive queue:
`ready-for-implementation`, `ready-for-review`, `waiting-for-authorization`,
`waiting-for-dependency`, `merged-needs-closure`, `needs-reconciliation`, `planning-only`,
`terminal`, `invalid`. Precedence: explicit requests in caller order, then other
independently executable issues, then permitted ready-for-review, then reconciliation
work, then planning-only; waiting/terminal issues stay visible but never consume a lane.
Ties break on explicit request position, then depth, then issue number. Multiple active
primary claims classify `needs-reconciliation` and are always excluded.

Replacement applies only to an explicitly requested issue in a blocked queue, with one
finite `replacement.blocked-*` reason per outcome: `-preferred-substituted` (an eligible
substitute fills the slot and records a `ReplacementRecord`),
`-exact-required-not-substituted` (`substitutable=False`), `-substitution-disabled`
(`substitution_allowed=False`), `-no-eligible-replacement` (slot stays empty). Results
embed only source `state_id`/`decision_id` identities; authority flags stay `False`.
