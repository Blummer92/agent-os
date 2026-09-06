"""Bounded, non-authorizing ChatGPT MCP facade for Agent OS (#1966 / #1988).

This module is deliberately transport-neutral. It exposes finite tool contracts
that reuse existing Agent OS owners instead of creating a second router,
discovery index, repair model, Scheduler, lease, or write authority.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Callable, Literal, Mapping, Any, TypedDict

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_preflight import FailedRepairAttempt, RepairContext
from agent_memory_context_manager.repair_lesson_activation import activate_repair_retry_lessons
from agent_os_execution_service.execution_surface_availability import ExecutionSurfaceAvailabilityOutcome
from scripts.agent_os_execution_interface.post_selection_continuation import (
    ContinuationLineage,
    NonAbsorbedDomain,
    PostSelectionAttemptEvidence,
    PriorAttemptEffect,
    classify_post_selection_continuation,
)

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)
_HANDOFF_RE = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)


class AgentOsContinuationPlan(TypedDict):
    status: Literal["agent-os-route", "needs-decision"]
    repository: str
    issue_number: int
    next_operation: Literal["discover-current-handoff", "resume-existing-handoff", "reconcile-currentness"]
    handoff_id: str | None
    ingress: str | None
    execution_authorized: Literal[False]
    github_writes_authorized: Literal[False]
    scheduler_invoked: Literal[False]
    side_effects_performed: Literal[False]


def _repository(value: object) -> str:
    if type(value) is not str or _REPOSITORY_RE.fullmatch(value) is None:
        raise ValueError("repository must use bounded owner/name syntax")
    return value


def _issue_number(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("issue_number must be a positive built-in integer")
    return value


def _handoff_id(value: object | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _HANDOFF_RE.fullmatch(value) is None:
        raise ValueError("handoff_id must be a canonical executor-handoff identity")
    return value


def plan_agent_os_continuation(*, repository: str, issue_number: int, canonical_handoff_id: str | None = None) -> AgentOsContinuationPlan:
    repo = _repository(repository)
    issue = _issue_number(issue_number)
    handoff = _handoff_id(canonical_handoff_id)
    if handoff is None:
        return {"status": "agent-os-route", "repository": repo, "issue_number": issue, "next_operation": "discover-current-handoff", "handoff_id": None, "ingress": None, "execution_authorized": False, "github_writes_authorized": False, "scheduler_invoked": False, "side_effects_performed": False}
    return {"status": "agent-os-route", "repository": repo, "issue_number": issue, "next_operation": "resume-existing-handoff", "handoff_id": handoff, "ingress": f"/agent-os resume {handoff}", "execution_authorized": False, "github_writes_authorized": False, "scheduler_invoked": False, "side_effects_performed": False}


def activate_agent_os_failed_repair(
    *,
    repository: str,
    issue_number: int,
    attempt_id: str,
    failed_hypothesis: str,
    result_summary: str,
    task_reference: str,
    ecosystem_hints: tuple[str, ...] = (),
    language_hints: tuple[str, ...] = (),
    library_hints: tuple[str, ...] = (),
    capability_keywords: tuple[str, ...] = (),
    target_path_hints: tuple[str, ...] = (),
    canonical_rule_refs: tuple[str, ...] = (),
    known_knowledge_refs: tuple[str, ...] = (),
    specialized_knowledge_required: bool | None = None,
    execute_read: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    repair_context: str = "failed-pr-repair",
) -> dict[str, object]:
    """Execute the existing #1873 CKR6 retry seam for one exact failed attempt.

    This is the ChatGPT-facing conformance boundary missing in the #1987
    recurrence. It does not merely report that policy was read: it materializes
    the canonical request/attempt models, invokes ``activate_repair_retry_lessons``
    exactly once, and returns the resulting mutation gate. The caller must not
    mutate when ``mutation_admissible`` is false.
    """
    repo = _repository(repository)
    issue = _issue_number(issue_number)
    if type(attempt_id) is not str or not attempt_id:
        raise ValueError("attempt_id must be non-empty exact text")
    try:
        context = RepairContext(repair_context)
    except ValueError as exc:
        raise ValueError("unsupported repair_context") from exc
    if context is RepairContext.NONE:
        raise ValueError("repair_context must identify a failed repair or CI diagnosis")

    request = CodingKnowledgeRequest(
        task_reference=task_reference,
        ecosystem_hints=ecosystem_hints,
        language_hints=language_hints,
        library_hints=library_hints,
        capability_keywords=capability_keywords,
        target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs,
        known_knowledge_refs=known_knowledge_refs,
        specialized_knowledge_required=specialized_knowledge_required,
    )
    attempt = FailedRepairAttempt(attempt_id, failed_hypothesis, result_summary)
    result = activate_repair_retry_lessons(request, attempt, execute_read=execute_read, repair_context=context)
    return {
        "repository": repo,
        "issue_number": issue,
        "attempt_id": result.attempt.attempt_id,
        "retry_reentry_outcome": result.attempt.retry_reentry_outcome.value,
        "lesson_retrieval_status": result.lesson_result.lesson_retrieval_status.value,
        "selected_lesson_ids": list(result.lesson_result.selected_lesson_ids),
        "canonical_github_refs": list(result.lesson_result.canonical_github_refs),
        "mutation_admissible": result.boundary.mutation_admissible,
        "blocking_attempt_id": result.boundary.blocking_attempt_id,
        "reason_codes": list(result.boundary.reason_codes),
        "github_writes_authorized": False,
        "execution_authorized": False,
        "side_effects_performed": False,
    }


def classify_agent_os_continuation(
    *, repository: str, issue_number: int, operation_id: str, surface_outcome: str,
    approved_alternative_capability: str | None = None, branch: str | None = None,
    pull_request: int | None = None, checkpoint_id: str | None = None,
    lease_id: str | None = None, prior_effect: str = "none-proven",
    target_identity_reacquired: bool = False, requires_exact_blob_identity: bool = False,
    exact_blob_identity_reacquired: bool = False, runtime_surface_transition: bool = False,
    evidence_compatibility_confirmed: bool = False, active_foreign_lease: bool = False,
    equivalent_transition_repeated: bool = False, material_decision_required: bool = False,
    alternative_widens_authority: bool = False, non_absorbed_domain: str | None = None,
) -> dict[str, object]:
    repo = _repository(repository)
    issue = _issue_number(issue_number)
    if type(operation_id) is not str or not operation_id:
        raise ValueError("operation_id must be non-empty exact text")
    try:
        outcome = ExecutionSurfaceAvailabilityOutcome(surface_outcome)
        effect = PriorAttemptEffect(prior_effect)
        domain = None if non_absorbed_domain is None else NonAbsorbedDomain(non_absorbed_domain)
    except ValueError as exc:
        raise ValueError("unsupported finite Agent OS continuation value") from exc
    lineage = ContinuationLineage(repository=repo, issue_number=issue, branch=branch, pull_request=pull_request, checkpoint_id=checkpoint_id, lease_id=lease_id)
    decision = classify_post_selection_continuation(PostSelectionAttemptEvidence(
        operation_id=operation_id, lineage=lineage, surface_outcome=outcome,
        approved_alternative_capability=approved_alternative_capability,
        alternative_widens_authority=alternative_widens_authority, prior_effect=effect,
        target_identity_reacquired=target_identity_reacquired,
        requires_exact_blob_identity=requires_exact_blob_identity,
        exact_blob_identity_reacquired=exact_blob_identity_reacquired,
        runtime_surface_transition=runtime_surface_transition,
        evidence_compatibility_confirmed=evidence_compatibility_confirmed,
        active_foreign_lease=active_foreign_lease,
        equivalent_transition_repeated=equivalent_transition_repeated,
        material_decision_required=material_decision_required, non_absorbed_domain=domain,
    ))
    payload = asdict(decision)
    payload["classification"] = decision.classification.value
    payload["reason_codes"] = [item.value for item in decision.reason_codes]
    payload["obligations"] = [item.value for item in decision.obligations]
    payload["lineage"] = asdict(decision.lineage)
    return payload
