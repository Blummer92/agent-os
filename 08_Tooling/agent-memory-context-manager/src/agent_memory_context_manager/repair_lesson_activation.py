"""Mandatory CKR6 lesson activation at failed-repair retry boundaries (#1873).

This module composes the existing CKR6 retry gate and CKR11 read-only activation
bridge. It creates no second selector, Notion client, authority model, scheduler,
or persistence path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Mapping

from .coding_knowledge_selection import CodingKnowledgeRequest
from .lesson_retrieval_orchestrator import orchestrate_lesson_retrieval
from .lesson_preflight import (
    FailedRepairAttempt,
    LessonPreflightResult,
    LessonRetrievalStatus,
    RepairContext,
    RepairRetryBoundaryPlan,
    RetryReentryOutcome,
    plan_repair_retry_boundary,
)

ReadExecutor = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class RepairLessonDisposition(str, Enum):
    """Exact-attempt lesson classification without changing retry admission."""

    CONSUMED = "consumed"
    NOT_MATERIAL = "not-material"
    CAPABILITY_UNAVAILABLE = "capability-unavailable"
    NO_RELEVANT_LESSON = "no-relevant-lesson"
    CANDIDATE_DATA_DEFECT = "candidate-data-defect"
    STALE_RELEVANT_LESSON = "stale-relevant-lesson"
    UNVERIFIABLE_RELEVANT_LESSON = "unverifiable-relevant-lesson"
    CANONICAL_AUTHORITY_CONFLICT = "canonical-authority-conflict"
    GOVERNANCE_INSUFFICIENT = "governance-insufficient"


@dataclass(frozen=True, slots=True)
class RepairLessonActivationResult:
    """One retry-specific lesson outcome plus the resulting mutation gate."""

    attempt: FailedRepairAttempt
    lesson_result: LessonPreflightResult
    lesson_disposition: RepairLessonDisposition
    boundary: RepairRetryBoundaryPlan


def activate_repair_retry_lessons(
    request: CodingKnowledgeRequest,
    attempt: FailedRepairAttempt,
    *,
    execute_read: ReadExecutor | None,
    repair_context: RepairContext = RepairContext.FAILED_PR_REPAIR,
) -> RepairLessonActivationResult:
    """Automatically satisfy the current failed-attempt CKR6 re-entry boundary.

    Repair/CI retry contexts force CKR6 material-use evaluation unless the
    caller explicitly opted out with ``specialized_knowledge_required=False``.
    When retrieval is required, CKR11 walks CKR2's existing bounded retrieval
    ledger. The returned outcome is recorded on this exact failed attempt before
    the retry gate is recomputed. A specialized-required retrieval failure
    remains a mutation blocker rather than being flattened into an admissible
    outcome; #2142 owns any change to that classification.
    """
    if type(request) is not CodingKnowledgeRequest:
        raise TypeError("request must be a CodingKnowledgeRequest")
    if type(attempt) is not FailedRepairAttempt:
        raise TypeError("attempt must be a FailedRepairAttempt")
    if type(repair_context) is not RepairContext or repair_context is RepairContext.NONE:
        raise ValueError("repair_context must be a repair or CI diagnosis context")

    initial = plan_repair_retry_boundary(repair_context, (attempt,))
    if initial.mutation_admissible:
        raise ValueError("failed attempt already has a CKR6 retry re-entry outcome")

    effective_request = request
    if request.specialized_knowledge_required is not False:
        effective_request = replace(request, specialized_knowledge_required=True)

    lesson_result = orchestrate_lesson_retrieval(
        effective_request,
        execute_read=execute_read,
    )
    outcome = _retry_outcome(lesson_result)
    disposition = _lesson_disposition(lesson_result)
    updated_attempt = replace(attempt, retry_reentry_outcome=outcome)

    if lesson_result.lesson_retrieval_status in {
        LessonRetrievalStatus.INSUFFICIENT,
        LessonRetrievalStatus.MANUAL_REVIEW,
    }:
        boundary = RepairRetryBoundaryPlan(
            False,
            attempt.attempt_id,
            ("retry-ckr6-reentry-unavailable-or-failed",),
        )
    else:
        boundary = plan_repair_retry_boundary(repair_context, (updated_attempt,))
    return RepairLessonActivationResult(updated_attempt, lesson_result, disposition, boundary)


def _retry_outcome(result: LessonPreflightResult) -> RetryReentryOutcome:
    status = result.lesson_retrieval_status
    if status is LessonRetrievalStatus.SUFFICIENT:
        return RetryReentryOutcome.CONSUMED
    if status is LessonRetrievalStatus.NOT_NEEDED:
        return RetryReentryOutcome.NOT_MATERIAL
    return RetryReentryOutcome.UNAVAILABLE_OR_FAILED


def _lesson_disposition(result: LessonPreflightResult) -> RepairLessonDisposition:
    status = result.lesson_retrieval_status
    reasons = set(result.selection_reason_codes)
    if status is LessonRetrievalStatus.SUFFICIENT:
        return RepairLessonDisposition.CONSUMED
    if status is LessonRetrievalStatus.NOT_NEEDED:
        return RepairLessonDisposition.NOT_MATERIAL
    if status is LessonRetrievalStatus.UNAVAILABLE_SAFE_FALLBACK or any(
        reason.startswith("lesson-retrieval-unavailable") for reason in reasons
    ):
        return RepairLessonDisposition.CAPABILITY_UNAVAILABLE
    if "no-relevant-candidate" in reasons:
        return RepairLessonDisposition.NO_RELEVANT_LESSON
    if "stale-relevant-candidate" in reasons:
        return RepairLessonDisposition.STALE_RELEVANT_LESSON
    if "unverifiable-relevant-candidate" in reasons:
        return RepairLessonDisposition.UNVERIFIABLE_RELEVANT_LESSON
    if "canonical-authority-conflict" in reasons:
        return RepairLessonDisposition.CANONICAL_AUTHORITY_CONFLICT
    if any(
        reason in {"candidate-data-defect", "duplicate-identity-conflict"} or "malformed" in reason
        for reason in reasons
    ):
        return RepairLessonDisposition.CANDIDATE_DATA_DEFECT
    return RepairLessonDisposition.GOVERNANCE_INSUFFICIENT


__all__ = [
    "RepairLessonActivationResult",
    "RepairLessonDisposition",
    "activate_repair_retry_lessons",
]
