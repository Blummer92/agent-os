"""Pure-local exact-head validation projection for bounded bulk PR repair.

BR3 binds supplied validation and BR4 review evidence to the current PR head,
projects deferred/retry/blocked/handoff dispositions, and performs no workflow
dispatch, review execution, repair, merge, or external mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ValidationState(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    MISSING = "missing"
    STALE = "stale"
    SUPERSEDED = "superseded"
    UNAVAILABLE = "unavailable"


class ReviewState(str, Enum):
    CLEARED = "cleared"
    MISSING = "missing"
    STALE = "stale"
    BLOCKING_FINDINGS = "blocking-findings"
    MANUAL_BLOCKED = "manual-blocked"


class ValidationDisposition(str, Enum):
    HANDOFF = "handoff"
    RETRY_REQUIRED = "retry-required"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ExactHeadValidationEvidence:
    repository: str
    pull_request_number: int
    current_head_sha: str
    tested_head_sha: str | None
    validation_state: ValidationState
    review_state: ReviewState
    reviewed_head_sha: str | None = None
    failed_attempt_id: str | None = None
    retry_count: int = 0
    retry_ceiling: int = 0
    repairable: bool = True
    semantic_progress: bool = True
    authorization_blocked: bool = False
    ckr6_mutation_blocked: bool = False

    def __post_init__(self) -> None:
        if type(self.repository) is not str or "/" not in self.repository or not self.repository.strip():
            raise ValueError("repository must use owner/name syntax")
        if type(self.pull_request_number) is not int or self.pull_request_number < 1:
            raise ValueError("pull_request_number must be a positive integer")
        _sha(self.current_head_sha, "current_head_sha")
        if self.tested_head_sha is not None:
            _sha(self.tested_head_sha, "tested_head_sha")
        if self.reviewed_head_sha is not None:
            _sha(self.reviewed_head_sha, "reviewed_head_sha")
        if type(self.validation_state) is not ValidationState:
            raise TypeError("validation_state must be ValidationState")
        if type(self.review_state) is not ReviewState:
            raise TypeError("review_state must be ReviewState")
        if type(self.retry_count) is not int or self.retry_count < 0:
            raise ValueError("retry_count must be a non-negative integer")
        if type(self.retry_ceiling) is not int or self.retry_ceiling < 0:
            raise ValueError("retry_ceiling must be a non-negative integer")
        for value, name in (
            (self.repairable, "repairable"),
            (self.semantic_progress, "semantic_progress"),
            (self.authorization_blocked, "authorization_blocked"),
            (self.ckr6_mutation_blocked, "ckr6_mutation_blocked"),
        ):
            if type(value) is not bool:
                raise TypeError(f"{name} must use built-in bool")
        if self.failed_attempt_id is not None and (
            type(self.failed_attempt_id) is not str or not self.failed_attempt_id.strip()
        ):
            raise ValueError("failed_attempt_id must be non-empty when supplied")


@dataclass(frozen=True, slots=True)
class ExactHeadValidationProjection:
    repository: str
    pull_request_number: int
    head_sha: str
    effective_validation_state: ValidationState
    review_state: ReviewState
    disposition: ValidationDisposition
    reason_codes: tuple[str, ...]
    failed_attempt_id: str | None
    workflow_dispatch_required: bool
    diagnostic_routing_required: bool
    review_clearance_required: bool
    handoff_to_bm0: bool
    mutation_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def evaluate_exact_head_validation(
    evidence: ExactHeadValidationEvidence,
) -> ExactHeadValidationProjection:
    if type(evidence) is not ExactHeadValidationEvidence:
        raise TypeError("evidence must be ExactHeadValidationEvidence")

    state = evidence.validation_state
    reasons: list[str] = []
    if evidence.tested_head_sha is not None and evidence.tested_head_sha != evidence.current_head_sha:
        state = ValidationState.STALE
        reasons.append("validation-head-stale")

    review_state = evidence.review_state
    if evidence.reviewed_head_sha is not None and evidence.reviewed_head_sha != evidence.current_head_sha:
        review_state = ReviewState.STALE
        reasons.append("review-head-stale")

    if evidence.authorization_blocked:
        disposition = ValidationDisposition.BLOCKED
        reasons.append("authorization-boundary")
    elif evidence.ckr6_mutation_blocked:
        disposition = ValidationDisposition.BLOCKED
        reasons.append("ckr6-mutation-blocked")
    elif not evidence.semantic_progress:
        disposition = ValidationDisposition.BLOCKED
        reasons.append("semantic-progress-failed")
    elif review_state is not ReviewState.CLEARED:
        disposition = ValidationDisposition.BLOCKED
        reasons.append(f"review-{review_state.value}")
    elif state is ValidationState.SUCCESS:
        disposition = ValidationDisposition.HANDOFF
        reasons.append("review-cleared-exact-head-valid")
    elif state is ValidationState.FAILURE:
        if evidence.repairable and evidence.retry_count < evidence.retry_ceiling:
            if evidence.failed_attempt_id is None:
                raise ValueError("repairable red validation requires exact failed_attempt_id")
            disposition = ValidationDisposition.RETRY_REQUIRED
            reasons.append("red-repairable-under-retry-ceiling")
        else:
            disposition = ValidationDisposition.BLOCKED
            reasons.append("retry-ceiling-or-nonrepairable-failure")
    elif state in {
        ValidationState.PENDING,
        ValidationState.CANCELLED,
        ValidationState.SKIPPED,
        ValidationState.MISSING,
        ValidationState.STALE,
        ValidationState.SUPERSEDED,
        ValidationState.UNAVAILABLE,
    }:
        disposition = ValidationDisposition.DEFERRED
        reasons.append(f"validation-{state.value}")
    else:  # pragma: no cover - enum exhaustiveness guard
        raise AssertionError("unhandled validation state")

    workflow_dispatch_required = state in {
        ValidationState.CANCELLED,
        ValidationState.SKIPPED,
        ValidationState.MISSING,
        ValidationState.SUPERSEDED,
        ValidationState.UNAVAILABLE,
    }
    return ExactHeadValidationProjection(
        repository=evidence.repository,
        pull_request_number=evidence.pull_request_number,
        head_sha=evidence.current_head_sha,
        effective_validation_state=state,
        review_state=review_state,
        disposition=disposition,
        reason_codes=tuple(reasons),
        failed_attempt_id=evidence.failed_attempt_id if disposition is ValidationDisposition.RETRY_REQUIRED else None,
        workflow_dispatch_required=workflow_dispatch_required,
        diagnostic_routing_required=state is ValidationState.FAILURE,
        review_clearance_required=review_state is not ReviewState.CLEARED,
        handoff_to_bm0=disposition is ValidationDisposition.HANDOFF,
    )


def _sha(value: str, field: str) -> None:
    if type(value) is not str or len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be exactly 40 lowercase hexadecimal characters")
