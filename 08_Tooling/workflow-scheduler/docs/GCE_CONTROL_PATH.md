# GCE Control Path — #1217

## Purpose

#1217 defines the smallest governed Google Compute Engine control-path contract
used by the bounded #1203 GitHub ingress. The control path is transport and VM
actuation only. It does not own Scheduler admission, execution authorization,
lease truth, retry, provider selection, publication, or repository writes.

Canonical flow:

```text
GitHub OIDC
-> Google Workload Identity Federation
-> dedicated transport service account
-> exact GCE resource tuple
-> start-if-stopped / observe-running
-> IAP + OS Login
-> fixed host entrypoint with one executor-handoff id
-> #1218 invocation reconstruction
-> existing Workflow Scheduler
-> bounded evidence
-> evidence-gated VM stop
```

## Exact resource tuple

The v1 qualification target is fixed to:

```text
project:  agent-os-502614
zone:     us-central1-a
instance: agent-os-test
```

A caller that supplies any other resource tuple is rejected before the control
adapter performs an external action.

## OIDC trust envelope

The pure control-path contract requires exact values for:

- repository;
- repository owner;
- exact `workflow_ref`;
- `refs/heads/main`;
- configured Google Workload Identity Provider audience.

These fields model the frozen Google trust boundary. #1203 separately owns the
GitHub comment actor rule and canonical Agent OS authorization reacquisition.
A matching OIDC claim set does not itself authorize Agent OS execution.

No service-account JSON key, SSH private key, or other long-lived credential is
part of this repository contract.

## Fixed host invocation

The only caller-controlled invocation datum is one canonical identity:

```text
executor-handoff:<64-lowercase-hex>
```

The host argv is constructed internally as exactly:

```text
/usr/local/libexec/agent-os-governed-resume \
  --handoff-id executor-handoff:<64-lowercase-hex>
```

There is no API for supplying shell text, an argv list, a prompt, a path, a
package command, a validation command, a branch operation, or environment
variables. The module does not invoke a shell or subprocess.

The fixed host entrypoint must bind the merged #1218 seam:

```text
executor-handoff id
-> GovernedInvocationDescriptor
-> current canonical evidence reacquisition
-> exact source/scope/checkpoint/ResumePlan/environment/runtime checks
-> existing Scheduler lease observation
-> exact current SingleIssuePilotInput OR fail-closed result
```

The transport must not duplicate these checks in workflow YAML or shell logic.

## VM state machine

The pure contract permits:

```text
STOPPED
  -> one start request
  -> one bounded wait/observation
  -> RUNNING

RUNNING
  -> no restart

STAGING / STOPPING / SUSPENDING / UNKNOWN / UNREACHABLE
  -> blocked
  -> no host invocation
```

There is no automatic retry or failover to another VM, Codespace, runner, or
provider.

After RUNNING is proven, one readiness probe must succeed before the fixed host
entrypoint can be invoked.

## Shutdown gate

VM stop is actuation only. It never proves execution termination, lease release,
or cleanup.

Automatic stop is eligible only when host-side canonical evidence proves one of
these bounded cases:

- `succeeded` with termination confirmed, lease released, and cleanup complete;
- `validation-failed` with the same clean terminal proof;
- `blocked-before-execution` with explicit proof that no retained ownership
  remains and cleanup/release are complete.

Shutdown is withheld for retained lease ownership, quarantine,
`termination-uncertain`, cleanup failure, release failure, or any other outcome
without the complete terminal proof. A stop failure becomes `needs-decision`.

This preserves #758/#1202/#759 truth: Actions completion, SSH disconnect, PID
absence, elapsed time, or transport timeout are not termination evidence.

## Adapter boundary

`workflow_scheduler.governance.gce_control_path` is pure and injected. It owns
only validation and deterministic control-path sequencing. A concrete adapter
may later implement the separately authorized Google operations:

- observe instance state;
- start the exact instance;
- wait for RUNNING;
- perform the bounded IAP/OS Login readiness probe;
- invoke the fixed host entrypoint;
- stop the exact instance when the shutdown gate permits it.

The pure module itself imports no Google SDK, GitHub client, network library, or
subprocess package. It creates no credential, IAM binding, queue, daemon,
database, persistent state, lease, or Scheduler execution.

## Bounded result

The control-path result records only bounded transport evidence, including:

- request and handoff identity;
- exact resource tuple;
- initial/final observed VM state;
- whether start/host invocation/stop were issued;
- bounded Scheduler invocation/execution identities returned by the host;
- terminal status and evidence references;
- shutdown eligibility;
- a finite reason-code set.

Authority fields are fixed false. The result does not authorize Scheduler work,
lease operations, GitHub writes, arbitrary commands, or merge.

## Ownership boundaries

- #1203 owns issue-comment parsing, actor admission, and the GitHub workflow.
- #1217 owns the Google identity/VM/IAP/OS Login control path and fixed host
  invocation binding.
- #1218 owns one-ID reconstruction/admission.
- #758 owns Scheduler lease/concurrency truth.
- #1202 owns orphaned/ambiguous lease recovery.
- #759 owns process containment and termination proof.
- #1197 owns dependency readiness.

No second owner is introduced by this module.

## Activation boundary

Repository implementation and offline tests are credential-free. Live
Workload Identity Federation, IAM, OS Login, IAP, VM lifecycle, public-IP/service
account hardening, deployment of the fixed host entrypoint, and the required
live smoke test must run only on a capable execution surface under the explicit
#1203/#1217 excluded-surface authorization.

A repository-only validation pass is not evidence that the external GCP
activation has succeeded.
