# First-publication producer activation (#1428)

`agent_os_execution_service.first_publication_producer` is the bounded composition
that prepares the existing canonical artifacts required by the production handoff
publisher. It is not a publisher and it is not an execution entrypoint.

## Ordering

```text
current canonical evidence
-> #1431 construct_execution_checkpoint(...)
-> #895 append_checkpoint(...)
-> #895 plan_resume(...) + append_resume_plan(...)
-> #918 select_executor_route(...) + existing route-decision store
-> require already-READY/current #1197 DependencyReadinessEvidence
-> existing dependency-readiness store
-> #1412 build_pre_publication_evidence(...)
-> #1412 append_pre_publication_evidence(...)
-> return immutable producer identities
-> STOP
```

The producer never calls `publish_authorized_validation_handoff(...)`,
`publish_governed_handoff(...)`, Workflow Scheduler, a lease API, or dependency
installation. A dependency state other than current `READY` fails before any
producer write. Dependency preparation remains a separately authorized Workflow
Scheduler operation.

## Authority

The operation consumes an exact current `ExecutionAuthorizationEvidence` and binds
its identity into #918 routing. It does not create authorization. The returned
result contains identities and `publication_invoked=false` /
`scheduler_invoked=false`; it exposes no execution/publication/GitHub-write/merge
authority flags.

`PrePublicationEvidenceCapsule` remains explicitly non-authorizing. #1411 must
still reacquire current authorization, checkpoint, route, ResumePlan, dependency,
repository, and runtime evidence before publication.

## Persistence

Every write uses the existing checkpoint-store root supplied by the caller/host
composition. This module defines no path, database, queue, descriptor store,
checkpoint store, retry database, or alternate persistence owner. Equivalent
canonical inputs converge through the existing content-addressed stores.

## Production integration

This module intentionally exposes a Python composition boundary first. A fixed
host CLI/adapter may call it only after trusted host composition can reacquire the
required canonical evidence without accepting caller-selected store paths,
hashes, commands, credentials, or authority. GitHub Actions workflow changes,
GCE deployment, live producer execution, publication, discovery, resume, replay,
and Scheduler execution remain separate authorization boundaries.
