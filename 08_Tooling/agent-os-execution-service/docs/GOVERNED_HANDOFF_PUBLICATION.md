# Governed Handoff Publication — AOS-INV1A (#1243)

## Purpose

`handoff_publication.py` is the thin Execution Service composition seam that
publishes one already-authorized, already-current governed-runner handoff only
after the existing #1218 invocation descriptor is durable.

It closes the publication-order gap between #918 routing and #1218 reconstruction
without creating another orchestrator, Scheduler, lease, checkpoint store,
authorization model, retry path, provider selector, queue, daemon, or control
plane.

## Canonical ordering

```text
supplied current canonical evidence
-> validate current ExecutionServiceRequest
-> replay #918 select_executor_route(...) deterministically
-> require chatgpt-governed-runner
-> #918 build_executor_handoff(...)
-> build the existing non-authorizing GovernedInvocationDescriptor in memory
-> run #1218 canonical current-binding checks
-> #1228 persist_current_invocation_descriptor(...)
-> verify persisted descriptor/handoff identities
-> return the existing ExecutorHandoff
```

Required invariant:

```text
HANDOFF_PUBLISHED => DESCRIPTOR_PRESENT
```

A handoff object may be constructed internally before persistence, but it is not
returned or exposed to transport until persistence reports success or idempotent
convergence.

## Ownership

- #918 owns `ExecutorRouteDecision`, `ExecutorHandoff`, route selection, and handoff identity.
- #1218/#1219/#1228 own invocation descriptor shape, current-evidence semantics, and descriptor persistence.
- #895 owns checkpoint/ResumePlan persistence.
- Workflow Scheduler remains sole admission, lease, execution, containment, cleanup, and release authority.
- #1238 owns the future fixed GCE host entrypoint and deployment/integrity work.

The publication seam owns only ordering/composition across those existing owners.

## Inputs

`publish_governed_handoff(...)` accepts current canonical objects rather than raw
transport text:

- `ExecutionServiceRequest`
- `ExecutorRouteDecision`
- `ExecutionAuthorizationEvidence`
- `ExecutionCheckpoint`
- `ResumePlan`
- `CandidatePacket`
- `ConcreteRuntimeConfiguration`
- `DependencyReadinessEvidence`
- `SingleIssuePilotInput`
- caller-supplied evaluation time
- bounded return-evidence and stop-condition tuples
- checkpoint-store root already owned by #895/#1218

The complete `SingleIssuePilotInput` is consumed only to verify existing bindings
and derive the already-canonical workspace identity. It is never serialized or
persisted by this seam.

## Currentness and fail-closed behavior

Before persistence, the seam reuses #1218's existing reconstruction cross-check
through `validate_current_invocation_bindings(...)`. That canonical check covers
route/handoff identity, authorization/currentness, repository/source/scope,
checkpoint/ResumePlan, environment/dependency readiness, execution surface,
workspace, CandidatePacket, runtime configuration, and pilot-input consistency.

The publisher additionally verifies that the current Execution Service request is
unexpired, deterministically replays #918 route selection, requires the governed
runner route, and binds repository/subject/request fingerprint/source ref/SHA back
to the request used to build the handoff.

Any mismatch blocks publication. No fallback or automatic retry occurs.

## Idempotency and partial failure

`persist_current_invocation_descriptor(...)` continues to use the existing
append-only handoff-keyed checkpoint store.

- identical descriptor already present -> idempotent success;
- conflicting bytes under the same handoff identity -> existing integrity conflict;
- persistence/storage exception -> publication error and no returned handoff;
- malformed persistence outcome or identity mismatch -> publication error and no returned handoff.

A descriptor can remain durably present after a later caller-side publication
failure because it is immutable, non-authorizing evidence. The seam never deletes
or rewrites it as rollback.

## Authority boundary

Descriptor persistence does not imply:

- Scheduler admission;
- lease acquisition;
- process start;
- validation success;
- GitHub write authority;
- Ready-for-Review;
- merge;
- issue closure;
- cloud/VM authority.

The module performs no Scheduler call, lease operation, subprocess execution,
network/provider operation, GitHub mutation, workflow mutation, credential/IAM
operation, or cloud/VM operation.

## Validation

Focused #1243 tests must run before a Draft PR is created. They cover publication
ordering, deterministic/idempotent replay, pre-persistence current-binding
failure, non-governed routes, persistence failure/mismatch, descriptor-builder
reuse, and architecture boundaries. Existing #918 and #1218/#1228 regression
suites remain the canonical detailed tests for route and reconstruction mismatch
semantics.

An isolated no-network harness may be used for developer feedback, but it is not
canonical pre-PR or exact-head evidence. Draft PR creation remains gated on the
issue-required repository-capable focused/regression validation.

Ready-for-Review still requires authoritative exact-head repository validation.

## Rollback

Revert the #1243 publication module, its focused tests/docs, and the additive pure
builder/validation wrapper in `current_invocation_resolver.py`. No Scheduler,
checkpoint data migration, cloud, VM, IAM, workflow, or production cleanup is
required.

Already-written invocation descriptors are immutable reference evidence and do
not grant authority; rollback does not delete durable checkpoint evidence.

## Downstream handoff

After #1243 is exact-head green, #1218 can treat runnable handoff publication as
wired and continue with Blocker B: concrete host current-evidence/runtime-packet
reconstruction. After that, #1238 may implement the fixed host entrypoint under
its separate repository/deployment authorization gates.
