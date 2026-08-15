# Agent OS Execution Service — contract 0.5.0

This package separates pure-local planning and evidence contracts from the governed validation-execution composition surface.

## Authority boundary

Pure-local surfaces validate requests, inspect supplied repository snapshots, project results, serialize evidence, build validation command plans, and select executor routes. They do not run commands, mutate repositories, dispatch a runtime, or authorize work.

The Issue #697 execution-composition surface may delegate validation exactly once to the canonical Workflow Scheduler only after request, command-plan, authorization, and runtime-configuration checks pass. Route selection never satisfies those preconditions. Execution authorization, routing, command execution, validation success, Ready for Review, and merge authorization remain separate states.

## Authorized-validation admission — Issue #757

`authorized_validation.py` is the pure security checkpoint between a complete non-authorizing candidate packet plus separately supplied human execution authorization and later runtime-capable lifecycle stages.

The lifecycle request binds canonical roots rather than flattening their schemas: the exact `CandidatePacket`, approval/projection stage, execution-packet stage, `ExecutionAuthorizationEvidence`, and a versioned lifecycle-policy profile. Admission reuses each owning module's canonical transport/identity checks, then verifies repository, issue, invocation, SHA, approval/projection, validation-plan, command-plan, request, runtime, scope, tests, argv, timeout/output, and expected-changed-path bindings.

Because `ExecutionAuthorizationEvidence` does not carry candidate-packet, invocation, permitted-operation, or authorizer fields, #757 binds those values in the content-addressed lifecycle request without replacing the canonical authorization model. This prevents replay across candidate packets, invocations, or operations. The only permitted operation is `validation-only`; concurrency is exactly `1`; automatic retry is false.

Admission statuses are `accepted`, `blocked`, `stale`, `needs-decision`, and `invalid`. Unknown fields/versions, malformed or noncanonical evidence, identity drift, invalid authorization windows, and unsupported policy authority fail closed. `accepted` remains non-authorizing evidence (`execution_authorized=false`), not a reusable bearer capability. Downstream lifecycle owners must revalidate currentness immediately before any separately authorized side effect.

Construction, serialization, reconstruction, and admission verification perform no lease acquisition, worktree creation, process execution, Git mutation, network/provider/credential access, workflow dispatch, publication, retry, or external write.

## Public capabilities

- `inspect_repository`
- `verify_repository_state`
- canonical `ExecutionServiceRequest` serialization/reconstruction
- deterministic validation command planning
- deterministic executor routing and immutable handoff construction
- pure authorized-validation lifecycle request construction and admission verification

Accepted requests, plans, routes, handoffs, and #757 admissions are evidence only; they do not authorize edits, commands, pushes, review readiness, merge, deployment, or external mutation.

## Unified validation-lifecycle evidence — Issue #761

`validation_lifecycle_evidence.py` defines one immutable, content-addressed `ValidationLifecycleEvidenceBundle` and one deterministic `ValidationLifecycleResult` projection over the already-canonical lower-level evidence produced by #757 (authorized admission), #758/#759 (lease and process-tree containment, surfaced through `SingleIssuePilotResult`), #760 (`WorkspaceLifecycleEvidence`), and the existing `ExecutionCompositionResult`. It owns none of that lower-level semantics: it never re-parses Git status, never re-implements lease or termination proof, and never rewrites a lower-level status or identity. It only verifies the supplied canonical objects belong together (repository, every SHA role, invocation, request/plan/runtime fingerprints, and nested result identities) and projects one additive top-level terminal status over the verified whole.

**Three dimensions stay separate**: authorization/admission truth (the #757 admission result), observed runtime/lifecycle truth (the embedded lower-level results), and evidence completeness/integrity (the bundle's `evidence_availability` ledger, using `EvidenceAvailability.{present,not-applicable,unavailable,missing-required}` instead of ambiguous `None`). Successful runtime evidence never manufactures authorization; a terminal status never implies authorization; evidence completeness never implies authorization. `side_effects_performed` is read directly from already-verified `ExecutionCompositionResult`/`SingleIssuePilotResult` observed facts, never inferred from the projected status.

**Terminal statuses** (`ValidationLifecycleTerminalStatus`): `succeeded`, `validation-failed`, `blocked`, `stale`, `timed-out`, `cancelled`, `quarantined`, `cleanup-failed`, `release-failed`, `termination-uncertain`, `evidence-incomplete`. No existing lower-level status vocabulary is renamed or removed. Pre-execution `blocked`/`stale` (and admission `needs-decision`, mapped to `blocked`; admission `invalid`, mapped to `evidence-incomplete`) are decided first and stay authoritative whenever the lifecycle never validly entered execution — a bundle cannot even be constructed with post-execution evidence attached to a non-accepted admission; construction fails closed instead.

For a lifecycle that was accepted into execution, exactly one frozen, documented precedence table (`POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE`) decides the projection, evaluated by one pure function (`project_validation_lifecycle_result`):

```
quarantined > termination-uncertain > cleanup-failed > release-failed
  > timed-out > cancelled > evidence-incomplete > validation-failed > succeeded
```

`succeeded` is a strict conjunction, not a default: verified admission acceptance, `execution_authorized=true`, a `completed` pilot result with confirmed lease acquisition/release, complete filesystem and Git-administrative cleanup, no cancellation/partial effects, a `passed` validation result, complete #760 initial/final workspace evidence, both the declared expected changed paths and the observed final changed paths empty, no quarantine packet, and no missing-required evidence. Any missing conjunct withholds success.

**Bounds and secrets**: the canonical serialized bundle is bounded (`MAX_BUNDLE_SERIALIZED_BYTES`), reason codes and evidence-availability items are bounded and deduplicated, and #761 never truncates lower-level output a canonical lower-level object already records as bounded/truncated. Secret-like public evidence reuses the existing `workflow_scheduler.execution.quarantine_review` redaction/rejection convention rather than a second scanner, and stores opaque IDs/fingerprints instead of copied command/output prose.

**Serialization/reconstruction** uses one schema version, deterministic key/list ordering, strict unknown/missing-field rejection, and a reconstruct → re-verify → recompute-identity path that reuses each nested object's own canonical constructor, serializer, and identity function wherever one exists (`serialize_authorized_validation_lifecycle_request`, `serialize_single_issue_pilot_result`/`single_issue_pilot_result_id`, `serialize_quarantine_evidence_packet`/`quarantine_evidence_packet_id`, the real `WorkspaceStateObservation`/`WorkspaceLifecycleEvidence` constructors); tampering with any embedded identity changes the recomputed `bundle_id`/`result_id` and reconstruction rejects.

**Recovery interpretation**: `evidence_availability`/`reason_codes` on the projected result tell a human adopter which conjunct is missing or which lower-level fact dominated; the bundle makes no rollback, cleanup, retry, or fresh-invocation decision itself — that remains the separately governed #762 concern. Construction, projection, and (de)serialization perform no I/O, subprocess, network/provider call, filesystem write, GitHub publication, cleanup, lease release, retry, or execution.

## Executor routing — Issue #918

Executable-lane selection decides what work may proceed; executor routing decides only which execution surface receives already-approved work.

Deterministic route precedence:
1. `human-decision-required` for ambiguity, excluded surfaces, stale/contradictory evidence, or irreversible/uncertain mutation.
2. `chatgpt-connector-native` when no runtime capability is required.
3. `chatgpt-governed-runner` when available and capable.
4. `external-coding-agent-fallback` only when fallback is available, capable, and explicitly permitted.
5. `human-decision-required` when no approved capable route remains.

The routing-only `ExecutorCapability` vocabulary is closed: `checkout`, `isolated-worktree`, `dependency-installation`, `process-execution`, `compile-or-lint`, `test-execution`, `runtime-inspection`, `generated-artifact-inspection`, `multi-file-implementation`, `git-reconciliation`, `exact-head-validation`, and `checkpointed-resume`.

`ExecutorRouteDecision` and `ExecutorHandoff` reference existing request, authorization, validation-plan, operating-mode, lane-selection, repository-state, worktree, package, environment, checkpoint, resume, and Workflow Scheduler evidence only through bounded opaque identities. Semantic validation remains with each canonical owner.

Routing never creates or widens authority. The router reads no host clock and performs no filesystem, subprocess, network, GitHub, workflow, credential, provider, runner, persistence, production, retry, or external-system operation. The complete frozen contract and stop conditions remain in Issue #918.

## Existing request, planning, and inspection contracts

`ExecutionServiceRequest` and `ExecutionServiceResult` remain frozen, bounded, strictly typed, canonically serialized, and content-addressed. The caller supplies `evaluated_at`; the service never reads the host clock.

Validation command planning maps only registered command strings to fixed argv and performs no shell parsing, alias expansion, user-supplied argv execution, network access, persistence, retry, or runtime dispatch.

`RepositoryInspector` is injected and invoked at most once after validation. Repository-state verification delegates only canonical evidence to the existing validator; private evidence is excluded from public projections.

## Validation

From the repository root:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests/test_authorized_validation.py \
  08_Tooling/agent-os-execution-service/tests/test_executor_routing.py \
  08_Tooling/agent-os-execution-service/tests/test_validation_lifecycle_evidence.py
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
git diff --check
```

## Rollback

Revert the #757 verifier, the #761 unified evidence bundle/projection, lazy exports, focused tests, and the corresponding README sections. No runtime, repository, lease, worktree, process, or external state requires cleanup.
