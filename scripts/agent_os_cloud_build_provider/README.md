# Agent OS Cloud Build Provider Core

This package defines the pure-local, deterministic contract between existing Agent OS execution evidence and Cloud Build, plus one injected adapter that submits, observes, and reconciles against that contract.
The core (`core.py`, `models.py`) does not call Google Cloud, GitHub, the network, the filesystem, the clock, the environment, subprocesses, credentials, or any external system. All identities, times, authorization evidence, dispatch evidence, and provider observations are supplied explicitly by the caller. The adapter (`adapter.py`, #805) performs no such call itself either: every Cloud Build submission, observation, and reconciliation is delegated to one caller-injected `CloudBuildProviderClient` implementation, never a Google SDK import in this package.

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

`prepare_cloud_build_provider_invocation` (#804) calls the public `validate_validation_command_plan` before touching any command-plan field or deriving an ID: `ValidationCommandPlan` performs no field validation of its own, so an exact-type plan with a malformed field would otherwise reach an unguarded comparison and raise. A malformed plan, or one whose `validation_plan_id` uses neither the standard positive-PR `validation-plan:` schema nor the canonical candidate-bound pre-PR `pre-pr-validation-plan:` schema (#1210), fails closed to a bounded manual-review result instead. `dispatch_identity` is likewise never trusted as supplied: the dispatch-guard boundary independently recomputes it from repository, head SHA, profile, selector version, command-set digest, and validation-plan ID before a decision ID is accepted, so changing `dispatch_identity` and recomputing a self-consistent decision ID around it still fails.

## Pre-PR admission (#1210)

A canonical candidate-bound pre-PR validation plan (`PrePrValidationPlan`, #723/#1030) already converts to the standard `ValidationCommandPlan` transport through `build_validation_command_plan`'s existing pre-PR branch, keyed by its `pre-pr-validation-plan:` validation-plan ID. `prepare_cloud_build_provider_invocation` admits that converted plan through the exact same identity, authorization, and dispatch-eligibility gate used for a positive-PR plan -- it is never treated as its own authority, and no PR number is invented, required, or mutated to make the positive-PR schema fit; the absence of a pull request is represented natively (`DispatchDecision.pull_request=None`, no PR field on `CloudBuildProviderInvocation`).

`evaluate_pre_pr_dispatch_decision` and `pre_pr_validation_dispatch_identity` (`agent_os_remote_validation.dispatch_guard`, #369) are the one narrow additive seam this required: the existing `evaluate_dispatch_decision`/`validation_dispatch_identity` pair is defined over `ValidationPlan`'s mandatory `pull_request`, so a pre-PR-shaped decision needs its own identity/eligibility entry point rather than a weakened positive-PR one. It reuses the same `DispatchDecision` type, the same decision-ID/dispatch-identity hashing, and the same finite `DispatchStatus` vocabulary, and only ever returns `launch-eligible`, `stale-skipped`, or `manual-review` -- dispatch-evidence retry, duplicate, reuse, and supersession tracking remain Workflow Scheduler lifecycle ownership (#330) and stay out of this seam's scope.

A non-candidate-bound (historical) pre-PR subject is not treated as a shortcut: it passes through the identical repository/issue/branch/SHA/scope/approval/projection/implementation-contract/selector/digest/command-identity matching as any other pre-PR or positive-PR plan, so it can only launch when its own contract genuinely and exactly matches the supplied request, authorization, and dispatch evidence.

## Fixed commands only

The provider copies exact `CommandPlanEntry` values from the canonical `ValidationCommandPlan`, which the command-plan validator has already confirmed uses only argv drawn from the existing command registry. It exposes no shell string, shell parser, arbitrary command builder, or caller-supplied argv surface. Each exact entry receives a deterministic domain-separated argv identity, and `CloudBuildProviderInvocation` recomputes that identity from its own `fixed_command_entries` rather than trusting a supplied `fixed_argv_identities` value, so a real entry can never be paired with a forged or stale identity.

## Status and reason vocabulary

Provider result statuses are `accepted`, `skipped`, `manual-review`, `unavailable`, `unknown`, and `terminal`.
Observation statuses are `working`, `success`, `failure`, `timeout`, `cancelled`, `expired`, `internal-error`, `unavailable`, and `unknown`. `expired` is provider-reported queue-expiry terminal evidence, distinct from timeout/failure/cancelled; never infer it from elapsed time; it grants no retry/cancel/readiness/merge/closure/execution/lease authority.
Side-effect states are `none`, `confirmed`, and `unknown`.
Reason codes are finite enum values. Raw exceptions, credentials, provider payloads, unrestricted logs, filesystem paths, and headers are never serialized into public results.

## Ordinary aggregate admission policy (#1233)

GitHub Actions owns the ordinary authoritative exact-final-head aggregate validation lane. Cloud Build therefore does not admit an otherwise-valid ordinary `aggregate` command plan after all existing provider acceptance evidence has validated. The provider returns `status=skipped` with reason `provider.aggregate-redundant-equivalent`, carries no accepted `CloudBuildProviderInvocation`, build ID, tested SHA, or normalized execution evidence, keeps `side_effect_state=none`, and never grants merge authority.

The ordering is deliberate: malformed command plans, identity/SHA drift, invalid or non-launch generic dispatch evidence, inactive/mismatched authorization, and provider-configuration drift keep their existing fail-closed classifications and are not converted into a cost-saving aggregate skip. A valid `focused` plan remains eligible for the existing accepted-invocation behavior.

Issue #369 remains the sole owner of generic launch eligibility, stale-head handling, duplicate/reuse/retry/supersession semantics, and dispatch identity. #1233 adds only this provider-specific admission rule after those generic and provider checks are already satisfied; it does not change validation-plan or command-plan identities/serialization.

Because `CloudBuildProviderAdapter` consumes only an already accepted `CloudBuildProviderInvocation`, a skipped aggregate produces no adapter input and cannot reach the injected `CloudBuildProviderClient.submit` path.

## At-most-once and unknown-outcome behavior

Issue #369 remains the sole owner of launch eligibility, duplicate suppression, stale-head handling, reuse, supersession, and retry recommendation. This package accepts only a verified `launch-eligible` decision with `launch_recommended=true`. Reused, duplicate, stale, non-required, supersede-required, malformed, and manual-review decisions create no invocation.

An unknown provider-side effect is explicit and non-retryable. A retry requires external reconciliation, a fresh exact #369 decision, and therefore a new invocation identity.
Once the observation's identity is safely proven against the invocation, an unknown side-effect state dominates every other status this package could otherwise project: it always yields `status=unknown`, never a `working`/`success`/`failure`/... projection, with no terminal evidence, a single bounded reason, and `merge_authorized=false`. `CloudBuildProviderResult` enforces this and related status/evidence/invocation coherence in its own constructor, so a contradictory result (an `accepted` status carrying build evidence, a `terminal` status without complete evidence, or an `unknown` status without an unknown side-effect state) cannot be constructed directly, not only produced through the normal entry points.

## Terminal evidence

Complete terminal observations are normalized through the existing #685 `CloudBuildResultEvidence` contract. This package does not create a second terminal Cloud Build evidence model and never fabricates a build ID, tested SHA, failed step, exit code, source completeness, or success state.

## Injected adapter (#805)

`CloudBuildProviderAdapter` consumes one exact accepted `CloudBuildProviderInvocation` and an injected `CloudBuildProviderClient` (a small `Protocol` with `submit`, `observe`, and `reconcile` methods only -- no `cancel`). Before any client call it recomputes the invocation's semantic ID and confirms the injected `CloudBuildProviderConfiguration`'s fingerprint matches the one bound into the invocation; a wrong type, a drifted invocation, or a configuration mismatch submits zero times and is projected through `project_cloud_build_provider_result` with `side_effect_state=none`.

- At-most-once submission and identity transport: each adapter instance submits at most once and transports only identities already bound into the invocation and its bound configuration, tagging the request's `provider_metadata` with the invocation ID.
- Bounded polling: a confirmed submission is polled through `observe` for a bounded number of attempts and projected through `project_cloud_build_provider_result`, the same #685-backed projection the core uses. The adapter never sleeps or reads the clock between polls -- the injected client owns pacing between calls.
- `denied` shape and diagnostic/`merge_authorized` guarantees: a clean `denied` outcome is a proven pre-build failure (`side_effect_state=none`, `provider.permission-denied`) that `project_cloud_build_provider_result` cannot itself produce, so the adapter constructs that one result shape directly; every adapter-produced result keeps `merge_authorized=false`, and every private diagnostic exposed on the adapter (`last_diagnostic`, `poll_attempts`) is bounded and control/secret-stripped, with raw exception messages never included, only the exception's type name.
- Reconciliation matching: a raised exception, a malformed response, or an explicit `ambiguous` outcome from `submit` never re-submits; it calls `reconcile` exactly once, and only an exact single matching build ID is trusted -- zero or multiple matches stay `status=unknown`/`side_effect_state=unknown`, which is never automatically retried.

## No-SDK and no-I/O boundary

The pure core performs no network access, filesystem access, environment inspection, clock reads, subprocess execution, dynamic imports, Google SDK use, GitHub client use, credential access, provider calls, persistence, or external writes. Every caller-supplied UTC timestamp, including `CloudBuildProviderObservation.observed_at`, is validated by strict parse-and-round-trip against the canonical format, not by regex shape alone, so a calendar- or clock-impossible value is rejected without ever reading the host clock. The adapter performs no GitHub write, command planning, Workflow Scheduler lifecycle management, deployment, IAM mutation, credential installation, or other workflow operation of its own; it also never reads the host clock, relying instead on client-supplied `observed_at` evidence for every observation it builds.
## Authority boundaries

`execution_authorized=true` records only that the exact supplied execution authorization applied to that exact invocation. Every invocation and result keeps `merge_authorized=false`.
Validation success does not authorize Ready-for-Review, merge, issue closure, protected-setting changes, production use, PR publication, or external writes.

## Related owners

- #330: Workflow Scheduler execution and concurrency governance; #369: dispatch identity and duplicate/stale/retry recommendation
- #520: duration, compute, cost, and concurrency conclusions
- #685: terminal Cloud Build evidence normalization
- #686 and #687: PR reporting and external activation
- #805: injected connected provider adapter (`adapter.py`, this package)
- #806: future external activation
- #803: temporary-gateway retirement after replacement proof
- #1210: candidate-bound pre-PR plan admission through this existing provider path (no second provider, planner, or authorization model)

## Rollback

Remove this package, its focused tests, fixtures, and this README. Existing Execution Service, remote validation, Workflow Scheduler, Cloud Build reporting, GitHub reporting, Cloud resources, and the temporary gateway remain unchanged. Removing only `adapter.py`, its exports, and `test_adapter.py` leaves the pure #804 core intact.
