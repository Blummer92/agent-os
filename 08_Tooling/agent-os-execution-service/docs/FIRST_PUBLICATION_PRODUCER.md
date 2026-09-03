# First-publication producer activation (#1428 / #1799 / #1830)

`agent_os_execution_service.first_publication_producer` remains the canonical
producer composition. #1799 adds the two-phase #1412 evidence envelope,
#1830 captures the source phase at the successful authorized-validation boundary,
and `agent_os_execution_service.first_publication_source_activation` supplies the
bounded continuation from one exact durable source capsule to the existing
producer identities. None of these modules is a publisher or Scheduler entrypoint.

## Two-phase #1412 evidence

Legacy schema `1.0` remains checkpoint-bound with unchanged identity semantics.
Schema `1.1` has explicit `source` and `checkpoint-bound` phases.

A `source` capsule carries the exact already-canonical CandidatePacket, approved
ApprovalRecord, RequiredEnvironmentSpec, validation bundle/plan identity,
advisory identities, candidate branch, workspace request, invalidation events,
timestamps, and one bounded non-authorizing execution identity. It has no
checkpoint ID and grants no authority.

`bind_source_capsule_to_checkpoint(...)` accepts one exact v1.1 source capsule and
one exact matching #895 checkpoint. Repository, issue, invocation, execution,
branch, source SHA, and tested SHA must all match. Equivalent pairs converge to
the same immutable identity.

The publication-facing `load_pre_publication_evidence(...)` explicitly rejects
source-phase records. `load_source_pre_publication_evidence(...)` is used only by
the #1428 source activation.

## #1830 source capture

`run_production_authorized_validation_with_source_capture(...)` wraps the existing
#762 authorized-validation lifecycle without changing its admission or execution
semantics. It calls that lifecycle exactly once. Only a terminal `succeeded`
result may proceed to source capture; every other terminal result returns with no
#1412 write.

The capture reuses existing owners rather than accepting producer evidence from an
external caller:

- CandidatePacket comes from the exact `AuthorizedValidationLifecycleRequest`;
- `SingleIssuePilotInput` is the exact lifecycle input;
- RequiredEnvironmentSpec comes from the already-bound runtime configuration;
- execution identity is the Scheduler-owned deterministic `pilot_holder_identity`
  for the exact `PilotLeaseRequest`, not the #761 evidence-bundle identity;
- `created_at`/`evaluated_at` use the lifecycle's canonical evaluation time;
- expiry is bounded by the execution authorization that admitted the specimen;
- the store root comes only from `load_production_host_configuration()` and its
  existing `ProductionHostConfiguration.checkpoint_store_root`.

The capture then calls `build_source_pre_publication_evidence(...)` once and
`append_pre_publication_evidence(...)` once. It creates no checkpoint, ResumePlan,
route decision, descriptor, handoff, dependency preparation, publication, retry,
or additional Scheduler dispatch. Equivalent source evidence converges through
the existing content-addressed #1412 store.

## #1428 source activation

`activate_first_publication_source(...)` accepts one exact source-capsule identity
plus evidence already reacquired by trusted host composition. It does not accept
store roots, repository paths, workspace paths, commands, credentials, or
authority booleans as part of its request contract. The trusted host supplies the
existing checkpoint-store root outside that bounded request.

The activation checks the source capsule against the current execution identity
before any write, independently requires current execution authorization and
current READY dependency evidence, then composes only existing owners:

```text
exact #1412 source capsule
-> verify repository / issue / invocation / execution / branch / source / tested bindings
-> require current execution authorization
-> require current READY dependency evidence
-> #1431 construct truthful checkpoint from already-observed host evidence
-> #895 append_checkpoint(...)
-> #1799 bind source capsule to exact checkpoint
-> #1412 append checkpoint-bound capsule
-> #895 plan_resume(...) + append_resume_plan(...)
-> #918 select_executor_route(...) + existing route-decision store
-> existing dependency-readiness store
-> return immutable producer identities
-> STOP
```

The activation deliberately does not serialize or persist a complete
`SingleIssuePilotInput`. The irreducible pre-PR evidence comes from the source
capsule; current authorization, dependency, repository/worktree/environment,
acceptance, governance, and route evidence remain host-reacquired inputs owned by
their existing contracts.

## Authority

Neither capsule phase, source capture, nor source activation creates execution
authorization. All publication/Scheduler/GitHub-write/merge/external-write
authority remains outside these operations. Dependency preparation/installation is
not implicit: any non-READY state fails before producer writes.

## Persistence

Both capsule phases use the existing checkpoint-store root and the same
`pre-publication-producer-evidence` namespace. The activation reuses the existing
#895 checkpoint/ResumePlan stores, #918 route-decision store, and #1197 dependency
readiness store. No new root, mutable pointer, database, queue, retry store,
descriptor store, or alternate persistence owner is introduced.

## Remaining production boundary

After #1830, a successful production authorized-validation lifecycle can leave one
exact durable source-capsule identity for #1428. A fixed host CLI/transport wrapper
may call the source activation only after trusted host composition has reacquired
the required current evidence. GitHub Actions changes, GCE deployment/host refresh,
live producer execution, #1411 publication, discovery, resume, replay, and
Scheduler execution remain separate authorization boundaries.
