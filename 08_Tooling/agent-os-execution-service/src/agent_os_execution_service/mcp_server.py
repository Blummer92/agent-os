"""MCP protocol binding for the bounded Agent OS ChatGPT facade (#1966).

The server exposes only two non-authorizing tools.  It performs no GitHub write,
checkpoint-store access, Scheduler dispatch, shell execution, network discovery,
or provider invocation.  Hosting/authentication remain a separately authorized
external activation concern.
"""

from __future__ import annotations

from mcp.server import MCPServer

from .mcp_facade import classify_agent_os_continuation, plan_agent_os_continuation

mcp = MCPServer("Agent OS")


@mcp.tool()
def plan_agent_os_continuation_tool(
    repository: str,
    issue_number: int,
    canonical_handoff_id: str | None = None,
) -> dict[str, object]:
    """Plan one bounded Agent OS continuation from canonical structured identity.

    A supplied handoff must already come from canonical Agent OS tool evidence.
    This tool never discovers or fabricates one and never grants execution/write
    authority.
    """

    return dict(
        plan_agent_os_continuation(
            repository=repository,
            issue_number=issue_number,
            canonical_handoff_id=canonical_handoff_id,
        )
    )


@mcp.tool()
def classify_agent_os_continuation_tool(
    repository: str,
    issue_number: int,
    operation_id: str,
    surface_outcome: str,
    approved_alternative_capability: str | None = None,
    branch: str | None = None,
    pull_request: int | None = None,
    checkpoint_id: str | None = None,
    lease_id: str | None = None,
    prior_effect: str = "none-proven",
    target_identity_reacquired: bool = False,
    requires_exact_blob_identity: bool = False,
    exact_blob_identity_reacquired: bool = False,
    runtime_surface_transition: bool = False,
    evidence_compatibility_confirmed: bool = False,
    active_foreign_lease: bool = False,
    equivalent_transition_repeated: bool = False,
    material_decision_required: bool = False,
    alternative_widens_authority: bool = False,
    non_absorbed_domain: str | None = None,
) -> dict[str, object]:
    """Classify one insufficient action through the existing #1237 contract."""

    return classify_agent_os_continuation(
        repository=repository,
        issue_number=issue_number,
        operation_id=operation_id,
        surface_outcome=surface_outcome,
        approved_alternative_capability=approved_alternative_capability,
        branch=branch,
        pull_request=pull_request,
        checkpoint_id=checkpoint_id,
        lease_id=lease_id,
        prior_effect=prior_effect,
        target_identity_reacquired=target_identity_reacquired,
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
