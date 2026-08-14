# Agent OS Execution Service — contract 0.5.0

This package separates pure-local planning and evidence contracts from the
existing governed validation-execution composition surface.

## Authority boundary

Pure-local surfaces validate requests, inspect supplied repository snapshots,
project results, serialize evidence, build validation command plans, and select
executor routes. They do not run commands, mutate repositories, dispatch a
runtime, or authorize work.

The execution-composition surface introduced under Issue #697 can delegate
validation exactly once to the canonical Workflow Scheduler only after separate
request, command-plan, authorization, and runtime-configuration checks pass.
Route selection never satisfies those preconditions.

Execution authorization, route selection, command execution, validation success,
Ready for Review, and merge authorization remain separate states.

## Authorized-validation admission — Issue #757

`authorized_validation.py` is the pure security checkpoint between a complete
non-authorizing candidate packet plus separately supplied human execution
authorization and later runtime-capable lifecycle stages.

The request deliberately binds canonical roots rather than flattening and
re-owning their schemas: the exact `CandidatePacket`, approval/projection stage,
execution-packet stage, `ExecutionAuthorizationEvidence`, and one versioned
lifecycle-policy profile. Admission re-runs each owning module's canonical
transport/identity checks and then verifies the cross-bindings for repository,
issue, invocation, SHAs, approval/projection, validation plan, command plan,
request, runtime configuration, scope, tests, argv, timeouts, output bounds, and
expected changed paths.

The existing `ExecutionAuthorizationEvidence` does not itself carry candidate
packet, invocation, permitted-operation, or authorizer fields. #757 therefore
binds those values in the content-addressed lifecycle request without changing or
replacing the canonical authorization model. This prevents an otherwise valid
authorization from being replayed against another candidate packet, invocation,
or operation. The only admitted operation in this contract is
`validation-only`; requested concurrency is exactly `1` and automatic retry is
always false.

Admission statuses are finite: `accepted`, `blocked`, `stale`,
`needs-decision`, and `invalid`. Unknown schema fields/versions, malformed or
noncanonical evidence, identity drift, expired/not-yet-active authorization, and
unsupported policy authority fail closed. An `accepted` result remains
non-authorizing evidence (`execution_authorized=false`) and is not a reusable
bearer capability. The end-to-end lifecycle owner must revalidate the exact
request/admission binding and required currentness immediately before its first
separately authorized side effect.

Construction, serialization, reconstruction, and admission verification perform
no lease acquisition, worktree creation, process execution, Git mutation,
network access, provider invocation, credential access, workflow dispatch,
publication, retry, or external write.

## Public capabilities
- `inspect_repository`
- `verify_repository_state`
- canonical `ExecutionServiceRequest` serialization/reconstruction
- deterministic validation command planning
- deterministic executor routing and immutable handoff construction
- pure authorized-validation lifecycle request construction and admission
  verification

An accepted request, command plan, route decision, handoff, or #757 admission is
evidence only. It does not authorize edits, commands, pushes, review readiness,
merge, deployment, or external mutation.

## Executor routing — Issue #918

Executable-lane selection decides **what work may proceed**. Executor routing
decides only **which execution surface receives already-approved work**.

Routes, in deterministic precedence order:

1. `human-decision-required` for any ambiguity, excluded surface, stale or
   contradictory evidence, or irreversible/uncertain mutation.
2. `chatgpt-connector-native` when no runtime capability is required.
3. `chatgpt-governed-runner` when available and capable.
4. `external-coding-agent-fallback` only when the runner is unavailable or
   insufficient and fallback is both available and explicitly permitted.
5. `human-decision-required` when no capable approved route remains.

The routing-only `ExecutorCapability` vocabulary is closed:
`checkout`, `isolated-worktree`, `dependency-installation`,
`process-execution`, `compile-or-lint`, `test-execution`,
`runtime-inspection`, `generated-artifact-inspection`,
`multi-file-implementation`, `git-reconciliation`,
`exact-head-validation`, and `checkpointed-resume`.

The two immutable core models are `ExecutorRouteDecision` and
`ExecutorHandoff`. Existing request, authorization, validation-plan,
operating-mode, lane-selection, repository-state, worktree, package,
environment, checkpoint, resume, and Workflow Scheduler evidence is referenced
only through bounded opaque identities. Semantic validation remains with each
canonical owner.

Route selection never creates or widens authority. Direct and deserialized
handoffs require an authorization identity whenever authority is present, and
checkpointed-resume handoffs require both checkpoint and resume-plan identities.
The router reads no host clock and performs no filesystem, subprocess, network,
GitHub, workflow, credential, provider, runner, persistence, production, retry,
or external-system operation.

The complete frozen contract and stop conditions are in Issue #918.

## Existing request, planning, and inspection contracts

`ExecutionServiceRequest` and `ExecutionServiceResult` remain frozen, bounded,
strictly typed, canonically serialized, and content-addressed. The caller
supplies `evaluated_at`; the service never reads the host clock. The public
request serializer/reconstructor preserves constructor-owned validation and
fingerprint semantics.

Validation command planning maps only registered command strings to fixed argv.
It performs no shell parsing, alias expansion, user-supplied argv execution,
network access, persistence, retry, or runtime dispatch.

`RepositoryInspector` is injected and invoked at most once after validation.
Repository-state verification delegates only canonical evidence to the existing
validator. Private evidence is excluded from public projections.

## Validation
From the repository root:

```bash
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests/test_authorized_validation.py
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests/test_executor_routing.py
PYTHONPATH=08_Tooling/agent-os-execution-service/src python -m pytest -q \
  08_Tooling/agent-os-execution-service/tests
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
git diff --check
```

## Rollback

Revert the Issue #757 verifier, lazy exports, focused tests, and this README
section to remove the admission capability. No runtime, repository, lease,
worktree, process, or external state requires cleanup.
