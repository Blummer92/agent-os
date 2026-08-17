# Governed Invocation Reconstruction — #1218

## Purpose

#1218 adds the smallest host-side seam required for a future fixed
`/agent-os resume <handoff-id>` transport without turning GitHub Actions, a
remote shell, or Workflow Scheduler into a second state system.

The existing execution-checkpoint/continuation architecture owns one small
persisted `GovernedInvocationDescriptor`. The descriptor is keyed by the
existing immutable `executor-handoff:<sha256>` identity and contains only
references to already-canonical evidence. It never stores the complete
`SingleIssuePilotInput` and every authority field is fixed `False`.

## Data flow

```text
executor-handoff id
  -> checkpoint-store invocations/<handoff digest>.json
  -> GovernedInvocationDescriptor
  -> reacquire current canonical objects exactly once
  -> cross-check existing identities and scope
  -> inspect existing host-local Scheduler lease exactly once
  -> exact current SingleIssuePilotInput OR fail-closed result
```

The descriptor references repository/issue, route decision, execution-service
request fingerprint, authorization, source ref/SHA, checkpoint, ResumePlan,
environment profile/health, required-environment and dependency-readiness
evidence, Workflow Scheduler runtime identity, candidate packet, concrete
runtime-configuration fingerprint, and execution/invocation identity.

These are references, not duplicated copies of the authoritative objects.
Changing any referenced current evidence therefore makes reconstruction stale
or blocked instead of rewriting the historical descriptor.

## Public seams

Checkpoint/continuation package:

```python
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
    load_invocation_descriptor,
)
```

Execution Service:

```python
from agent_os_execution_service.invocation_reconstruction import (
    CurrentInvocationEvidence,
    InvocationReconstructionResult,
    reconstruct_governed_invocation,
)
```

`reconstruct_governed_invocation(...)` accepts one handoff identity plus
injected infrastructure dependencies: a descriptor loader, one current-evidence
resolver, one lease observation reader, and a trusted current evaluation time.
The external/user-controlled value is the handoff identity only.

## Fail-closed behavior

Reconstruction returns no pilot input when any of the following is unresolved:

- descriptor missing, malformed, tampered, or rebound;
- route/handoff identity drift or route no longer targets the governed runner;
- execution authorization absent, mismatched, expired, or not yet current;
- repository/source/request-scope drift;
- checkpoint invalidation, lifecycle drift, or ResumePlan mismatch/completion;
- environment profile/health, required-environment, or dependency-readiness drift;
- candidate-packet or concrete runtime-configuration drift;
- pilot-input identity/scope/test drift;
- active conflicting Scheduler lease;
- ambiguous retained/orphaned lease; or
- a prior generation proving the same logical invocation was already consumed.

Ambiguous lease ownership is never expired, stolen, force-released, or taken
over. Recovery remains exclusively governed by #1202. A generation greater
than zero on an inactive exact lease blocks replay of the same invocation; a
new legitimate continuation must carry a new canonical invocation identity.

## Authority and side effects

The descriptor and reconstruction result are evidence only. They do not grant
execution, GitHub write, merge, closure, workflow, cloud, or external-write
authority. Reconstruction itself performs no GitHub/network/subprocess/provider,
VM lifecycle, merge, issue closure, Scheduler dispatch, lease acquisition,
lease release, retry, or fallback operation.

The current evidence resolver may perform read-only reacquisition appropriate
to its execution environment, but that adapter is not implemented by #1218.
#1203 is expected to bind a fixed resolver/descriptor-store location and pass
only the validated handoff identity across its transport boundary.

## Relationship to existing contracts

- #918 remains the canonical `ExecutorRouteDecision` / `ExecutorHandoff` owner.
- #895/#1188 remain the checkpoint / ResumePlan evidence owners.
- #1197 remains the required-environment / dependency-readiness owner.
- #758/#1202 remain the only Scheduler lease/concurrency/recovery authority.
- #759 containment remains part of the already-bound concrete runtime
  configuration and is not reimplemented here.
- Workflow Scheduler still accepts an already fully supplied
  `SingleIssuePilotInput`; #1218 only decides whether one freshly reacquired
  input is still the exact input bound by the immutable invocation evidence.

## Non-goals

#1218 does not add a queue, daemon, database, distributed lock, replay lock,
second Scheduler, retry loop, fallback provider, workflow, cloud credential,
remote-shell protocol, or complete runtime-packet persistence.
