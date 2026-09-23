# Authorized Handoff Publication — AOS-INV1B (#1409)

## Purpose

`authorized_validation_entrypoint.publish_authorized_validation_handoff(...)` is the production composition caller that connects an already-admitted Execution Service lifecycle to the existing #1243 governed handoff publication seam.

It closes the production-caller gap exposed by #1239 discovery run `32899227152`, which found no matching current invocation descriptor.

## Ownership and ordering

The caller does not build or persist a handoff or descriptor itself. It reuses current objects already owned by `AuthorizedValidationLifecycleRequest` and accepts only the canonical references that #757 does not carry:

- #918 `ExecutorRouteDecision`;
- #895 `ExecutionCheckpoint`;
- #895 `ResumePlan`;
- #1197 `DependencyReadinessEvidence`.

It then delegates exactly once to #1243 `publish_governed_handoff(...)`.

```text
AuthorizedValidationLifecycleRequest
-> verify #757 admission is ACCEPTED
-> require #1201 dispatch compatibility when supplied
-> reuse request + authorization + CandidatePacket + runtime configuration
-> accept route decision + checkpoint + ResumePlan + dependency readiness
-> #1243 publish_governed_handoff(...)
-> existing persistence ordering
-> return the exact ExecutorHandoff from #1243
```

The canonical invariant remains:

```text
HANDOFF_PUBLISHED => DESCRIPTOR_PRESENT
```

## Fail-closed behavior

Non-accepted admission exposes no runnable handoff. A non-compatible #1201 dispatch decision blocks before publication. All route, source, authorization, checkpoint/ResumePlan, environment/dependency, workspace, identity, persistence, and idempotency validation after that boundary remains owned by #1243/#1218 and their existing canonical dependencies.

## Non-goals

This caller adds no descriptor schema, handoff schema, persistence path, state owner, Scheduler call, lease, retry, fallback, workflow, provider route, IAM/WIF behavior, host behavior, or VM behavior. It does not execute the published handoff.

## Live activation boundary

Repository implementation and validation under #1409 do not authorize live publication. After exact-head green review, a separate live authorization must identify current #1239 canonical evidence and permit exactly one publication attempt. Fresh `/agent-os discover`, `/agent-os resume`, deliberate replay, and Scheduler execution remain separately gated.

## Rollback

Revert the #1409 entrypoint extension, focused tests, and this document. No external cleanup is required because #1409 performs no live publication.
