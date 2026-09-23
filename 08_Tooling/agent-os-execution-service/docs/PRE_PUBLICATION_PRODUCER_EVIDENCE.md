# Pre-publication producer evidence capsule (#1412)

`PrePublicationEvidenceCapsule` is the one durable, non-authorizing evidence
transport used to bridge canonical candidate/approval/validation evidence into
the first governed handoff publication, before a `GovernedInvocationDescriptor`
exists.

It does **not** authorize execution or publication. Current execution
authorization, dependency readiness, route currentness, ResumePlan currentness,
and publication admission remain independently reacquired by #1411/#1409.

## Canonical contents

The capsule reuses existing canonical transports and identities for:

- the execution-candidate `CandidatePacket`;
- the approved #398 `ApprovalRecord`;
- the declarative `RequiredEnvironmentSpec`;
- the canonical validation evidence bundle and plan/bundle/advisory identities;
- candidate branch/workspace/invalidation bindings needed to rebuild the
  in-memory `SingleIssuePilotInput`;
- the exact #895 `ExecutionCheckpoint` identity that must already be durable.

No nested approval, candidate, validation, environment, checkpoint, Scheduler,
lease, route, descriptor, or authorization semantics are redefined here.

## Persistence

`pre_publication_evidence_store.py` is the **only** #1412 persistence owner.
It writes under the existing checkpoint-store root in:

```text
pre-publication-producer-evidence/
```

The store uses the existing checkpoint-store atomic/content-addressed write
primitives. Before a capsule becomes visible, it independently loads and
revalidates the exact bound checkpoint through `load_checkpoint_by_id(...)`.
Missing, quarantined, conflicting, or drifted checkpoint evidence fails closed
with zero capsule write.

Equivalent evidence converges on the same content identity and the same file.
No mutable HEAD, retry/fallback path, database, alternate root, network call,
GitHub call, cloud call, Scheduler dispatch, or lease action is introduced.

## Authority boundary

Every authority flag carried by the capsule is fixed `False`, including:

- `repository_implementation_authorized`;
- `execution_authorized`;
- `publication_authorized`;
- `github_writes_authorized`;
- `merge_authorized`;
- `external_writes_authorized`.

Capsule presence is evidence availability only. It can never substitute for a
current owner-authored execution authorization record or a current durable
checkpoint.

## #1411 handoff

After #1412 is merged, #1411 should load the capsule from the canonical host
checkpoint store, reacquire current live issue/repository evidence, revalidate
the carried approval/candidate/validation bindings, independently reacquire
current execution authorization/checkpoint/route/ResumePlan/dependency evidence,
rebuild the complete `SingleIssuePilotInput` in memory, and invoke the existing
#1409 `publish_authorized_validation_handoff(...)` boundary.

The complete pilot input remains in memory only. #1243/#1218 remain the sole
owners of runnable handoff and descriptor publication.
