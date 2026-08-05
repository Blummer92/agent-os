# agent_os_execution_checkpoint

AOS-RESUME1A (#895), implementing the design approved for #858. Pure-local
`ExecutionCheckpoint` record, content-addressed identity, append-only
local store, and a resume planner -- a checkpoint records evidence only
and never authorizes the next stage. No subprocess, network, GitHub,
Scheduler, retry, or credential access anywhere; only local filesystem
I/O in `store.py`. Owner: Integration Manager / GitHub Service Agent.

## Public interface

```python
from scripts.agent_os_execution_checkpoint import (
    ExecutionCheckpoint, serialize_checkpoint, deserialize_checkpoint,
    append_checkpoint, load_checkpoints, BindingSnapshot, plan_resume,
)
```

## Record schema (`models.py`)

`ExecutionCheckpoint` (frozen, `schema=agent-os.execution-checkpoint`, `v1.0`):
Identity (`checkpoint_id`, `parent_checkpoint_id`, `reuse_key`); Binding
(`repository`, `issue_number`, `invocation_id`, `execution_id`, `branch`,
`worktree_fingerprint`/`worktree_role`, `environment_fingerprint`,
`source_sha`/`tested_sha`/`merge_base_sha`, `dependency_fingerprint`,
`command_plan_id`, `acceptance_criteria_digest`, `governance_contract_digest`);
Stage (`lifecycle_stage`, `checkpoint_stage`, `stage_status`); Evidence
(`evidence_hashes`, `pre_read_digest`, `post_write_digest`,
`mutation_intent_id`); six `False` authority fields; State
(`invalidation_state`, `supersession_state`, `lifecycle_state`); Provenance
(`recorded_at`, `actor_id`, `diagnostic_refs`, bounded). No secrets or
unbounded logs -- enforced by validation, not convention.

## Identity (`identity.py`)

Byte-exact canonical JSON, reused verbatim from ADR-0002 details-01b
(`sort_keys=True, separators=(",", ":"), ensure_ascii=False`). SHA-256,
domain-separated (`agent-os.execution-checkpoint:<hex>`). Semantic identity
covers every Binding/Stage/Evidence/State field, including `lifecycle_state`;
`recorded_at`, `actor_id`, and `diagnostic_refs` are **observational only** and
excluded (mirrors ADR-0002 details-02's timestamp-semantics rule). `reuse_key` excludes
`invocation_id`/`execution_id`, so identical evidence from separate
invocations is recognized as interchangeable.

## Storage (`store.py`)

Intended root: `$(git rev-parse --git-common-dir)/agent-os-checkpoints/`,
caller-resolved since this package never shells out to `git`. Layout:
`issue-<n>/checkpoints/<hex>.json` (immutable), `issue-<n>/HEAD` (a
reconstructable pointer, never authoritative), `issue-<n>/quarantine/`
(additive facts; originals are never deleted). Atomic temp-then-rename
writes; a content-addressed path holding different bytes than expected
raises `CheckpointStoreIntegrityConflict`. Nothing is ever committed.
Retention: 30 days post-terminal, 14 otherwise (`retention_cutoff_epoch_seconds`).
Caps: 512 records / 32 MiB per issue, refused rather than auto-pruned.
`load_checkpoints` recomputes every id, quarantining (never raising for)
a mismatch or descendant chain.

## Invalidation matrix (`invalidation.py`)

`TRIGGER_STAGES` (15 triggers) is the single source of truth;
`STAGE_INVALIDATION_TRIGGERS` is its inversion, so the two views cannot
drift apart. `AUTHORIZATION_CHANGED` maps to the empty set for every
stage: structural proof an authorization change invalidates zero
evidence. `source-sha`/`acceptance-criteria`/`governance-contract` changes
invalidate all 11 stages; `tested-sha-differs`/`dependency`/`environment`/
`command-plan-id` changes (the last folds "required validation changed")
invalidate only the two validation stages; `worktree` adds
`implementation-complete`/`committed`; `branch` invalidates `committed`
through `issue-closed`; `pr-head`/`ci-result`/`review-feedback`/
`merge-base`/external-lifecycle changes invalidate their specific
`draft-pr`/`review`/`merged`/`closed`-stage counterparts only.

## Resume planner (`resume_planner.py`)

`plan_resume(...)` returns one immutable `ResumePlan`; all six authority
fields are `False` -- a plan is evidence, never permission. Per-stage
classification: `reusable`, `rerun-required`, `blocked`, `manual-review`,
`quarantined`, `superseded`, `complete-but-unauthorized-to-continue`. An
unavailable store forces read-only stages to `rerun-required` and mutating
stages to `manual-review`. Authority gating is fully delegated to a
caller-supplied `AgentOperatingModeDecision` (#863) via
`authority_ceiling_from_decision`/`authority_permits_stage`; this module
never re-derives authorization. `resume_point` is the earliest non-reusable
stage; `None` only when every stage is reusable.

## Mutation safety (`mutation_intent.py`)

`compute_mutation_intent_id(...)` is stable across retries of the same
intent, different for different content. An uncertain outcome always
classifies `manual-review`, never a blind retry. Zero matches on a
stable-key re-read proves an operation did not take effect, so a fresh
attempt is new, not a retry; unprovable state goes to manual review.

## Authority boundary and rollback

Every checkpoint and resume plan carries six hardcoded-`False` authority
fields; no mutation is executed here. Revert only this package's files,
tests, README, and the changelog/module-version-map entries.
