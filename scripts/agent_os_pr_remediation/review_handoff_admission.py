"""Fail-closed admission for declaring a PR review handoff complete.

This module consumes already-normalized review evidence only. It performs no
GitHub/provider I/O and does not trigger review, mutate lifecycle state, or grant
merge/closure authority. Provider execution/normalization remains owned by #1588.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .merge_evidence_summary import AIReviewEvidence, ReviewStatus
from .models import EvidenceValidationError


class ReviewHandoffState(str, Enum):
    REVIEW_NOT_REQUIRED = "review-not-required"
    REVIEW_REQUESTED_PENDING = "review-requested/pending"
    SUBSTANTIVE_REVIEW_PERFORMED_CURRENT = "substantive-review-performed/current"
    REVIEW_UNAVAILABLE_MANUAL_REVIEW = "review-unavailable/manual-review"


@dataclass(frozen=True, slots=True)
class ReviewHandoffAdmission:
    state: ReviewHandoffState
    review_complete: bool
    blocker: str | None
    clearing_condition: str | None
    reason_codes: tuple[str, ...]
    side_effects_performed: bool = False


def admit_review_handoff(
    *,
    review_required: bool,
    current_head_sha: str,
    review_evidence: AIReviewEvidence | None,
    review_requested: bool = False,
    provider_disabled_or_not_triggered: bool = False,
    independent_reviewer: bool = False,
    substantive_review: bool = False,
) -> ReviewHandoffAdmission:
    """Classify current review-handoff evidence without synthesizing completion.

    `review_evidence` must already be provider-normalized. A GitHub COMMENTED or
    APPROVED artifact is not substantive merely because it exists; callers must
    separately prove independent reviewer identity and substantive execution.
    """
    for name, value in (
        ("review_required", review_required),
        ("review_requested", review_requested),
        ("provider_disabled_or_not_triggered", provider_disabled_or_not_triggered),
        ("independent_reviewer", independent_reviewer),
        ("substantive_review", substantive_review),
    ):
        if type(value) is not bool:
            raise EvidenceValidationError(f"{name} must be a boolean")
    if type(current_head_sha) is not str or len(current_head_sha) != 40 or any(
        char not in "0123456789abcdef" for char in current_head_sha.lower()
    ):
        raise EvidenceValidationError("current_head_sha must be a 40-character hexadecimal SHA")
    if review_evidence is not None and type(review_evidence) is not AIReviewEvidence:
        raise EvidenceValidationError("review_evidence must be AIReviewEvidence or None")

    if not review_required:
        return ReviewHandoffAdmission(
            state=ReviewHandoffState.REVIEW_NOT_REQUIRED,
            review_complete=True,
            blocker=None,
            clearing_condition=None,
            reason_codes=("review-policy:not-required",),
        )

    if provider_disabled_or_not_triggered:
        return ReviewHandoffAdmission(
            state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
            review_complete=False,
            blocker="required substantive review is disabled or not triggered",
            clearing_condition="obtain current substantive review evidence or an explicit canonical review-not-required decision",
            reason_codes=("review-required", "provider-disabled-or-not-triggered"),
        )

    if review_evidence is not None:
        if review_evidence.status is ReviewStatus.NOT_REQUIRED:
            # A provider cannot waive a canonical review obligation.
            return ReviewHandoffAdmission(
                state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
                review_complete=False,
                blocker="provider evidence says not-required while canonical policy requires review",
                clearing_condition="resolve the policy/evidence conflict",
                reason_codes=("review-required", "review-policy-conflict"),
            )
        if review_evidence.status in {ReviewStatus.UNAVAILABLE, ReviewStatus.SKIPPED}:
            return ReviewHandoffAdmission(
                state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
                review_complete=False,
                blocker="required substantive review is unavailable or skipped",
                clearing_condition="obtain current substantive review evidence or an explicit canonical review-not-required decision",
                reason_codes=("review-required", f"review-{review_evidence.status.value}"),
            )
        if review_evidence.status is ReviewStatus.STALE or (
            review_evidence.reviewed_sha is not None
            and review_evidence.reviewed_sha.lower() != current_head_sha.lower()
        ):
            return ReviewHandoffAdmission(
                state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
                review_complete=False,
                blocker="substantive review evidence is stale for the current PR head",
                clearing_condition="perform or reacquire substantive review bound to the current exact head",
                reason_codes=("review-required", "review-stale"),
            )
        if review_evidence.status in {ReviewStatus.PERFORMED_CLEAR, ReviewStatus.PERFORMED_BLOCKED}:
            if not independent_reviewer or not substantive_review:
                return ReviewHandoffAdmission(
                    state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
                    review_complete=False,
                    blocker="review artifact does not prove independent substantive review",
                    clearing_condition="prove independent substantive review execution for the current head",
                    reason_codes=("review-required", "substantive-review-unproven"),
                )
            if review_evidence.status is ReviewStatus.PERFORMED_BLOCKED:
                return ReviewHandoffAdmission(
                    state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
                    review_complete=False,
                    blocker="substantive review has unresolved blocking findings",
                    clearing_condition="clear or disposition the blocking review findings and reacquire current evidence",
                    reason_codes=("review-required", "review-performed-blocked"),
                )
            return ReviewHandoffAdmission(
                state=ReviewHandoffState.SUBSTANTIVE_REVIEW_PERFORMED_CURRENT,
                review_complete=True,
                blocker=None,
                clearing_condition=None,
                reason_codes=("review-required", "substantive-review-current"),
            )

    if review_requested:
        return ReviewHandoffAdmission(
            state=ReviewHandoffState.REVIEW_REQUESTED_PENDING,
            review_complete=False,
            blocker="required substantive review is pending",
            clearing_condition="wait for current substantive review evidence",
            reason_codes=("review-required", "review-requested-pending"),
        )

    return ReviewHandoffAdmission(
        state=ReviewHandoffState.REVIEW_UNAVAILABLE_MANUAL_REVIEW,
        review_complete=False,
        blocker="required substantive review has not been proven requested or performed",
        clearing_condition="request review or prove canonical review-not-required",
        reason_codes=("review-required", "review-not-requested"),
    )
