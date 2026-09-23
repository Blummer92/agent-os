"""Fail-closed recovery admission after a GitHub Contents publication failure.

This module does not perform GitHub writes. It decides whether an already-bounded
replacement publication may switch to the existing atomic Git-object path, and
whether the resulting publication evidence is sufficient to allow Draft-PR
creation. The atomic writer remains the sole mutation owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from .models import AtomicCommitResult, AtomicCommitStatus, MutationState, require_branch, require_path, require_repository, require_sha40


class RecoveryStatus(str, Enum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ContentsFailureEvidence:
    repository: str
    branch: str
    expected_head_sha: str
    paths: tuple[str, ...]
    mutation_state: MutationState
    error_class: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", require_repository(self.repository))
        object.__setattr__(self, "branch", require_branch(self.branch))
        object.__setattr__(self, "expected_head_sha", require_sha40(self.expected_head_sha, "expected_head_sha"))
        if type(self.paths) is not tuple or not self.paths:
            raise ValueError("paths must be a non-empty tuple")
        paths = tuple(sorted(require_path(path) for path in self.paths))
        if len(paths) != len(set(paths)):
            raise ValueError("paths contains duplicates")
        object.__setattr__(self, "paths", paths)
        if not isinstance(self.mutation_state, MutationState):
            raise TypeError("mutation_state must be MutationState")
        if type(self.error_class) is not str or not self.error_class or len(self.error_class) > 128:
            raise ValueError("error_class must be bounded non-empty text")


@dataclass(frozen=True, slots=True)
class PublicationRecoveryDecision:
    status: RecoveryStatus
    reason: str
    use_atomic_git_objects: bool
    pr_creation_allowed: bool
    side_effects_performed: Literal[False] = False


def admit_atomic_recovery(
    failure: ContentsFailureEvidence,
    *,
    observed_branch_sha: str,
    replacement_paths: tuple[str, ...],
) -> PublicationRecoveryDecision:
    """Admit fallback only after a proven pre-side-effect Contents failure."""

    observed = require_sha40(observed_branch_sha, "observed_branch_sha")
    paths = tuple(sorted(require_path(path) for path in replacement_paths))
    if len(paths) != len(set(paths)) or not paths:
        return _blocked("replacement-paths-invalid")
    if failure.mutation_state is MutationState.UNCERTAIN:
        return PublicationRecoveryDecision(
            RecoveryStatus.UNCERTAIN,
            "contents-mutation-uncertain-readback-required",
            False,
            False,
        )
    if failure.mutation_state is not MutationState.FAILED_BEFORE_SIDE_EFFECT:
        return _blocked("contents-failure-not-proven-pre-side-effect")
    if observed != failure.expected_head_sha:
        return _blocked("branch-head-moved-after-contents-failure")
    if paths != failure.paths:
        return _blocked("replacement-paths-do-not-match-failed-publication")
    return PublicationRecoveryDecision(
        RecoveryStatus.ADMITTED,
        "atomic-git-object-recovery-admitted",
        True,
        False,
    )


def admit_pr_creation_after_recovery(
    failure: ContentsFailureEvidence,
    result: AtomicCommitResult,
) -> PublicationRecoveryDecision:
    """Allow Draft-PR creation only after exact atomic publication readback."""

    if result.status is not AtomicCommitStatus.REF_UPDATED:
        status = RecoveryStatus.UNCERTAIN if result.status is AtomicCommitStatus.UNCERTAIN else RecoveryStatus.BLOCKED
        return PublicationRecoveryDecision(status, "atomic-publication-not-confirmed", False, False)
    if result.mutation_state is not MutationState.CONFIRMED:
        return PublicationRecoveryDecision(RecoveryStatus.UNCERTAIN, "atomic-publication-readback-unconfirmed", False, False)
    if result.starting_branch_sha != failure.expected_head_sha:
        return _blocked("atomic-publication-start-head-mismatch")
    if result.ending_branch_sha is None or result.ending_branch_sha == failure.expected_head_sha:
        return _blocked("atomic-publication-did-not-advance-branch")
    if tuple(sorted(result.changed_paths)) != failure.paths:
        return _blocked("atomic-publication-paths-mismatch")
    if result.force_used is not False:
        return _blocked("force-update-not-allowed")
    return PublicationRecoveryDecision(
        RecoveryStatus.ADMITTED,
        "draft-pr-creation-admitted-after-readback",
        False,
        True,
    )


def _blocked(reason: str) -> PublicationRecoveryDecision:
    return PublicationRecoveryDecision(RecoveryStatus.BLOCKED, reason, False, False)
