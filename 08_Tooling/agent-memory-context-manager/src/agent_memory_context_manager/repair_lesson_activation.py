"""Mandatory CKR6 lesson activation at failed-repair retry boundaries (#1873).

This module composes the existing CKR6 retry gate and CKR11 read-only activation
bridge. It creates no second selector, Notion client, authority model, scheduler,
or persistence path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Callable

from .coding_knowledge_selection import CodingKnowledgeRequest
from .lesson_activation_bridge import orchestrate_lesson_activation
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


@dataclass(frozen=True, slots=True)
class RepairLessonActivationResult:
    """One retry-specific lesson outcome plus the resulting mutation gate."""

    attempt: FailedRepairAttempt
    lesson_result: LessonPreflightResult
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
    When retrieval is required, CKR11 performs the existing bounded read. The
    returned outcome is recorded on this exact failed attempt before the retry
    gate is recomputed.
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

    lesson_result = orchestrate_lesson_activation(
        effective_request,
        execute_read=execute_read,
    )
    outcome = _retry_outcome(lesson_result)
    updated_attempt = replace(attempt, retry_reentry_outcome=outcome)
    boundary = plan_repair_retry_boundary(repair_context, (updated_attempt,))
    return RepairLessonActivationResult(updated_attempt, lesson_result, boundary)


def _retry_outcome(result: LessonPreflightResult) -> RetryReentryOutcome:
    status = result.lesson_retrieval_status
    if status is LessonRetrievalStatus.SUFFICIENT:
        return RetryReentryOutcome.CONSUMED
    if status is LessonRetrievalStatus.NOT_NEEDED:
        return RetryReentryOutcome.NOT_MATERIAL
    return RetryReentryOutcome.UNAVAILABLE_OR_FAILED


__all__ = ["RepairLessonActivationResult", "activate_repair_retry_lessons"]
