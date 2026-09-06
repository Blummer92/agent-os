# First-run authorized-validation invalidation projection (#1970)

## Purpose

The trusted-host first-run validation-only lifecycle does not transport or invent a historical invalidation-event log. `project_first_run_residual_invalidation(...)` is a pure composition proof over already-canonical candidate, approval, execution-packet, and `ValidationEvidenceBundle` objects.

A successful proof returns exactly:

```python
()
```

That empty tuple means the existing canonical owners positively proved the applicable first-run invalidation categories. It never means merely that no event was observed.

## Ownership partition

- `ApprovalRecord` owns approval lifecycle/decision history, including expired, invalidated, and superseded state.
- IssuePlanCore/source/scanner/planning/projection owners retain source, scanner, contract, handoff, graph, identity, projection, and version currentness.
- Approved-projection consumption retains validation-staleness/current-subject comparison.
- Candidate/execution/runtime preflight retains runtime capability currentness.
- The #1970 projection owns no currentness or authorization semantics. It only verifies that the existing evidence is complete and mutually bound before returning the residual tuple.

## Validation-plan identity boundary

The candidate runtime intentionally binds a candidate-specific `PrePrValidationPlan` identity (`pre-pr-validation-plan:*`). `ValidationEvidenceBundle` intentionally binds the standard remote `ValidationPlan` identity (`validation-plan:*`). These are different domain-separated identities and must not be compared for equality.

The first-run projection preserves both owners and proves their intersection through exact repository/base/source/tested subject bindings and exact ordered command identities. It does not translate, alias, or replace either plan identity.

## In-memory composition

`build_first_run_authorized_validation_request(...)` accepts the exact `ValidationEvidenceBundle` Python object, derives the residual tuple through the pure projection, and supplies both directly to the existing schema-1.1 authorized-validation request builder. It exposes no caller-supplied `invalidation_events` parameter.

No serialization or persistence is required merely to bridge these functions in one trusted Python process. The downstream #1929 production caller remains responsible for its existing independent state/authorization reacquisition and `SingleIssuePilotInput` reconstruction before delegation to #1830/#762.

## Vocabulary

`canonical_invalidation_events(...)` reuses `APPROVAL_INVALIDATION_REASON_CODES` from the canonical IssuePlanCore approval owner. It accepts only sorted, unique, bounded values from that vocabulary and rejects structural fixture strings such as `proposal-revised` or `approval-record-superseded`.

## Non-goals

This seam performs no I/O, GitHub access, persistence, Scheduler dispatch, lease work, execution, activation, resume, replay, workflow mutation, IAM/WIF/credential work, VM/network changes, MCP work, merge, or issue closure. It creates no authority and no second currentness, approval, validation, routing, Scheduler, or persistence system.
