# Runtime Execution Request — AOS-EXECSIMPL1 (#1338)

## Purpose

`runtime_execution_request.py` is the additive migration target for the governed
runtime path: one immutable, content-addressed, non-authorizing request record
keyed by the existing `executor-handoff:<sha256>` identity.

The request bundles the immutable recovery artifacts that were previously
reachable only through separate route-decision, handoff, invocation-descriptor,
and restart-capsule records:

```text
ExecutorRouteDecision
+ ExecutorHandoff
+ GovernedInvocationDescriptor compatibility projection
+ GovernedResumeRestartCapsule
+ canonical #1419 ComputeControlProjection (current schema only)
= RuntimeExecutionRequest
```

It does **not** absorb current authorization, dependency readiness, Scheduler
lease truth, checkpoint/ResumePlan semantics, workspace state, process
containment, validation authority, merge authority, or issue-lifecycle authority.
Those remain with their existing canonical owners and are reacquired before
Scheduler admission.

## Migration behavior

At the existing runnable-handoff descriptor persistence seam:

```text
validated current evidence
+ already-produced canonical #1419 projection
-> canonical RuntimeExecutionRequest
-> legacy descriptor compatibility marker
-> return only after both durable writes succeed
```

The request is written first so a discoverable new compatibility descriptor can
never exist without its canonical request. If descriptor publication later
fails, the request may remain as immutable non-authorizing evidence and grants
no Scheduler admission by itself.

The already-existing route-decision, full-handoff, ResumePlan, checkpoint,
restart-capsule, and descriptor writes remain compatibility mirrors during this
phase. No existing record is deleted, rewritten, migrated in place, or made less
strict.

`load_runtime_execution_request_or_legacy(...)` implements the bounded dual-read
transition:

1. load and verify the canonical runtime request when present;
2. if and only if it is absent, reconstruct the same request from the existing
   descriptor + route-decision + handoff + restart-capsule records;
3. if a canonical request is present but malformed/tampered, fail closed — never
   hide the integrity failure by falling back to legacy records.

`load_current_invocation_descriptor(...)` projects the compatibility descriptor
from that dual-read result.

Phase 2 moves the installed production governed-resume factory onto the same
canonical read seam. `build_production_governed_resume_bindings_for_handoff(...)`
loads `RuntimeExecutionRequest-or-legacy`, consumes the embedded invocation
descriptor and restart capsule, then performs the existing dependency-readiness,
advisory reconstruction, GitHub read transport, and host-bootstrap composition.
The loader's source is not authority: current authorization and all other live
admission evidence remain reacquired by their existing owners downstream.

This means a valid canonical request is now the preferred production recovery
packet, while old persisted invocations remain resumable through the bounded
legacy reconstruction path. A present malformed canonical request remains a
fail-closed integrity error and cannot silently downgrade to legacy evidence.

## Compute-control transport — AOS-NCCE5 (#1487)

The current write schema is `agent-os.runtime-execution-request/1.1`. It carries
exactly one already-produced canonical
`agent-os-compute-control-projection/1.0` `ComputeControlProjection` supplied by
the upstream #1419 producer path. The runtime-request publication seam only
transports that object; it does not derive, upgrade, downgrade, or reinterpret a
compute disposition.

The request constructor binds the supplied projection to the runtime subject:

- projection repository must match the runtime request repository;
- projection issue number must match the invocation issue;
- projection `current_head_sha` must match the invocation descriptor source SHA;
- the canonical projection ID and source revision are preserved rather than
  recomputed heuristically;
- malformed, unsupported-version, noncanonical, or tampered projection content
  fails closed.

The projection is part of the canonical request payload, so replacing it changes
the `RuntimeExecutionRequest.request_id`. All request-level authority fields
remain hard-coded `False`; the presence of a projection does not grant execution,
GitHub write, merge, closure, or external-write authority.

Legacy `agent-os.runtime-execution-request/1.0` records remain readable and carry
no compute-control projection. Their payload shape and content identity remain
unchanged. Legacy reconstruction is used only when the canonical request is
truly absent; a present malformed current request never falls back silently.

Production governed-resume already propagates the complete canonical runtime
request through the host factory/bootstrap path. Therefore #1486 can consume the
embedded `compute_control_projection` at the final pre-runtime dispatch seam
without deriving missing #1419 claim/freshness/authority semantics locally.
#1487 itself adds no dispatch decision or Scheduler behavior.

Notion is not an input to this runtime request and cannot grant compute admission.
This transport performs no Notion, network, cloud, process, Scheduler, workflow,
or production side effect.

## Canonical ownership

- #918 remains the owner of `ExecutorRouteDecision` and `ExecutorHandoff` routing semantics.
- #895 remains the owner of checkpoint and `ResumePlan` semantics.
- #1419 remains the owner of compute-control decision/projection semantics.
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

Legacy writes remain intact. No historical record migration or retirement is
performed.

Rollback of #1487 is repository-only: revert the runtime-request `1.1` transport,
publication-seam parameter, focused tests, and this documentation section. The
pre-#1487 `1.0` reader and legacy record graph remain the compatibility baseline;
already-written request records are immutable non-authorizing evidence and do not
require destructive cleanup.

A later removal phase may stop writing legacy route/handoff/descriptor/capsule
mirrors only after exact-head tests prove the host path consumes the canonical
request directly and old persisted invocations remain readable through bounded
compatibility logic. This change deliberately does not perform that destructive
transition.

## Expected simplification after migration

Current publication still writes separate compatibility records, but production
recovery now has one preferred durable packet:

```text
ExecutorRouteDecision
-> RuntimeExecutionRequest (+ canonical #1419 projection)
-> fresh authorization/currentness/dependency checks
-> #1486 compute-control admission guard
-> existing Workflow Scheduler
-> execution/validation result
```

Checkpoint/ResumePlan persistence remains only where genuine continuation
semantics require it.
