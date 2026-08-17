# Governed Invocation Reconstruction — #1218

## Purpose
#1218 adds the smallest host-side seam required for a future fixed
`/agent-os resume <handoff-id>` transport without turning GitHub Actions, a
remote shell, or Workflow Scheduler into a second state system.

The execution-checkpoint/continuation architecture owns one persisted
`GovernedInvocationDescriptor`, keyed by the immutable
`executor-handoff:<sha256>` identity. It contains references to canonical
evidence, never the complete `SingleIssuePilotInput`, and all authority fields
are fixed `False`.

## Data flow
```text
executor-handoff id
  -> checkpoint-store invocations/<handoff digest>.json
  -> GovernedInvocationDescriptor
  -> reacquire current canonical objects exactly once
  -> cross-check identities and scope
  -> inspect existing host-local Scheduler lease exactly once
  -> exact current SingleIssuePilotInput OR fail-closed result
```

The descriptor references repository/issue, route decision, execution-service
request fingerprint, authorization, source ref/SHA, checkpoint, ResumePlan,
environment profile/health, required-environment and dependency-readiness
evidence, Workflow Scheduler runtime identity, candidate packet, concrete
runtime-configuration fingerprint, and execution/invocation identity. These are
references, not duplicated authoritative objects; drift makes reconstruction
stale or blocked instead of rewriting historical evidence.

## Public seams
Checkpoint/continuation package:
```python
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor, append_invocation_descriptor,
    load_invocation_descriptor,
)
```

Execution Service:
```python
from agent_os_execution_service.invocation_reconstruction import (
    CurrentInvocationEvidence, InvocationReconstructionResult,
    reconstruct_governed_invocation,
)
```

`reconstruct_governed_invocation(...)` accepts one handoff identity plus a
bound descriptor loader, current-evidence resolver, lease observation reader,
and trusted evaluation time. The external/user-controlled value is the handoff
identity only.

## Fail-closed behavior
Reconstruction returns no pilot input for descriptor tamper/rebinding;
route/handoff or execution-authorization drift; repository/source/scope drift;
checkpoint invalidation or ResumePlan mismatch/completion; environment or
dependency-readiness drift; candidate/runtime-configuration or pilot-input
drift; active conflicting lease; ambiguous retained/orphaned lease; or a prior
lease generation proving the same logical invocation was already consumed.

Ambiguous lease ownership is never expired, stolen, force-released, or taken
over. #1202 exclusively owns recovery. An inactive exact lease with generation
above zero blocks replay; a legitimate continuation needs a new canonical
invocation identity.

## Authority and side effects
The descriptor and reconstruction result are evidence only. They grant no
execution, GitHub write, merge, closure, workflow, cloud, or external-write
authority. Reconstruction performs no GitHub/network/subprocess/provider, VM
lifecycle, Scheduler dispatch, lease acquisition/release, retry, or fallback.

The current-evidence resolver may perform read-only reacquisition appropriate
to its environment, but #1218 does not implement that adapter. #1203 should
bind a fixed resolver and descriptor-store location and pass only the validated
handoff identity across its transport boundary.

## Existing contract ownership
- #918 owns `ExecutorRouteDecision` / `ExecutorHandoff`.
- #895/#1188 own checkpoint / ResumePlan evidence.
- #1197 owns required-environment / dependency-readiness evidence.
- #758/#1202 own Scheduler lease/concurrency/recovery truth.
- #759 containment stays in the existing concrete runtime configuration.
- Workflow Scheduler still requires an already supplied `SingleIssuePilotInput`;
  #1218 only admits the freshly reacquired input when all bindings remain exact.

## Non-goals
No queue, daemon, database, distributed/replay lock, second Scheduler, retry
loop, fallback provider, workflow, cloud credential, remote-shell protocol, or
complete runtime-packet persistence is added.
