"""MCP protocol binding for the bounded Agent OS ChatGPT facade (#1966 / #1988 / #2363 / #2487 / #2331 / #2523 / #2528 / #2607 / #2612)."""

from __future__ import annotations

from dataclasses import asdict

from mcp.server import MCPServer

from scripts.agent_os_execution_interface.continuation_driver import ContinuationDecision, continuation_payload
from scripts.agent_os_execution_interface.investigation_completion_admission import evaluate_investigation_completion_admission
from scripts.agent_os_issue_acceptance.primary_pr_creation_admission import (
    ActivePrimaryPr,
    BatchIssuePrimaryPrEvidence,
    evaluate_batch_primary_pr_packaging,
    evaluate_primary_pr_creation_admission,
)

from .bulk_repair_facade import classify_bulk_repair_continuation
from .connected_issue_creation_facade import plan_connected_issue_creation_for_host
from .issue_batch_completion import classify_issue_batch_completion
from .issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from .lesson_reader_composition import resolve_lesson_read_route
from .mcp_facade import (
    activate_agent_os_failed_repair,
    admit_agent_os_failed_repair,
    classify_agent_os_continuation,
    classify_agent_os_mission_completion,
    plan_agent_os_continuation,
)

mcp = MCPServer("Agent OS")


def _lesson_route(lesson_rows: list[dict[str, object]] | None):
    if lesson_rows is not None:
        return (lambda _query: {"results": lesson_rows}, "diagnostic-override", "diagnostic-lesson-rows", False)
    route = resolve_lesson_read_route()
    return (route.execute_read, route.status.value, route.reason_code, route.canonical_source_unavailable)


def _with_lesson_route(result: dict[str, object], route_status: str, reason_code: str, canonical_source_unavailable: bool) -> dict[str, object]:
    return {**result, "lesson_read_route_status": route_status, "lesson_read_route_reason_code": reason_code, "canonical_lessons_source_unavailable": canonical_source_unavailable}


def _deferred_lesson_read():
    """Resolve the provider route only when CKR6 actually performs a read."""
    state: dict[str, object] = {
        "resolved": False,
        "execute_read": None,
        "status": "not-needed",
        "reason_code": "lesson-retrieval-not-required",
        "canonical_source_unavailable": False,
    }

    def execute_read(query):
        if not state["resolved"]:
            reader, status, reason_code, source_unavailable = _lesson_route(None)
            state.update(
                resolved=True,
                execute_read=reader,
                status=status,
                reason_code=reason_code,
                canonical_source_unavailable=source_unavailable,
            )
        reader = state["execute_read"]
        if reader is None:
            raise RuntimeError("lesson read route unavailable on current execution surface")
        return reader(query)

    return execute_read, state


@mcp.tool()
def plan_connected_issue_creation_tool(
    repository: str,
    issue_body: str,
    duplicate_review_disposition: str | None = None,
    canonical_issue_number: int | None = None,
    distinct_repair_seam: bool = False,
) -> dict[str, object]:
    """Project canonical connected-issue admission evidence without performing writes."""
    return plan_connected_issue_creation_for_host(
        repository=repository,
        issue_body=issue_body,
        duplicate_review_disposition=duplicate_review_disposition,
        canonical_issue_number=canonical_issue_number,
        distinct_repair_seam=distinct_repair_seam,
    )


@mcp.tool()
def plan_agent_os_continuation_tool(repository: str, issue_number: int, canonical_handoff_id: str | None = None) -> dict[str, object]:
    return dict(plan_agent_os_continuation(repository=repository, issue_number=issue_number, canonical_handoff_id=canonical_handoff_id))


@mcp.tool()
def admit_agent_os_primary_pr_creation_tool(issue_number: int, issue_open: bool, evidence_current: bool, active_primary_prs: list[dict[str, object]]) -> dict[str, object]:
    """Classify create/reuse/conflict immediately before Draft PR materialization."""
    claims = tuple(
        ActivePrimaryPr(
            pull_request_number=item["pull_request_number"],
            branch=item["branch"],
            head_sha=item["head_sha"],
        )
        for item in active_primary_prs
    )
    result = evaluate_primary_pr_creation_admission(
        issue_number=issue_number,
        issue_open=issue_open,
        evidence_current=evidence_current,
        active_primary_prs=claims,
    )
    return {
        "action": result.action.value,
        "creation_admitted": result.creation_admitted,
        "existing_pull_request_number": result.existing_pull_request_number,
        "reason_codes": list(result.reason_codes),
        "github_writes_authorized": result.github_writes_authorized,
    }


@mcp.tool()
def admit_agent_os_batch_pr_packaging_tool(issue_evidence: list[dict[str, object]], evidence_current: bool) -> dict[str, object]:
    """Preserve independent primary-PR lineage across one batch (#2447)."""
    evidence = tuple(
        BatchIssuePrimaryPrEvidence(
            issue_number=item["issue_number"],
            issue_open=item["issue_open"],
            objective_ref=item["objective_ref"],
            active_primary_prs=tuple(
                ActivePrimaryPr(
                    pull_request_number=claim["pull_request_number"],
                    branch=claim["branch"],
                    head_sha=claim["head_sha"],
                )
                for claim in item.get("active_primary_prs", ())
            ),
        )
        for item in issue_evidence
    )
    result = evaluate_batch_primary_pr_packaging(issue_evidence=evidence, evidence_current=evidence_current)
    return {
        "packaging_admitted": result.packaging_admitted,
        "issue_numbers": list(result.issue_numbers),
        "per_issue": [
            {
                "issue_number": number,
                "action": admission.action.value,
                "creation_admitted": admission.creation_admitted,
                "existing_pull_request_number": admission.existing_pull_request_number,
                "reason_codes": list(admission.reason_codes),
            }
            for number, admission in result.per_issue_admissions
        ],
        "reason_codes": list(result.reason_codes),
        "github_writes_authorized": result.github_writes_authorized,
    }


@mcp.tool()
def activate_agent_os_issue_start_lessons_tool(repository: str, issue_number: int, task_reference: str, ecosystem_hints: tuple[str, ...] = (), language_hints: tuple[str, ...] = (), library_hints: tuple[str, ...] = (), capability_keywords: tuple[str, ...] = (), target_path_hints: tuple[str, ...] = (), canonical_rule_refs: tuple[str, ...] = (), known_knowledge_refs: tuple[str, ...] = (), specialized_knowledge_required: bool | None = None, lesson_rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    if lesson_rows is not None:
        execute_read, route_status, reason_code, source_unavailable = _lesson_route(lesson_rows)
        result = activate_issue_start_lesson_preflight(repository=repository, issue_number=issue_number, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read)
        return _with_lesson_route(result, route_status, reason_code, source_unavailable)

    execute_read, route_state = _deferred_lesson_read()
    result = activate_issue_start_lesson_preflight(repository=repository, issue_number=issue_number, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read)
    return _with_lesson_route(
        result,
        str(route_state["status"]),
        str(route_state["reason_code"]),
        bool(route_state["canonical_source_unavailable"]),
    )


@mcp.tool()
def activate_agent_os_failed_repair_tool(repository: str, issue_number: int, attempt_id: str, failed_hypothesis: str, result_summary: str, task_reference: str, ecosystem_hints: tuple[str, ...] = (), language_hints: tuple[str, ...] = (), library_hints: tuple[str, ...] = (), capability_keywords: tuple[str, ...] = (), target_path_hints: tuple[str, ...] = (), canonical_rule_refs: tuple[str, ...] = (), known_knowledge_refs: tuple[str, ...] = (), specialized_knowledge_required: bool | None = None, lesson_rows: list[dict[str, object]] | None = None, repair_context: str = "failed-pr-repair") -> dict[str, object]:
    execute_read, route_status, reason_code, source_unavailable = _lesson_route(lesson_rows)
    result = activate_agent_os_failed_repair(repository=repository, issue_number=issue_number, attempt_id=attempt_id, failed_hypothesis=failed_hypothesis, result_summary=result_summary, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read, repair_context=repair_context)
    return _with_lesson_route(result, route_status, reason_code, source_unavailable)


@mcp.tool()
def admit_agent_os_failed_repair_tool(activation_result: dict[str, object], check_state: str, required_check_configuration_state: str, review_state: str, branch_freshness: str, mergeability: str) -> dict[str, object]:
    return admit_agent_os_failed_repair(activation_result=activation_result, check_state=check_state, required_check_configuration_state=required_check_configuration_state, review_state=review_state, branch_freshness=branch_freshness, mergeability=mergeability)


@mcp.tool()
def classify_agent_os_mission_completion_tool(repository: str, issue_number: int, branch_exists: bool, implementation_commit_count: int, draft_pr_exists: bool, canonical_pr_readback_verified: bool, capable_route_available: bool, subordinate_writes_only: bool) -> dict[str, object]:
    return classify_agent_os_mission_completion(repository=repository, issue_number=issue_number, branch_exists=branch_exists, implementation_commit_count=implementation_commit_count, draft_pr_exists=draft_pr_exists, canonical_pr_readback_verified=canonical_pr_readback_verified, capable_route_available=capable_route_available, subordinate_writes_only=subordinate_writes_only)


@mcp.tool()
def classify_agent_os_issue_batch_completion_tool(repository: str, issue_number: int, lane_evidence: list[dict[str, object]]) -> dict[str, object]:
    """Require PR-or-explicit-no-PR terminal proof for every selected issue lane."""
    return classify_issue_batch_completion(repository=repository, issue_number=issue_number, lane_evidence=lane_evidence)


@mcp.tool()
def classify_agent_os_investigation_completion_tool(repository: str, issue_number: int, material_branch_states: tuple[str, ...], executable_next_action_available: bool, subordinate_write_performed: bool) -> dict[str, object]:
    decision = evaluate_investigation_completion_admission(repository=repository, issue_number=issue_number, material_branch_states=material_branch_states, executable_next_action_available=executable_next_action_available, subordinate_write_performed=subordinate_write_performed)
    payload = asdict(decision); payload["reason_codes"] = list(decision.reason_codes); payload["agent_os_continuation"] = continuation_payload(ContinuationDecision(action="" if decision.completion_admissible else decision.next_action, terminal=decision.completion_admissible, blocked=(not decision.completion_admissible and not decision.executable_next_action_available), reason_codes=decision.reason_codes)); return payload


@mcp.tool()
def classify_agent_os_continuation_tool(repository: str, issue_number: int, operation_id: str, surface_outcome: str, approved_alternative_capability: str | None = None, branch: str | None = None, pull_request: int | None = None, checkpoint_id: str | None = None, lease_id: str | None = None, prior_effect: str = "none-proven", target_identity_reacquired: bool = False, requires_exact_blob_identity: bool = False, exact_blob_identity_reacquired: bool = False, runtime_surface_transition: bool = False, evidence_compatibility_confirmed: bool = False, active_foreign_lease: bool = False, equivalent_transition_repeated: bool = False, material_decision_required: bool = False, alternative_widens_authority: bool = False, non_absorbed_domain: str | None = None) -> dict[str, object]:
    return classify_agent_os_continuation(repository=repository, issue_number=issue_number, operation_id=operation_id, surface_outcome=surface_outcome, approved_alternative_capability=approved_alternative_capability, branch=branch, pull_request=pull_request, checkpoint_id=checkpoint_id, lease_id=lease_id, prior_effect=prior_effect, target_identity_reacquired=target_identity_reacquired, requires_exact_blob_identity=requires_exact_blob_identity, exact_blob_identity_reacquired=exact_blob_identity_reacquired, runtime_surface_transition=runtime_surface_transition, evidence_compatibility_confirmed=evidence_compatibility_confirmed, active_foreign_lease=active_foreign_lease, equivalent_transition_repeated=equivalent_transition_repeated, material_decision_required=material_decision_required, alternative_widens_authority=alternative_widens_authority, non_absorbed_domain=non_absorbed_domain)


@mcp.tool()
def classify_agent_os_bulk_repair_continuation_tool(repository: str, issue_number: int, requested_pull_requests: list[int], candidate_evidence: list[dict[str, object]]) -> dict[str, object]:
    return classify_bulk_repair_continuation(repository=repository, issue_number=issue_number, requested_pull_requests=requested_pull_requests, candidate_evidence=candidate_evidence)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
