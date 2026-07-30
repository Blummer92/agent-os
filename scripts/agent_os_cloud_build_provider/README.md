# Agent OS Cloud Build Provider Core

This package defines the pure-local, deterministic contract between existing Agent OS execution evidence and a future connected Cloud Build adapter.

It does not call Google Cloud, GitHub, the network, the filesystem, the clock, the environment, subprocesses, credentials, or any external system. All identities, times, authorization evidence, dispatch evidence, and provider observations are supplied explicitly by the caller.

## Placement and dependency direction

Canonical placement:

```text
scripts/agent_os_cloud_build_provider/
```

Allowed imports:

```text
agent_os_cloud_build_provider
  -> agent_os_execution_service
  -> scripts.agent_os_remote_validation
  -> scripts.agent_os_cloud_build_reporting
```

Upstream packages must never import this provider package. Workflow Scheduler remains the local lifecycle owner and is not imported here.

## Public inputs and outputs

`prepare_cloud_build_provider_invocation` consumes exact immutable `ExecutionServiceRequest`, `ValidationCommandPlan`, `DispatchDecision`, `ExecutionAuthorizationEvidence`, and `CloudBuildProviderConfiguration` values plus a caller-supplied resolved SHA and evaluation timestamp. It returns one accepted immutable invocation or a bounded fail-closed result.

`project_cloud_build_provider_result` consumes one accepted invocation and one caller-supplied observation. It projects working, unavailable, unknown, or terminal provider evidence without performing reconciliation or a provider call.

An issue number, branch name, profile, previous success, build ID, or gateway request never independently authorizes launch.

## Identity and authorization matrix

An accepted invocation requires agreement across repository, requested ref, expected SHA, resolved SHA, request fingerprint and revision, validation-plan ID, command-plan ID, dispatch decision ID and identity, authorization ID and active interval, profile, selector version, command-set digest, ordered fixed argv, and provider-configuration fingerprint.

The resolved SHA must equal the expected SHA before invocation acceptance.

## Fixed commands only

The provider copies exact `CommandPlanEntry` values from the canonical `ValidationCommandPlan`. It exposes no shell string, shell parser, arbitrary command builder, or caller-supplied argv surface. Each exact entry receives a deterministic domain-separated argv identity.

## Status and reason vocabulary

Provider result statuses are `accepted`, `skipped`, `manual-review`, `unavailable`, `unknown`, and `terminal`.

Observation statuses are `working`, `success`, `failure`, `timeout`, `cancelled`, `internal-error`, `unavailable`, and `unknown`.

Side-effect states are `none`, `confirmed`, and `unknown`.

Reason codes are finite enum values. Raw exceptions, credentials, provider payloads, unrestricted logs, filesystem paths, and headers are never serialized into public results.

## At-most-once and unknown-outcome behavior

Issue #369 remains the sole owner of launch eligibility, duplicate suppression, stale-head handling, reuse, supersession, and retry recommendation. This package accepts only a verified `launch-eligible` decision with `launch_recommended=true`. Reused, duplicate, stale, non-required, supersede-required, malformed, and manual-review decisions create no invocation.

An unknown provider-side effect is explicit and non-retryable. A retry requires external reconciliation, a fresh exact #369 decision, and therefore a new invocation identity.

## Terminal evidence

Complete terminal observations are normalized through the existing #685 `CloudBuildResultEvidence` contract. This package does not create a second terminal Cloud Build evidence model and never fabricates a build ID, tested SHA, failed step, exit code, source completeness, or success state.

## No-SDK and no-I/O boundary

The pure core performs no network access, filesystem access, environment inspection, clock reads, subprocess execution, dynamic imports, Google SDK use, GitHub client use, credential access, provider calls, persistence, or external writes.

## Authority boundaries

`execution_authorized=true` records only that the exact supplied execution authorization applied to that exact invocation. Every invocation and result keeps `merge_authorized=false`.

Validation success does not authorize Ready-for-Review, merge, issue closure, protected-setting changes, production use, PR publication, or external writes.

## Related owners

- #330: Workflow Scheduler execution and concurrency governance
- #369: dispatch identity and duplicate/stale/retry recommendation
- #520: duration, compute, cost, and concurrency conclusions
- #685: terminal Cloud Build evidence normalization
- #686 and #687: PR reporting and external activation
- #805: future injected connected provider adapter
- #806: future external activation
- #803: temporary-gateway retirement after replacement proof

## Rollback

Remove this package, its focused tests, fixtures, and this README. Existing Execution Service, remote validation, Workflow Scheduler, Cloud Build reporting, GitHub reporting, Cloud resources, and the temporary gateway remain unchanged.
