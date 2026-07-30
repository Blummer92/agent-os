# Agent OS Cloud Build Provider Contract

This package is the pure-local CBP2 boundary selected by #802 and implemented by #804.

It consumes exact, caller-supplied Agent OS contracts: `ExecutionServiceRequest`, `ValidationCommandPlan`, `DispatchDecision`, `ExecutionAuthorizationEvidence`, exact resolved SHA, and immutable provider configuration. It produces a deterministic provider invocation or a bounded fail-closed result. Terminal observations are normalized through the existing #685 Cloud Build evidence contract.

## Import direction

`agent_os_cloud_build_provider` may import Execution Service, remote-validation dispatch, and Cloud Build reporting contracts. Those packages and Workflow Scheduler must not import this provider package.

## Authority

An accepted invocation proves only that the supplied request, command plan, dispatch recommendation, authorization, SHA, commands, and provider configuration matched. It does not execute a build. It never authorizes review, readiness, issue completion, merge, protected settings, deployment, or production.

## At-most-once and unknown outcomes

#369 remains the launch, duplicate, stale, reuse, supersede, and retry-recommendation owner. One invocation identity includes one exact dispatch-decision identity. An unknown provider-side effect is explicit and non-retryable until external reconciliation and a fresh dispatch decision.

## I/O boundary

The package performs no network, filesystem, environment, clock, subprocess, credential, GitHub, Google Cloud SDK, or external-system operation. Caller-supplied canonical UTC timestamps are used for authorization checks.

## Rollback

Remove this package and its focused tests. Existing Execution Service, Workflow Scheduler, remote validation, Cloud Build reporting, GitHub reporting, and Cloud resources remain unchanged.
