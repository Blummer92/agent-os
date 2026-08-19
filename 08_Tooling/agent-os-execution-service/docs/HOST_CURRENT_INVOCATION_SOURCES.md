# Host Current Invocation Sources

## Purpose

Issue #1253 closes #1218/#1238 Blocker B with one repository-owned host composition behind the existing `InvocationEvidenceSources` contract.

`HostCurrentInvocationSources` reacquires current evidence from existing owners and rejects descriptor-binding mismatches. `CanonicalCurrentInvocationResolver` remains responsible for exact current evidence construction and authorization reacquisition; `reconstruct_governed_invocation(...)` remains responsible for full cross-binding/currentness checks and existing Scheduler lease observation.

This module is composition only. It creates no Scheduler, state store, readiness owner, authorization owner, retry system, or execution authority.

## Canonical order

```text
executor-handoff:<sha256>
-> GovernedInvocationDescriptor loader
-> HostCurrentInvocationSources
   -> route + handoff readers (#918)
   -> checkpoint + ResumePlan readers (#895)
   -> CandidatePacket rebuilder
   -> runtime-configuration builder
   -> DependencyReadinessEvidence loader (#1197 semantics / #1254 store)
   -> in-memory SingleIssuePilotInput builder
-> CanonicalCurrentInvocationResolver
   -> execution-authorization reacquisition (#1226/#1227)
-> reconstruct_governed_invocation(...)
   -> #1218 binding/currentness checks
   -> #758/#1202 lease observation
-> admitted current SingleIssuePilotInput or fail closed
```

## Dependency-readiness recovery

Merged PR #1254 made the bounded, content-addressed `DependencyReadinessEvidence` restart-recoverable in the checkpoint-owned append-only store. The host composition calls `load_dependency_readiness(...)` by the descriptor-bound evidence identity and verifies source SHA, required-environment identity, environment-health identity, execution surface, and workspace identity.

Persistence does not establish currentness. The existing #1218 checks still require READY evidence in its valid time window. Matching SHA alone is insufficient when workspace, environment, or execution-surface identity differs.

## Existing-owner injection

Read-only callables supply route decision, handoff, checkpoint, ResumePlan, CandidatePacket, runtime configuration, and pilot input. They remain owned by their existing canonical readers/rebuilders; dependency injection does not create new authority. A #1238 host entrypoint must not replace them with issue prose, descriptor snapshots, timestamps, or shell-derived assumptions.

## Fail-closed bindings

Before evidence reaches the resolver, the composition checks the descriptor-bound identity fields available for each object, including repository/issue/invocation/source bindings, route/handoff/checkpoint/resume identities, CandidatePacket identity, runtime fingerprint, and exact dependency workspace/surface/environment bindings.

The existing reconstruction path remains the final owner of complete currentness classification and lease observation.

## Authority boundary

Successful composition authorizes no side effect. It does not dispatch the Scheduler; acquire/release/recover a lease; create execution authorization; write GitHub; mutate cloud/IAM/VM/IAP/OS Login; change workflows/protected settings; retry/fallback; persist a complete `SingleIssuePilotInput`; merge; or close an issue.

The complete `SingleIssuePilotInput` exists only in memory after current evidence is reacquired.

## #1238 handoff

After #1253 is exact-head green, #1238 may bind its fixed governed-resume host entrypoint to the existing reconstruction API with:

1. one validated immutable `executor-handoff:<64-lowercase-hex>` identity;
2. the existing descriptor loader;
3. `HostCurrentInvocationSources` using canonical current readers/rebuilders and checkpoint store root;
4. `CanonicalCurrentInvocationResolver` using the existing execution-authorization source transport;
5. the existing lease observation reader; and
6. `reconstruct_governed_invocation(...)` before Scheduler admission.

#1238 must not move evidence discovery into shell code or infer readiness from descriptor presence.

## Rollback

Remove this composition module/tests/documentation and return callers to the prior injected `InvocationEvidenceSources` implementation. #1254 dependency-readiness records remain valid bounded historical evidence and need no cleanup.
