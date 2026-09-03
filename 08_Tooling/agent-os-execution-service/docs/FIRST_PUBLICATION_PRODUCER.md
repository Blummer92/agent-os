# First-publication producer activation (#1428 / #1799)

`agent_os_execution_service.first_publication_producer` is the bounded composition
that prepares the existing canonical artifacts required by the production handoff
publisher. It is not a publisher and it is not an execution entrypoint.

## Two-phase #1412 evidence

#1799 extends the existing `PrePublicationEvidenceCapsule` owner rather than
creating a second producer-input transport. Legacy schema `1.0` remains the
checkpoint-bound format with unchanged identity semantics. Schema `1.1` has two
explicit finite phases:

```text
source
checkpoint-bound
```

A `source` capsule carries the exact already-canonical CandidatePacket, approved
ApprovalRecord, RequiredEnvironmentSpec, validation bundle and plan identity,
advisory identities, candidate branch, workspace request, invalidation events,
timestamps, and one bounded non-authorizing execution identity. It has no
checkpoint ID and grants no authority. It may be persisted in the existing
`pre-publication-producer-evidence` namespace before a checkpoint exists.

`bind_source_capsule_to_checkpoint(...)` accepts only one exact v1.1 source
capsule plus one exact matching #895 `ExecutionCheckpoint`. Repository, issue,
invocation, execution, branch, source SHA, and tested SHA must all match. The
result preserves the source evidence and adds only the checkpoint binding.
Equivalent source/checkpoint pairs converge to the same content identity.

The historical `load_pre_publication_evidence(...)` remains the publication-facing
loader and explicitly rejects source-phase evidence. The separate
`load_source_pre_publication_evidence(...)` exists only for the future trusted
#1428 host activation. A source capsule therefore cannot reach #1411/#1409/#1243
publication merely because it is durable.

## Intended ordering

```text
already-produced canonical pre-PR evidence
-> #1412 source capsule + existing #1412 store
-> trusted host reacquires current repository/issue/authorization/dependency truth
-> #1431 truthful preflight-complete checkpoint
-> #895 append_checkpoint(...)
-> bind source capsule to exact durable checkpoint
-> persist checkpoint-bound #1412 capsule
-> #895 plan_resume(...) + append_resume_plan(...)
-> #918 select_executor_route(...) + existing route-decision store
-> require already-READY/current #1197 DependencyReadinessEvidence
-> existing dependency-readiness store
-> return immutable producer identities
-> STOP
```

The producer never calls `publish_authorized_validation_handoff(...)`,
`publish_governed_handoff(...)`, Workflow Scheduler, a lease API, or dependency
installation. Dependency preparation remains a separately authorized Workflow
Scheduler operation.

## Authority

Neither capsule phase creates execution authorization. The trusted host must
reacquire current `ExecutionAuthorizationEvidence`, dependency readiness, route,
ResumePlan, repository and runtime currentness independently. All authority flags
on both phases remain hard-false.

## Persistence

Both phases use the existing checkpoint-store root and the same
`pre-publication-producer-evidence` namespace. No new path, database, queue,
mutable pointer, descriptor store, checkpoint store, retry database, or alternate
persistence owner is introduced. Legacy v1.0 records require no migration.

## Production integration

The future fixed #1428 host activation should accept only bounded lineage/source
capsule identity, reacquire host-current evidence, construct a truthful
`preflight-complete` checkpoint, and finalize the source capsule. GitHub Actions
workflow changes, GCE deployment, live producer execution, publication,
discovery, resume, replay, and Scheduler execution remain separate authorization
boundaries.
