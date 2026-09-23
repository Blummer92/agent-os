# agent_os_execution_checkpoint

AOS-RESUME1A (#895) plus the AOS-RESUME1B (#1431) canonical construction
boundary. This package owns the pure-local `ExecutionCheckpoint` record,
deterministic construction from canonical evidence, content-addressed append-only
local store, invalidation matrix, and resume planner. A checkpoint records
evidence only and never authorizes the next stage. No subprocess, network,
GitHub, Scheduler, retry, credential, cloud, or host mutation occurs here; only
`store.py` performs bounded local filesystem I/O. Canonical implementation owner:
GitHub Service Agent; QA / Test Agent owns independent validation evidence.

## Public interface

```python
from scripts.agent_os_execution_checkpoint import (
    CanonicalExecutionEvidence, WorktreeEvidence, EnvironmentEvidence,
    DependencyEvidence, AcceptanceCriteriaEvidence, GovernanceContractEvidence,
    StageObservation, construct_execution_checkpoint,
    ExecutionCheckpoint, serialize_checkpoint, deserialize_checkpoint,
    append_checkpoint, load_checkpoints, BindingSnapshot, plan_resume,
)
```

## Construction boundary (`construction.py`)

`construct_execution_checkpoint(...)` accepts bounded evidence objects rather
than caller-selected checkpoint hashes. It derives five #895-owned bindings with
canonical JSON, SHA-256, and fixed domain separation:

- `worktree_fingerprint`: non-host-specific branch/worktree role/source/index-tree/
  working-diff facts; absolute worktree paths are never inputs.
- `environment_fingerprint`: bounded OS/architecture/runtime identities and an
  optional immutable container-image digest; no secrets, mutable handles, or
  absolute paths.
- `dependency_fingerprint`: sorted repository-relative dependency/lock/development
  manifest paths and their already-observed content digests.
- `acceptance_criteria_digest`: ordered canonical issue acceptance criteria with
  deterministic newline/trailing-whitespace normalization and issue binding.
- `governance_contract_digest`: the exact bounded applicable Agent OS governance
  document set, represented by repository-relative paths and canonical git blob
  SHAs rather than arbitrary repository contents.

`merge_base_sha`, `tested_sha`, repository/issue/invocation/execution identity,
branch, worktree role, command-plan identity, and authorization snapshot reference
remain direct observations from their existing owners. The constructor does not
invent them and cannot accept substitutes for the five derived bindings.

Stage selection is evidence-driven. `StageObservation` values must all bind the
same exact `tested_sha`; selecting a later stage requires a complete contiguous
prefix of earlier stage observations. Passed/uncertain mutating stages require a
canonical mutation-intent identity, and passed mutating stages require pre-read
and post-write digests. Missing, contradictory, duplicate, non-contiguous, or
cross-head evidence fails closed before a checkpoint is constructed.

The #1210/PR #1429 Cloud Build Provider work is **not** a #1239 execution
specimen. It may inform fixture shape only. No #1239 checkpoint may be built until
#1239's own canonical invocation/execution/worktree/dependency/test evidence
exists. In particular, a later merge fact never retroactively changes the exact
head that was actually tested.

## Field-source classification

- Direct canonical source: repository, issue, invocation/execution IDs, branch,
  worktree role, source/tested/merge-base SHAs, command-plan ID, authorization
  snapshot reference.
- Canonical deterministic derivation: the five fingerprints/digests above.
- Observational provenance: `recorded_at`, `actor_id`, `diagnostic_refs`.
- Stage-dependent nullable: parent checkpoint, mutation intent, pre/post digests,
  evidence hashes, supersession state.
- Fail closed when unavailable: any required direct identity/SHA/plan fact, any
  required derivation input, or any mutation evidence required by the selected
  stage.

## Record schema (`models.py`)

`ExecutionCheckpoint` remains frozen at
`schema=agent-os.execution-checkpoint`, `v1.0`. #1431 does not change its schema,
store, identity, invalidation, ResumePlan, or authority semantics. The six
authority fields remain hardcoded `False`.

## Identity (`identity.py`)

Byte-exact canonical JSON follows ADR-0002 details-01b
(`sort_keys=True, separators=(",", ":"), ensure_ascii=False`). Semantic
checkpoint identity excludes only observational `recorded_at`, `actor_id`, and
`diagnostic_refs`. `reuse_key` excludes invocation/execution IDs so equivalent
evidence from separate invocations can be recognized as interchangeable.

## Storage (`store.py`)

Intended root: `$(git rev-parse --git-common-dir)/agent-os-checkpoints/`, resolved
by the caller because this package never shells out. `append_checkpoint(...)`
remains the only append boundary; construction performs no persistence.
Content-addressed immutable checkpoint files, reconstructable `HEAD`, quarantine,
retention, capacity, and chain-integrity behavior are unchanged.

## Invalidation matrix (`invalidation.py`)

The existing 15-trigger `TRIGGER_STAGES` matrix remains canonical. The new
constructor feeds its existing `BindingSnapshot` fields; it does not reinterpret
invalidation. Acceptance/governance changes invalidate all stages; dependency,
environment, worktree, branch, command-plan, merge-base, PR/CI/review/lifecycle
rules remain exactly as #895 defines them. Authorization changes invalidate no
evidence.

## Resume planner (`resume_planner.py`)

`plan_resume(...)` remains unchanged and returns evidence only. All six authority
fields remain `False`; operating-mode decisions continue to supply the authority
ceiling externally. #1431 adds no Scheduler, currentness engine, retry loop,
publication path, or alternate ResumePlan.

## Mutation safety (`mutation_intent.py`)

`compute_mutation_intent_id(...)` remains canonical. An uncertain mutation is
manual-review evidence, never permission for blind retry. #1431 only requires the
existing mutation evidence when constructing a mutating checkpoint stage.

## Authority boundary and rollback

Construction creates no checkpoint persistence, producer execution, publication,
Scheduler invocation, discovery, resume, replay, GitHub write, cloud action, or
external write. Revert `construction.py`, its tests/exports, and this README
update to remove #1431 without changing the v1.0 checkpoint/store/resume contract.
