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
from agent_os_execution_service.failed_repair_admission import evaluate_failed_repair_admission
from scripts.agent_os_execution_interface.continuation_driver import ContinuationDecision as DriverDecision
from scripts.agent_os_execution_interface.mission_completion_admission import evaluate_mission_completion_admission
from scripts.agent_os_execution_interface.post_selection_continuation import (
    ContinuationLineage,
    NonAbsorbedDomain,
    PostSelectionAttemptEvidence,
    PriorAttemptEffect,
    classify_post_selection_continuation,
)
from workflow_scheduler.execution.continuation import (
    ContinuationDisposition,
    ExistingWorkEvidence,
    plan_execution_continuation,
)
from workflow_scheduler.execution.host_local_lease_adapter import HostLocalLeaseObservation
from workflow_scheduler.execution.recovery_progress import (
    RecoveryProgressDisposition,
    RecoverySemanticEvidence,
    classify_recovery_progress,
)
from workflow_scheduler.execution.red_ci_continuation import (
    RedCiEvidence,
    RedCiNextAction,
    plan_red_ci_continuation,
)
from workflow_scheduler.execution.single_issue_pilot import PilotLeaseRequest

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


def _driver_payload(decision: DriverDecision) -> dict[str, object]:
    return {
        "action": decision.action,
        "terminal": decision.terminal,
        "blocked": decision.blocked,
        "stalled": decision.stalled,
        "reason_codes": list(decision.reason_codes),
        "execution_authorized": False,
        "github_writes_authorized": False,
        "side_effects_performed": False,
    }


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
    """Execute the existing #1873 CKR6 retry seam for one exact failed attempt."""
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


def admit_agent_os_failed_repair(
    *, activation_result: Mapping[str, object], check_state: str,
    required_check_configuration_state: str, review_state: str,
    branch_freshness: str, mergeability: str,
) -> dict[str, object]:
    """Consume the existing failed-repair admission classifier at the runtime facade."""
    decision = evaluate_failed_repair_admission(
        activation_result=activation_result,
        check_state=check_state,
        required_check_configuration_state=required_check_configuration_state,
        review_state=review_state,
        branch_freshness=branch_freshness,
        mergeability=mergeability,
    )
    payload = asdict(decision)
    payload["reason_codes"] = list(decision.reason_codes)
    payload["agent_os_continuation"] = _driver_payload(DriverDecision(
        action=decision.next_action if decision.mutation_admissible else "",
        blocked=not decision.mutation_admissible,
        reason_codes=decision.reason_codes,
    ))
    return payload


def classify_agent_os_mission_completion(
    *, repository: str, issue_number: int, branch_exists: bool,
    implementation_commit_count: int, draft_pr_exists: bool,
    canonical_pr_readback_verified: bool, capable_route_available: bool,
    subordinate_writes_only: bool,
) -> dict[str, object]:
    """Consume the existing mission-completion admission classifier at runtime."""
    decision = evaluate_mission_completion_admission(
        repository=_repository(repository), issue_number=_issue_number(issue_number),
        branch_exists=branch_exists, implementation_commit_count=implementation_commit_count,
        draft_pr_exists=draft_pr_exists,
        canonical_pr_readback_verified=canonical_pr_readback_verified,
        capable_route_available=capable_route_available,
        subordinate_writes_only=subordinate_writes_only,
    )
    payload = asdict(decision)
    payload["reason_codes"] = list(decision.reason_codes)
    payload["agent_os_continuation"] = _driver_payload(DriverDecision(
        action="" if decision.completion_admissible else decision.next_action,
        terminal=decision.completion_admissible,
        blocked=(not decision.completion_admissible and not decision.capable_route_available),
        reason_codes=decision.reason_codes,
    ))
    return payload


def classify_agent_os_existing_work(
    *, evidence: ExistingWorkEvidence, resume_plan: object | None,
    lease_request: PilotLeaseRequest | None, lease_observation: HostLocalLeaseObservation | None,
) -> dict[str, object]:
    """Expose the canonical #1188 existing-work classifier without reimplementing it."""
    decision = plan_execution_continuation(
        evidence, resume_plan=resume_plan, lease_request=lease_request,
        lease_observation=lease_observation,
    )
    payload = asdict(decision)
    payload["disposition"] = decision.disposition.value
    blocked = decision.disposition in {
        ContinuationDisposition.ACTIVE_CONFLICT,
        ContinuationDisposition.SCOPE_DRIFT,
        ContinuationDisposition.NEEDS_DECISION,
    }
    action = "" if blocked else decision.recommended_action
    payload["agent_os_continuation"] = _driver_payload(DriverDecision(
        action=action, blocked=blocked, reason_codes=decision.reason_codes,
    ))
    return payload


def classify_agent_os_red_ci(evidence: RedCiEvidence) -> dict[str, object]:
    """Expose the canonical #1251 red-CI classifier and its next action."""
    decision = plan_red_ci_continuation(evidence)
    payload = asdict(decision)
    payload["failure_class"] = decision.failure_class.value
    payload["next_action"] = decision.next_action.value
    blocked = decision.next_action in {
        RedCiNextAction.BLOCKED_DIAGNOSTIC_SURFACE,
        RedCiNextAction.NEEDS_DECISION,
    }
    payload["agent_os_continuation"] = _driver_payload(DriverDecision(
        action="" if blocked else decision.next_action.value,
        blocked=blocked,
        reason_codes=decision.reason_codes,
    ))
    return payload


def classify_agent_os_recovery_progress(
    current: RecoverySemanticEvidence, *, prior: RecoverySemanticEvidence | None = None,
    prior_transition_fingerprint: str | None = None,
) -> dict[str, object]:
    """Expose canonical semantic no-progress detection to the continuation path."""
    decision = classify_recovery_progress(
        current, prior=prior, prior_transition_fingerprint=prior_transition_fingerprint,
    )
    payload = asdict(decision)
    payload["disposition"] = decision.disposition.value
    stalled = decision.disposition is RecoveryProgressDisposition.RECOVERY_STALLED
    payload["agent_os_continuation"] = _driver_payload(DriverDecision(
        action="" if stalled else decision.recommended_action,
        stalled=stalled,
        reason_codes=decision.reason_codes,
    ))
    return payload


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
