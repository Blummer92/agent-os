# GCE Control Path — #1217

## Purpose
#1217 owns the smallest governed GCE transport/VM-actuation contract used by #1203. It does not own Scheduler admission, execution authorization, lease truth, retry, provider selection, publication, or repository writes.

```text
GitHub OIDC -> Google WIF -> dedicated transport service account
-> exact GCE tuple -> start-if-stopped / observe-running -> IAP + OS Login
-> fixed host entrypoint + one executor-handoff id -> #1218 reconstruction
-> existing Workflow Scheduler -> bounded evidence -> evidence-gated VM stop
```

## Frozen resource and trust envelope
The v1 target is `agent-os-502614 / us-central1-a / agent-os-test`. Any other tuple is rejected before adapter effects.

OIDC admission requires exact repository, repository owner, `workflow_ref`, `refs/heads/main`, and configured Workload Identity Provider audience. #1203 separately owns comment-actor admission and Agent OS authorization reacquisition; matching OIDC claims never create execution authority. No service-account JSON key, SSH private key, or other long-lived credential belongs in this contract.

## Fixed host invocation
The only caller-controlled execution datum is `executor-handoff:<64-lowercase-hex>`. Host argv is constructed internally as exactly:

```text
/usr/local/libexec/agent-os-governed-resume --handoff-id executor-handoff:<64-lowercase-hex>
```

There is no API for caller shell text, argv lists, prompts, paths, package/test commands, branch operations, or environment payloads. The transport must bind the merged #1218 seam rather than duplicate it:

```text
handoff id -> GovernedInvocationDescriptor -> current evidence reacquisition
-> source/scope/checkpoint/ResumePlan/environment/runtime checks
-> existing Scheduler lease observation
-> exact current SingleIssuePilotInput OR fail-closed result
```

## VM state machine
```text
STOPPED -> one start -> one bounded wait -> RUNNING
RUNNING -> no restart
STAGING / STOPPING / SUSPENDING / UNKNOWN / UNREACHABLE -> blocked
```

There is no automatic retry or fallback. One readiness probe must succeed before the fixed host entrypoint is invoked.

## Shutdown gate
VM stop is actuation only; it never proves termination, lease release, or cleanup. Automatic stop is eligible only for `succeeded` or `validation-failed` with confirmed termination + lease release + cleanup, or `blocked-before-execution` with explicit proof that no retained ownership remains and release/cleanup are complete.

Shutdown is withheld for retained lease ownership, quarantine, `termination-uncertain`, cleanup failure, release failure, or any outcome lacking complete terminal proof. Stop failure becomes `needs-decision`. Actions completion, SSH disconnect, PID absence, elapsed time, or transport timeout are not termination evidence.

## Pure adapter boundary
`workflow_scheduler.governance.gce_control_path` owns validation and deterministic sequencing only. A separately authorized concrete adapter may observe/start/wait for the exact VM, perform bounded IAP/OS Login readiness, invoke the fixed host entrypoint, and stop the exact VM when the shutdown gate permits it.

The pure module imports no Google SDK, GitHub client, network library, or subprocess package. It creates no credential, IAM binding, queue, daemon, database, persistent state, lease, Scheduler execution, or retry system.

## Bounded result
The result carries bounded request/handoff identity, exact resource tuple, initial/final VM state, start/invoke/stop observations, bounded Scheduler invocation/execution identities returned by the host, terminal status/evidence references, shutdown eligibility, and finite reason codes. Authority fields are fixed false: the result cannot authorize Scheduler work, lease operations, GitHub writes, arbitrary commands, or merge.

## Ownership
- #1203: issue-comment parsing, actor admission, GitHub workflow.
- #1217: Google identity/VM/IAP/OS Login control path and fixed host binding.
- #1218: one-ID reconstruction/admission.
- #758: Scheduler lease/concurrency truth.
- #1202: orphaned/ambiguous lease recovery.
- #759: containment and termination proof.
- #1197: dependency readiness.

## Activation boundary
Repository code/tests are credential-free. Live WIF/IAM, OS Login, IAP, VM lifecycle, public-IP/service-account hardening, fixed-entrypoint deployment, and the required live smoke test must run only on a capable governed GCP surface under the existing explicit #1203/#1217 excluded-surface authorization. Repository validation alone is not evidence that external GCP activation succeeded.
