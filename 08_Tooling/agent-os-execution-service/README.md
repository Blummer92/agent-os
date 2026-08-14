# Agent OS Execution Service — contract 0.5.0

This package separates pure-local planning and evidence contracts from the governed validation-execution composition surface.

## Authority boundary

Pure-local surfaces validate requests, inspect supplied repository snapshots, project results, serialize evidence, build validation command plans, and select executor routes. They do not run commands, mutate repositories, dispatch a runtime, or authorize work.

The Issue #697 execution-composition surface may delegate validation exactly once to the canonical Workflow Scheduler only after request, command-plan, authorization, and runtime-configuration checks pass. Route selection never satisfies those preconditions. Execution authorization, routing, command execution, validation success, Ready for Review, and merge authorization remain separate states.

## Authorized-validation admission — Issue #757

`authorized_validation.py` is the pure security checkpoint between a complete non-authorizing candidate packet plus separately supplied human execution authorization and later runtime-capable lifecycle stages.

The lifecycle request binds canonical roots rather than flattening their schemas: the exact `CandidatePacket`, approval/projection stage, execution-packet stage, `ExecutionAuthorizationEvidence`, and a versioned lifecycle-policy profile. Admission reuses each owning module's canonical transport/identity checks, then verifies repository, issue, invocation, SHA, approval/projection, validation-plan, command-plan, request, runtime, scope, tests, argv, timeout/output, and expected-changed-path bindings.

Because `ExecutionAuthorizationEvidence` does not carry candidate-packet, invocation, permitted-operation, or authorizer fields, #757 binds those values in the content-addressed lifecycle request without replacing the canonical authorization model. This prevents replay across candidate packets, invocations, or operations. The only permitted operation is `validation-only`; concurrency is exactly `1`; automatic retry is false.

Admission statuses are `accepted`, `blocked`, `stale`, `needs-decision`, and `invalid`. Unknown fields/versions, malformed or noncanonical evidence, identity drift, invalid authorization windows, and unsupported policy authority fail closed. `accepted` remains non-authorizing evidence (`execution_authorized=false`), not a reusable bearer capability. Downstream lifecycle owners must revalidate currentness immediately before any separately authorized side effect.

Construction, serialization, reconstruction, and admission verification perform no lease acquisition, worktree creation, process execution, Git mutation, network/provider/credential access, workflow dispatch, publication, retry, or external write.

## Public capabilities

- `inspect_repository`
- `verify_repository_state`
- canonical `ExecutionServiceRequest` serialization/reconstruction
- deterministic validation command planning
- deterministic executor routing and immutable handoff construction
- pure authorized-validation lifecycle request construction and admission verification

Accepted requests, plans, routes, handoffs, and #757 admissions are evidence only; they do not authorize edits, commands, pushes, review readiness, merge, deployment, or external mutation.

## Executor routing — Issue #918

Executable-lane selection decides what work may proceed; executor routing decides only which execution surface receives already-approved work.

Deterministic route precedence:
1. `human-decision-required` for ambiguity, excluded surfaces, stale/contradictory evidence, or irreversible/uncertain mutation.
2. `chatgpt-connector-native` when no runtime capability is required.
3. `chatgpt-governed-runner` when available and capable.
4. `external-coding-agent-fallback` only when fallback is available, capable, and explicitly permitted.
5. `human-decision-required` when no approved capable route remains.

The routing-only `ExecutorCapability` vocabulary is closed: `checkout`, `isolated-worktree`, `dependency-installation`, `process-execution`, `compile-or-lint`, `test-execution`, `runtime-inspection`, `generated-artifact-inspection`, `multi-file-implementation`, `git-reconciliation`, `exact-head-validation`, and `checkpointed-resume`.

`ExecutorRouteDecision` and `ExecutorHandoff` reference existing request, authorization, validation-plan, operating-mode, lane-selection, repository-state, worktree, package, environment, checkpoint, resume, and Workflow Scheduler evidence only through bounded opaque identities. Semantic validation remains with each canonical owner.

Routing never creates or widens authority. The router reads no host clock and performs no filesystem, subprocess, network, GitHub, workflow, credential, provider, runner, persistence, production, retry, or external-system operation. The complete frozen contract and stop conditions remain in Issue #918.

## Existing request, planning, and inspection contracts

`ExecutionServiceRequest` and `ExecutionServiceResult` remain frozen, bounded, strictly typed, canonically serialized, and content-addressed. The caller supplies `evaluated_at`; the service never reads the host clock.

Validation command planning maps only registered command strings to fixed argv and performs no shell parsing, alias expansion, user-supplied argv execution, network access, persistence, retry, or runtime dispatch.

`RepositoryInspector` is injected and invoked at most once after validation. Repository-state verification delegates only canonical evidence to the existing validator; private evidence is excluded from public projections.

## Validation

From the repository root:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests/test_authorized_validation.py \
  08_Tooling/agent-os-execution-service/tests/test_executor_routing.py
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
git diff --check
```

## Rollback

Revert the #757 verifier, lazy exports, focused tests, and this README section. No runtime, repository, lease, worktree, process, or external state requires cleanup.
