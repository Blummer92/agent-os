"""Dependency-directed invalidation matrix for execution checkpoints.

Pure, structural, and mechanical: this module compares supplied binding
snapshots and evidence digests, it never interprets issue prose, review
text, or authorization intent. Notably, ``AUTHORIZATION_CHANGED`` exists in
``InvalidationTrigger`` purely to prove -- structurally, not by omission --
that an authorization change invalidates zero stages: it has no field on
``BindingSnapshot`` at all, and its entry in ``TRIGGER_STAGES`` is the empty
set for every stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import (
    CANONICAL_STAGE_ORDER,
    CheckpointStage,
    ExecutionCheckpoint,
    _branch,
    _hex64,
    _optional_hex64,
    _sha256_id,
    _sha40,
)

ALL_STAGES: frozenset[CheckpointStage] = frozenset(CANONICAL_STAGE_ORDER)

# Canonical evidence_hashes names used to carry the four observational facts
# that live only in Evidence, not in the checkpoint's first-class Binding
# fields (PR head, CI result, review state, external lifecycle marker).
EVIDENCE_HASH_PR_HEAD_SHA = "pr_head_sha"
EVIDENCE_HASH_CI_RESULT = "ci_result"
EVIDENCE_HASH_REVIEW_STATE = "review_state"
EVIDENCE_HASH_EXTERNAL_LIFECYCLE = "external_lifecycle"


class InvalidationTrigger(str, Enum):
    SOURCE_SHA_CHANGED = "source-sha-changed"
    TESTED_SHA_DIFFERS = "tested-sha-differs-from-source-sha"
    DEPENDENCY_CHANGED = "dependency-fingerprint-changed"
    ENVIRONMENT_CHANGED = "environment-fingerprint-changed"
    WORKTREE_CHANGED = "worktree-fingerprint-changed"
    BRANCH_CHANGED = "branch-changed"
    ACCEPTANCE_CRITERIA_CHANGED = "acceptance-criteria-digest-changed"
    AUTHORIZATION_CHANGED = "authorization-changed"
    GOVERNANCE_CONTRACT_CHANGED = "governance-contract-digest-changed"
    COMMAND_PLAN_CHANGED = "command-plan-id-changed"
    PR_HEAD_CHANGED = "pr-head-sha-changed"
    CI_RESULT_STALE = "ci-result-stale"
    REVIEW_FEEDBACK_ARRIVED = "review-feedback-arrived"
    MERGE_BASE_CHANGED = "merge-base-sha-changed"
    LIFECYCLE_CHANGED_EXTERNALLY = "issue-or-pr-lifecycle-changed-externally"


# Single source of truth for the approved invalidation matrix. Each row
# names exactly the stages that trigger invalidates -- reproduced verbatim
# from the #895 design contract. STAGE_INVALIDATION_TRIGGERS below is
# derived from this by inversion, so the two views can never drift apart.
TRIGGER_STAGES: dict[InvalidationTrigger, frozenset[CheckpointStage]] = {
    InvalidationTrigger.SOURCE_SHA_CHANGED: ALL_STAGES,
    InvalidationTrigger.TESTED_SHA_DIFFERS: frozenset(
        {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}
    ),
    InvalidationTrigger.DEPENDENCY_CHANGED: frozenset(
        {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}
    ),
    InvalidationTrigger.ENVIRONMENT_CHANGED: frozenset(
        {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}
    ),
    InvalidationTrigger.WORKTREE_CHANGED: frozenset(
        {
            CheckpointStage.IMPLEMENTATION_COMPLETE,
            CheckpointStage.FOCUSED_TESTS_PASSED,
            CheckpointStage.AGGREGATE_VALIDATION_PASSED,
            CheckpointStage.COMMITTED,
        }
    ),
    InvalidationTrigger.BRANCH_CHANGED: frozenset(
        {
            CheckpointStage.COMMITTED,
            CheckpointStage.PUSHED,
            CheckpointStage.DRAFT_PR_OPENED,
            CheckpointStage.CI_PASSED,
            CheckpointStage.REVIEW_COMPLETE,
            CheckpointStage.MERGED,
            CheckpointStage.ISSUE_CLOSED,
        }
    ),
    # Issue body / acceptance criteria drift invalidates preflight and
    # implementation directly; every later stage attests to a now-superseded
    # objective, so the net effect is every stage.
    InvalidationTrigger.ACCEPTANCE_CRITERIA_CHANGED: ALL_STAGES,
    # Authority is not evidence: structurally, this trigger invalidates
    # nothing. A documentation-only authorization change never invalidates
    # dependency installation or any other evidence stage.
    InvalidationTrigger.AUTHORIZATION_CHANGED: frozenset(),
    # A governance-contract change is re-checked at preflight, and any
    # individual checkpoint whose own recorded governance_contract_digest
    # has drifted is invalidated regardless of which stage it is for.
    InvalidationTrigger.GOVERNANCE_CONTRACT_CHANGED: ALL_STAGES,
    # Folds "required validation changed": the command plan identity is the
    # single field that carries exact ordered command/test identities.
    InvalidationTrigger.COMMAND_PLAN_CHANGED: frozenset(
        {CheckpointStage.FOCUSED_TESTS_PASSED, CheckpointStage.AGGREGATE_VALIDATION_PASSED}
    ),
    InvalidationTrigger.PR_HEAD_CHANGED: frozenset(
        {CheckpointStage.CI_PASSED, CheckpointStage.REVIEW_COMPLETE}
    ),
    InvalidationTrigger.CI_RESULT_STALE: frozenset({CheckpointStage.CI_PASSED}),
    InvalidationTrigger.REVIEW_FEEDBACK_ARRIVED: frozenset({CheckpointStage.REVIEW_COMPLETE}),
    InvalidationTrigger.MERGE_BASE_CHANGED: frozenset(
        {CheckpointStage.AGGREGATE_VALIDATION_PASSED, CheckpointStage.CI_PASSED}
    ),
    InvalidationTrigger.LIFECYCLE_CHANGED_EXTERNALLY: frozenset(
        {CheckpointStage.MERGED, CheckpointStage.ISSUE_CLOSED}
    ),
}

STAGE_INVALIDATION_TRIGGERS: dict[CheckpointStage, frozenset[InvalidationTrigger]] = {
    stage: frozenset(
        trigger for trigger, stages in TRIGGER_STAGES.items() if stage in stages
    )
    for stage in CANONICAL_STAGE_ORDER
}


@dataclass(frozen=True, slots=True)
class BindingSnapshot:
    """One comparable snapshot of the fields the invalidation matrix reads.

    Used for both a stored checkpoint's recorded bindings and the caller's
    live current bindings. The four optional fields carry observational
    facts (PR head, CI result, review state, external lifecycle marker)
    that live only in a checkpoint's ``evidence_hashes``, never as a
    first-class Binding field.
    """

    source_sha: str
    tested_sha: str
    dependency_fingerprint: str
    environment_fingerprint: str
    worktree_fingerprint: str
    branch: str
    acceptance_criteria_digest: str
    governance_contract_digest: str
    command_plan_id: str
    merge_base_sha: str
    pr_head_sha: str | None = None
    ci_result_digest: str | None = None
    review_state_digest: str | None = None
    external_lifecycle_digest: str | None = None

    def __post_init__(self) -> None:
        _sha40(self.source_sha, "source_sha")
        _sha40(self.tested_sha, "tested_sha")
        _hex64(self.dependency_fingerprint, "dependency_fingerprint")
        _hex64(self.environment_fingerprint, "environment_fingerprint")
        _hex64(self.worktree_fingerprint, "worktree_fingerprint")
        _branch(self.branch)
        _hex64(self.acceptance_criteria_digest, "acceptance_criteria_digest")
        _hex64(self.governance_contract_digest, "governance_contract_digest")
        _sha256_id(self.command_plan_id, "command_plan_id")
        _sha40(self.merge_base_sha, "merge_base_sha")
        _optional_hex64(self.pr_head_sha, "pr_head_sha")
        _optional_hex64(self.ci_result_digest, "ci_result_digest")
        _optional_hex64(self.review_state_digest, "review_state_digest")
        _optional_hex64(self.external_lifecycle_digest, "external_lifecycle_digest")


def binding_snapshot_from_checkpoint(checkpoint: ExecutionCheckpoint) -> BindingSnapshot:
    """Project the comparable bindings out of one stored checkpoint."""

    evidence = dict(checkpoint.evidence_hashes)
    return BindingSnapshot(
        source_sha=checkpoint.source_sha,
        tested_sha=checkpoint.tested_sha,
        dependency_fingerprint=checkpoint.dependency_fingerprint,
        environment_fingerprint=checkpoint.environment_fingerprint,
        worktree_fingerprint=checkpoint.worktree_fingerprint,
        branch=checkpoint.branch,
        acceptance_criteria_digest=checkpoint.acceptance_criteria_digest,
        governance_contract_digest=checkpoint.governance_contract_digest,
        command_plan_id=checkpoint.command_plan_id,
        merge_base_sha=checkpoint.merge_base_sha,
        pr_head_sha=evidence.get(EVIDENCE_HASH_PR_HEAD_SHA),
        ci_result_digest=evidence.get(EVIDENCE_HASH_CI_RESULT),
        review_state_digest=evidence.get(EVIDENCE_HASH_REVIEW_STATE),
        external_lifecycle_digest=evidence.get(EVIDENCE_HASH_EXTERNAL_LIFECYCLE),
    )


def detect_triggers(
    *,
    recorded: BindingSnapshot,
    current: BindingSnapshot,
    extra_triggers: frozenset[InvalidationTrigger] = frozenset(),
) -> frozenset[InvalidationTrigger]:
    """Compare a recorded snapshot against the live current snapshot.

    ``extra_triggers`` lets a caller explicitly assert a trigger this
    module cannot detect on its own (there is no test for it, most notably
    ``AUTHORIZATION_CHANGED``, which has no corresponding field at all) --
    used to prove, even under an explicit assertion, that the trigger still
    invalidates nothing.
    """

    if type(recorded) is not BindingSnapshot or type(current) is not BindingSnapshot:
        raise TypeError("recorded and current must be exact BindingSnapshot values")

    triggers: set[InvalidationTrigger] = set(extra_triggers)

    if recorded.source_sha != current.source_sha:
        triggers.add(InvalidationTrigger.SOURCE_SHA_CHANGED)
    if current.tested_sha != current.source_sha:
        triggers.add(InvalidationTrigger.TESTED_SHA_DIFFERS)
    if recorded.dependency_fingerprint != current.dependency_fingerprint:
        triggers.add(InvalidationTrigger.DEPENDENCY_CHANGED)
    if recorded.environment_fingerprint != current.environment_fingerprint:
        triggers.add(InvalidationTrigger.ENVIRONMENT_CHANGED)
    if recorded.worktree_fingerprint != current.worktree_fingerprint:
        triggers.add(InvalidationTrigger.WORKTREE_CHANGED)
    if recorded.branch != current.branch:
        triggers.add(InvalidationTrigger.BRANCH_CHANGED)
    if recorded.acceptance_criteria_digest != current.acceptance_criteria_digest:
        triggers.add(InvalidationTrigger.ACCEPTANCE_CRITERIA_CHANGED)
    if recorded.governance_contract_digest != current.governance_contract_digest:
        triggers.add(InvalidationTrigger.GOVERNANCE_CONTRACT_CHANGED)
    if recorded.command_plan_id != current.command_plan_id:
        triggers.add(InvalidationTrigger.COMMAND_PLAN_CHANGED)
    if recorded.merge_base_sha != current.merge_base_sha:
        triggers.add(InvalidationTrigger.MERGE_BASE_CHANGED)

    pr_head_changed = (
        recorded.pr_head_sha is not None
        and current.pr_head_sha is not None
        and recorded.pr_head_sha != current.pr_head_sha
    )
    if pr_head_changed:
        triggers.add(InvalidationTrigger.PR_HEAD_CHANGED)
        # CI evidence is inherently tied to the head it observed; a changed
        # head definitionally makes prior CI evidence stale.
        triggers.add(InvalidationTrigger.CI_RESULT_STALE)
    if (
        recorded.ci_result_digest is not None
        and current.ci_result_digest is not None
        and recorded.ci_result_digest != current.ci_result_digest
    ):
        triggers.add(InvalidationTrigger.CI_RESULT_STALE)
    if current.review_state_digest is not None and current.review_state_digest != recorded.review_state_digest:
        triggers.add(InvalidationTrigger.REVIEW_FEEDBACK_ARRIVED)
    if (
        current.external_lifecycle_digest is not None
        and current.external_lifecycle_digest != recorded.external_lifecycle_digest
    ):
        triggers.add(InvalidationTrigger.LIFECYCLE_CHANGED_EXTERNALLY)

    return frozenset(triggers)


def is_stage_invalidated(stage: CheckpointStage, triggers: frozenset[InvalidationTrigger]) -> bool:
    if type(stage) is not CheckpointStage:
        raise TypeError("stage must be an exact CheckpointStage")
    return bool(STAGE_INVALIDATION_TRIGGERS[stage] & triggers)
