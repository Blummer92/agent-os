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

result = prepare_issue_readiness(request, issue_reader, repository_reader)
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

## Outcomes

`IssueReadinessStageResult.status` is one of: `ready`, `blocked`,
`needs-decision`, `source-failure`, `incomplete-evidence`. These are kept
distinct -- a source failure never masquerades as a blocked or
needs-decision readiness outcome, and vice versa.

`execution_authorized` and `side_effects_performed` are fixed `False` on
every result. This stage never authorizes execution and performs no writes.

## Round trip

`issue_readiness_stage_result_to_dict` / `_from_dict` in `stage_models.py`
serialize and reconstruct every field with no semantic drift, including the
nested `IssuePlanCurrentStateEvidence` and `AcceptanceReport`.

Registry admission (module-version-map, ownership-matrix) is explicitly
deferred to the final integration issue and is out of scope here.
