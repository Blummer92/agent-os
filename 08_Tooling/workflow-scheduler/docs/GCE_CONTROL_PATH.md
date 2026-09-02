# GCE Control Path — #1217

## Purpose
#1217 owns the smallest governed GCE transport/VM-actuation contract used by #1203. It does not own Scheduler admission, execution authorization, lease truth, retry, provider selection, publication, or repository writes.

```text
GitHub OIDC -> Google WIF -> dedicated transport service account
-> exact GCE tuple -> start-if-stopped / observe-running -> IAP + OS Login
-> fixed host entrypoint + one executor-handoff id -> #1218 reconstruction
-> existing Workflow Scheduler -> bounded evidence
```

## Frozen resource and trust envelope
The v1 target is `agent-os-502614 / us-central1-a / agent-os-test`. Any other tuple is rejected before adapter effects.

The activated cloud identity reuses the existing `agent-os-github` Workload Identity Pool, `agent-os-main` provider, and `agent-os-transport@agent-os-502614.iam.gserviceaccount.com`. The provider is restricted to GitHub repository ID `1289370915`, repository-owner ID `32861845`, `issue_comment`, `refs/heads/main`, and the exact `agent-os-governed-invocation.yml@refs/heads/main` workflow reference. No service-account JSON key or persistent SSH private key is used.

The transport custom role is intentionally limited to `compute.instances.get`, `compute.instances.start`, and `compute.projects.get`. IAP tunnel access is conditioned to destination port 22 and OS Login is granted on `agent-os-test` only. The first activation deliberately has no `compute.instances.stop` authority.

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
STOPPED -> one start -> bounded state observation -> RUNNING
RUNNING -> no restart
STAGING / STOPPING / SUSPENDING / UNKNOWN / UNREACHABLE -> blocked
```

There is no invocation retry or provider fallback. Bounded polling observes a VM start already issued by the one control attempt; it does not create another execution attempt. One IAP/OS Login readiness probe must succeed before the fixed host entrypoint is invoked.

## First-activation shutdown rule
The pure control contract retains the future evidence-gated shutdown model, but the concrete first-activation adapter implements `stop()` as a fail-closed no-op and the transport IAM role has no `compute.instances.stop` permission. Therefore the first live qualification can authenticate, observe, start if stopped, connect, invoke, and return evidence, but it cannot stop the VM.

Automatic shutdown remains a later separately reviewed hardening step after end-to-end terminal, lease-release, containment, and cleanup evidence is proven live. Actions completion, SSH disconnect, PID absence, elapsed time, or transport timeout are never termination evidence.

## Concrete gcloud/IAP adapter
`workflow_scheduler.governance.gce_gcloud_adapter` is the only concrete external-effect adapter for this activation. It:

- accepts only the frozen GCE tuple;
- uses `gcloud compute instances describe/start` for bounded VM control;
- uses `gcloud compute ssh --tunnel-through-iap` for readiness and invocation;
- probes only the fixed executable path;
- accepts only the fixed three-element argv produced by `gce_control_path`;
- parses bounded JSON host evidence into `HostInvocationEvidence`;
- has no automatic invocation retry and no VM-stop command surface.

The pure `gce_control_path` remains the deterministic sequencing and policy boundary; the concrete adapter does not acquire leases or decide Scheduler admission.

## GitHub workflow activation
`.github/workflows/agent-os-governed-invocation.yml` remains #1203's bounded issue-comment ingress and now adds only the separately authorized #1217 transport activation:

```text
accepted ingress
-> id-token: write
-> google-github-actions/auth using agent-os-main + agent-os-transport
-> setup-gcloud
-> gce_gcloud_adapter
-> bounded JSON artifact + step summary
```

The workflow has only `contents: read` and `id-token: write`. GitHub Actions concurrency is transport noise reduction only; deterministic handoff/control-request identity plus the existing Scheduler lease remain the execution/idempotency authority.

### Developer-validation outcome semantics

For an accepted developer-validation envelope, transport success and validation success are separate evidence dimensions:

```text
transport-success != validation-success
```

The workflow summary reports the developer-validation status, reason codes, exact tested SHA, validation identity, exit code, and cleanup state from the bounded result. A dedicated fail-closed developer-validation gate then evaluates that evidence against the accepted transport envelope. Only `status=success` with the exact requested branch/SHA/validation identity, `exit_code=0`, and `cleanup_complete=true` satisfies the developer-validation gate. `failure`, `timeout`, `needs-decision`, malformed/missing result evidence, identity drift, nonzero success exit codes, or incomplete cleanup fail the workflow gate while preserving transport evidence for diagnosis.

This gate does not turn transport into validation authority and does not grant Ready-for-Review, merge, issue-closure, Scheduler, production, repository-write, or external-write authority. Non-developer-validation ingress remains unaffected.

### Reusable governed validation profiles

DEVVAL5 (#1566) replaces one-off validation-id growth with a main-owned finite profile catalog. A caller may provide only repository, issue, non-protected `agent/*` branch, exact SHA, and a canonical profile identity. The profile catalog owns runner kind, fixed targets, fixed working directory, runtime identity, timeout class, and selector-requirement binding. Trusted code constructs argv; caller-supplied paths, modules, scripts, environment, cwd, package-install commands, and shell text remain unavailable.

Initial reusable package profiles are `pr-remediation`, `workflow-scheduler`, and `issue-acceptance`. Existing identities remain stable compatibility aliases for `remote-validation`, `instructional-materials-current-curriculum`, `picture-perfect`, and `semantic-ownership-advisory`. The selector projection consumes already-selected canonical validation requirement names; it does not rematch changed paths and never executes selector command strings.

A profile added on a feature branch is not executable merely because it exists on that branch. The executable trust rule remains **main-owned profiles only**: a new profile must first merge canonically before a consumer branch may rely on it. The repository contract does not claim network isolation of branch-owned test code; no IAM, WIF, VM, OS Login, credential, or network-sandbox change is introduced by DEVVAL5.

## Bounded result
The result carries bounded request/handoff identity, exact resource tuple, start/invoke observations, bounded Scheduler invocation/execution identities returned by the host, terminal status, and finite reason codes. Authority fields remain false: transport evidence cannot authorize Scheduler work, lease operations, GitHub writes, readiness, merge, or issue closure.

## Ownership
- #1203: issue-comment parsing, actor admission, GitHub workflow.
- #1217: Google identity/VM/IAP/OS Login control path and fixed host binding.
- #1218: one-ID reconstruction/admission.
- #758: Scheduler lease/concurrency truth.
- #1202: orphaned/ambiguous lease recovery.
- #759: containment and termination proof.
- #1197: dependency readiness.

## Live smoke gate
Do not perform the live smoke test until focused offline validation and repository aggregate validation are green on the implementation head. The smoke test must use one pre-existing authorized `ExecutorHandoff`, invoke the fixed entrypoint once, then replay the same logical request once to prove no second Scheduler execution is created. The VM remains running after first qualification.

## Rollback
Repository rollback reverts the workflow, concrete adapter, tests, and this runbook update. Cloud rollback removes only the #1217 WIF/IAM/IAP/OS Login/firewall bindings that were explicitly created or changed for this path. Durable Scheduler execution records, ResumePlans, ExecutorHandoffs, checkpoints, lease history, validation evidence, branches, and PR history are never rollback targets.
