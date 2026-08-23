# Runtime Execution Request — AOS-EXECSIMPL1 (#1338)

## Purpose

`runtime_execution_request.py` introduces the additive migration target for the
governed runtime path: one immutable, content-addressed, non-authorizing request
record keyed by the existing `executor-handoff:<sha256>` identity.

The request bundles the immutable recovery artifacts that were previously
reachable only through separate route-decision, handoff, invocation-descriptor,
and restart-capsule records:

```text
ExecutorRouteDecision
+ ExecutorHandoff
+ GovernedInvocationDescriptor compatibility projection
+ GovernedResumeRestartCapsule
= RuntimeExecutionRequest
```

It does **not** absorb current authorization, dependency readiness, Scheduler
lease truth, checkpoint/ResumePlan semantics, workspace state, process
containment, validation authority, merge authority, or issue-lifecycle authority.
Those remain with their existing canonical owners and are reacquired before
Scheduler admission.

## Migration behavior

This first implementation is intentionally additive.

At the existing runnable-handoff descriptor persistence seam:

```text
validated current evidence
-> legacy descriptor compatibility marker
-> canonical RuntimeExecutionRequest
-> return only after both durable writes succeed
```

The already-existing route-decision, full-handoff, ResumePlan, checkpoint,
restart-capsule, and descriptor writes are retained in this PR as compatibility
mirrors. No existing record is deleted, rewritten, migrated in place, or made
less strict.

`load_runtime_execution_request_or_legacy(...)` implements the bounded dual-read
transition:

1. load and verify the canonical runtime request when present;
2. if and only if it is absent, reconstruct the same request from the existing
   descriptor + route-decision + handoff + restart-capsule records;
3. if a canonical request is present but malformed/tampered, fail closed — never
   hide the integrity failure by falling back to legacy records.

`load_current_invocation_descriptor(...)` projects the compatibility descriptor
from that dual-read result. This gives later host-composition work a stable seam
to switch from the old record graph without changing Scheduler semantics.

## Canonical ownership

- #918 remains the owner of `ExecutorRouteDecision` and `ExecutorHandoff` routing semantics.
- #895 remains the owner of checkpoint and `ResumePlan` semantics.
- current execution authorization remains reacquired from its existing source.
- dependency readiness remains current runtime evidence and is not persisted as
  authority inside this request.
- Workflow Scheduler remains the lease, workspace, execution lifecycle,
  validation integration, cleanup, and completion authority.
- the runtime request is immutable recovery/transport evidence only.

All request-level authority fields are hard-coded `False`.

## Persistence

The canonical additive store is:

```text
<checkpoint-store-root>/runtime-execution-requests/<handoff-digest>.json
```

Records are canonical JSON, content-addressed, bounded, atomic, idempotent, and
use the existing checkpoint-store path-safety/integrity primitives. The record
is keyed by the existing handoff identity; no second discovery index, queue,
lock, retry system, daemon, Scheduler, or database is introduced.

## Compatibility and rollback

Rollback is repository-only for this phase: revert the #1338 request module,
resolver integration, tests, and this document. Existing legacy records remain
untouched and continue to be sufficient for the pre-#1338 recovery path.
Already-written runtime-request records are immutable, non-authorizing evidence
and do not require deletion.

A later removal phase may stop writing legacy route/handoff/descriptor/capsule
mirrors only after exact-head tests prove the host path consumes the canonical
request directly and old persisted invocations remain readable through bounded
compatibility logic. This PR does not perform that destructive transition.

## Expected simplification after migration

Current publication/recovery uses separate durable records for route decision,
handoff, ResumePlan, checkpoint, restart capsule, and invocation descriptor.
The target after compatibility retirement is:

```text
ExecutorRouteDecision
-> RuntimeExecutionRequest
-> fresh authorization/currentness/dependency checks
-> existing Workflow Scheduler
-> execution/validation result
```

Checkpoint/ResumePlan persistence remains only where genuine continuation
semantics require it.
