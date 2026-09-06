"""MCP protocol binding for the bounded Agent OS ChatGPT facade (#1966 / #1988)."""

from __future__ import annotations

from mcp.server import MCPServer

from .mcp_facade import activate_agent_os_failed_repair, classify_agent_os_continuation, plan_agent_os_continuation

mcp = MCPServer("Agent OS")


@mcp.tool()
def plan_agent_os_continuation_tool(repository: str, issue_number: int, canonical_handoff_id: str | None = None) -> dict[str, object]:
    return dict(plan_agent_os_continuation(repository=repository, issue_number=issue_number, canonical_handoff_id=canonical_handoff_id))


@mcp.tool()
def activate_agent_os_failed_repair_tool(
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
    lesson_rows: list[dict[str, object]] | None = None,
    repair_context: str = "failed-pr-repair",
) -> dict[str, object]:
    """Execute canonical CKR6 for one failed attempt using bounded read evidence.

    ``lesson_rows`` is the result of the existing read-only Lessons Learned
    connector operation selected by CKR6/CKR11. It is not trusted as authority:
    the canonical activation bridge still normalizes, bounds, verifies
    provenance/currentness, and selects it. Omitting rows when material retrieval
    is required fails closed rather than treating policy text as activation.
    """
    execute_read = None if lesson_rows is None else lambda _query: {"results": lesson_rows}
    return activate_agent_os_failed_repair(
        repository=repository, issue_number=issue_number, attempt_id=attempt_id,
        failed_hypothesis=failed_hypothesis, result_summary=result_summary,
        task_reference=task_reference, ecosystem_hints=ecosystem_hints,
        language_hints=language_hints, library_hints=library_hints,
        capability_keywords=capability_keywords, target_path_hints=target_path_hints,
        canonical_rule_refs=canonical_rule_refs, known_knowledge_refs=known_knowledge_refs,
        specialized_knowledge_required=specialized_knowledge_required,
        execute_read=execute_read, repair_context=repair_context,
    )


@mcp.tool()
def classify_agent_os_continuation_tool(
    repository: str, issue_number: int, operation_id: str, surface_outcome: str,
    approved_alternative_capability: str | None = None, branch: str | None = None,
    pull_request: int | None = None, checkpoint_id: str | None = None,
    lease_id: str | None = None, prior_effect: str = "none-proven",
    target_identity_reacquired: bool = False, requires_exact_blob_identity: bool = False,
    exact_blob_identity_reacquired: bool = False, runtime_surface_transition: bool = False,
    evidence_compatibility_confirmed: bool = False, active_foreign_lease: bool = False,
    equivalent_transition_repeated: bool = False, material_decision_required: bool = False,
    alternative_widens_authority: bool = False, non_absorbed_domain: str | None = None,
) -> dict[str, object]:
    return classify_agent_os_continuation(
        repository=repository, issue_number=issue_number, operation_id=operation_id,
        surface_outcome=surface_outcome, approved_alternative_capability=approved_alternative_capability,
        branch=branch, pull_request=pull_request, checkpoint_id=checkpoint_id, lease_id=lease_id,
        prior_effect=prior_effect, target_identity_reacquired=target_identity_reacquired,
        requires_exact_blob_identity=requires_exact_blob_identity,
        exact_blob_identity_reacquired=exact_blob_identity_reacquired,
        runtime_surface_transition=runtime_surface_transition,
        evidence_compatibility_confirmed=evidence_compatibility_confirmed,
        active_foreign_lease=active_foreign_lease,
        equivalent_transition_repeated=equivalent_transition_repeated,
        material_decision_required=material_decision_required,
        alternative_widens_authority=alternative_widens_authority,
        non_absorbed_domain=non_absorbed_domain,
    )
