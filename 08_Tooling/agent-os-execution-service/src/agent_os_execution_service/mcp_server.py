"""MCP protocol binding for the bounded Agent OS ChatGPT facade (#1966 / #1988)."""

from __future__ import annotations

from mcp.server import MCPServer

from .lesson_execution_surface_router import (
    activate_routed_issue_start_lesson_preflight,
    execute_routed_notion_read,
)
from .lesson_reader_composition import build_lesson_read_executor
from .mcp_facade import (
    activate_agent_os_failed_repair,
    admit_agent_os_failed_repair,
    classify_agent_os_continuation,
    classify_agent_os_mission_completion,
    plan_agent_os_continuation,
)

mcp = MCPServer("Agent OS")


@mcp.tool()
def plan_agent_os_continuation_tool(repository: str, issue_number: int, canonical_handoff_id: str | None = None) -> dict[str, object]:
    return dict(plan_agent_os_continuation(repository=repository, issue_number=issue_number, canonical_handoff_id=canonical_handoff_id))


@mcp.tool()
def read_agent_os_notion_knowledge_tool(content_class: str, query: dict[str, object], native_notion_connector_available: bool = False, notion_rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Read one typed Agent OS Notion knowledge surface without creating write authority."""
    native_execute_read = (
        (lambda _query: {"results": notion_rows})
        if native_notion_connector_available and notion_rows is not None
        else None
    )
    fallback_factory = (
        (lambda: (lambda _query: {"results": notion_rows}))
        if not native_notion_connector_available and notion_rows is not None
        else None
    )
    return execute_routed_notion_read(
        content_class=content_class,
        query=query,
        native_notion_connector_available=native_notion_connector_available,
        native_execute_read=native_execute_read,
        fallback_factory=fallback_factory,
    )


@mcp.tool()
def activate_agent_os_issue_start_lessons_tool(repository: str, issue_number: int, task_reference: str, native_notion_connector_available: bool = False, ecosystem_hints: tuple[str, ...] = (), language_hints: tuple[str, ...] = (), library_hints: tuple[str, ...] = (), capability_keywords: tuple[str, ...] = (), target_path_hints: tuple[str, ...] = (), canonical_rule_refs: tuple[str, ...] = (), known_knowledge_refs: tuple[str, ...] = (), specialized_knowledge_required: bool | None = None, lesson_rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Resolve mandatory initial CKR6 through native Notion or existing fallback."""
    native_execute_read = (
        (lambda _query: {"results": lesson_rows})
        if native_notion_connector_available and lesson_rows is not None
        else None
    )
    fallback_factory = (
        (lambda: (lambda _query: {"results": lesson_rows}))
        if not native_notion_connector_available and lesson_rows is not None
        else build_lesson_read_executor
    )
    return activate_routed_issue_start_lesson_preflight(
        repository=repository,
        issue_number=issue_number,
        task_reference=task_reference,
        native_notion_connector_available=native_notion_connector_available,
        native_execute_read=native_execute_read,
        fallback_factory=fallback_factory,
        ecosystem_hints=ecosystem_hints,
        language_hints=language_hints,
        library_hints=library_hints,
        capability_keywords=capability_keywords,
        target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs,
        known_knowledge_refs=known_knowledge_refs,
        specialized_knowledge_required=specialized_knowledge_required,
    )


@mcp.tool()
def activate_agent_os_failed_repair_tool(repository: str, issue_number: int, attempt_id: str, failed_hypothesis: str, result_summary: str, task_reference: str, ecosystem_hints: tuple[str, ...] = (), language_hints: tuple[str, ...] = (), library_hints: tuple[str, ...] = (), capability_keywords: tuple[str, ...] = (), target_path_hints: tuple[str, ...] = (), canonical_rule_refs: tuple[str, ...] = (), known_knowledge_refs: tuple[str, ...] = (), specialized_knowledge_required: bool | None = None, lesson_rows: list[dict[str, object]] | None = None, repair_context: str = "failed-pr-repair") -> dict[str, object]:
    # ``lesson_rows`` is an explicit test/diagnostic override. Production calls
    # bind CKR11 to the existing read-only Scheduler Notion adapter so the
    # bounded query produced by the lesson bridge is actually executed.
    execute_read = (
        (lambda _query: {"results": lesson_rows})
        if lesson_rows is not None
        else build_lesson_read_executor()
    )
    return activate_agent_os_failed_repair(repository=repository, issue_number=issue_number, attempt_id=attempt_id, failed_hypothesis=failed_hypothesis, result_summary=result_summary, task_reference=task_reference, ecosystem_hints=ecosystem_hints, language_hints=language_hints, library_hints=library_hints, capability_keywords=capability_keywords, target_path_hints=target_path_hints, canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs, specialized_knowledge_required=specialized_knowledge_required, execute_read=execute_read, repair_context=repair_context)


@mcp.tool()
def admit_agent_os_failed_repair_tool(activation_result: dict[str, object], check_state: str, required_check_configuration_state: str, review_state: str, branch_freshness: str, mergeability: str) -> dict[str, object]:
    return admit_agent_os_failed_repair(activation_result=activation_result, check_state=check_state, required_check_configuration_state=required_check_configuration_state, review_state=review_state, branch_freshness=branch_freshness, mergeability=mergeability)


@mcp.tool()
def classify_agent_os_mission_completion_tool(repository: str, issue_number: int, branch_exists: bool, implementation_commit_count: int, draft_pr_exists: bool, canonical_pr_readback_verified: bool, capable_route_available: bool, subordinate_writes_only: bool) -> dict[str, object]:
    return classify_agent_os_mission_completion(repository=repository, issue_number=issue_number, branch_exists=branch_exists, implementation_commit_count=implementation_commit_count, draft_pr_exists=draft_pr_exists, canonical_pr_readback_verified=canonical_pr_readback_verified, capable_route_available=capable_route_available, subordinate_writes_only=subordinate_writes_only)


@mcp.tool()
def classify_agent_os_continuation_tool(repository: str, issue_number: int, operation_id: str, surface_outcome: str, approved_alternative_capability: str | None = None, branch: str | None = None, pull_request: int | None = None, checkpoint_id: str | None = None, lease_id: str | None = None, prior_effect: str = "none-proven", target_identity_reacquired: bool = False, requires_exact_blob_identity: bool = False, exact_blob_identity_reacquired: bool = False, runtime_surface_transition: bool = False, evidence_compatibility_confirmed: bool = False, active_foreign_lease: bool = False, equivalent_transition_repeated: bool = False, material_decision_required: bool = False, alternative_widens_authority: bool = False, non_absorbed_domain: str | None = None) -> dict[str, object]:
    return classify_agent_os_continuation(repository=repository, issue_number=issue_number, operation_id=operation_id, surface_outcome=surface_outcome, approved_alternative_capability=approved_alternative_capability, branch=branch, pull_request=pull_request, checkpoint_id=checkpoint_id, lease_id=lease_id, prior_effect=prior_effect, target_identity_reacquired=target_identity_reacquired, requires_exact_blob_identity=requires_exact_blob_identity, exact_blob_identity_reacquired=exact_blob_identity_reacquired, runtime_surface_transition=runtime_surface_transition, evidence_compatibility_confirmed=evidence_compatibility_confirmed, active_foreign_lease=active_foreign_lease, equivalent_transition_repeated=equivalent_transition_repeated, material_decision_required=material_decision_required, alternative_widens_authority=alternative_widens_authority, non_absorbed_domain=non_absorbed_domain)
