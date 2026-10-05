"""Lane A (#3278): MCP completion routes forward live-consumer/successor evidence.

The facade (`classify_agent_os_mission_completion`) and the admission gate
(`evaluate_mission_completion_admission`) already model the ten
live-consumer/successor inputs, but `classify_agent_os_mission_completion_tool`
declared only nine parameters and `issue_batch_completion._classify_lane`
forwarded none, so through MCP `live_consumer_required` was always False.
These tests pin the plumbed connection.
"""
from __future__ import annotations

from agent_os_execution_service import mcp_server
from agent_os_execution_service.issue_batch_completion import classify_issue_batch_completion

REPOSITORY = "Blummer92/agent-os"


def _admissible_kwargs() -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "issue_number": 2765,
        "branch_exists": True,
        "implementation_commit_count": 2,
        "draft_pr_exists": True,
        "canonical_pr_readback_verified": True,
        "capable_route_available": True,
        "subordinate_writes_only": False,
        "canonical_pr_readback_binding": "readback-digest:canonical-pr:2765",
    }


def _pr_lane(issue: int, pr: int) -> dict[str, object]:
    return {
        "issue_number": issue,
        "current_state": "open-ready",
        "repository_gap": "yes",
        "implementation_authorized": True,
        "pr_required": "yes",
        "pr_number": pr,
        "remaining_owner": "GitHub Service Agent",
        "branch_exists": True,
        "implementation_commit_count": 1,
        "draft_pr_exists": True,
        "canonical_pr_readback_verified": True,
        "capable_route_available": True,
        "subordinate_writes_only": False,
        "canonical_pr_readback_binding": "readback-digest:canonical-pr:lane",
    }


def test_mcp_completion_tool_forwards_live_consumer_requirements() -> None:
    """Gap reproduction: tool must accept the live-consumer inputs.

    An otherwise repository-green mission whose issue contract requires a
    live consumer with unproven reachability must not be admitted through
    the MCP tool. Before the Lane A fix this call raised TypeError because
    the tool declared no live-consumer parameters at all.
    """
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2765",
        live_consumer_reachability_proven=False,
    )
    assert result["completion_admissible"] is False
    assert "required-live-consumer-reachability-not-proven" in result["reason_codes"]
    assert result["agent_os_continuation"]["terminal"] is False


def test_mcp_completion_tool_defaults_preserve_nine_param_callers() -> None:
    """The new live-consumer/successor params default to False/None."""
    plain = mcp_server.classify_agent_os_mission_completion_tool(**_admissible_kwargs())
    assert plain["completion_admissible"] is True
    assert "canonical-implementation-delivery-proven" in plain["reason_codes"]
    assert plain["agent_os_continuation"]["terminal"] is True


def test_mcp_completion_tool_accepts_proven_live_consumer() -> None:
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2765",
        live_consumer_reachability_proven=True,
        live_consumer_identity="chatgpt-host:agent-os",
        live_consumer_evidence_source="current-host-readback",
        live_consumer_evidence_current=True,
        live_consumer_evidence_kind="live-consumer-observation",
        live_consumer_observation_binding="observation-digest:live-consumer:chatgpt-host:agent-os",
    )
    assert result["completion_admissible"] is True
    assert "required-live-consumer-current-observation-proven" in result["reason_codes"]


def test_mcp_completion_tool_accepts_successor_owned_residual_acceptance() -> None:
    """Successor delegation pass: a current successor that owns residual live
    acceptance satisfies the live-consumer requirement for this child."""
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2525",
        successor_issue_number=2673,
        successor_current=True,
        successor_owns_residual_live_acceptance=True,
    )
    assert result["completion_admissible"] is True
    assert "residual-live-acceptance-owned-by-current-successor" in result["reason_codes"]


def test_mcp_completion_tool_refuses_partial_successor_delegation() -> None:
    """Successor delegation fail: a named but stale successor proves nothing."""
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2525",
        successor_issue_number=2673,
        successor_current=False,
        successor_owns_residual_live_acceptance=True,
    )
    assert result["completion_admissible"] is False
    assert "residual-live-successor-currentness-not-proven" in result["reason_codes"]


def test_batch_lane_forwards_live_consumer_requirements_per_lane() -> None:
    """Gap reproduction: a PR lane whose issue contract requires a live
    consumer must not terminalize through the batch tool when reachability
    is unproven. Before the fix this lane terminalized as True."""
    lanes = [_pr_lane(3278, 3280)]
    lanes[0]["live_consumer_required"] = True
    lanes[0]["live_consumer_requirement_source"] = "issue-contract:#3278"
    result = classify_issue_batch_completion(
        repository=REPOSITORY, issue_number=3277, lane_evidence=lanes
    )
    assert result["terminal"] is False
    assert result["unfinished_issue_numbers"] == [3278]
    assert "required-live-consumer-reachability-not-proven" in result["lanes"][0]["reason_codes"]


def test_batch_lane_forwards_live_consumer_successor_pass_per_lane() -> None:
    lanes = [_pr_lane(2525, 2526)]
    lanes[0]["live_consumer_required"] = True
    lanes[0]["live_consumer_requirement_source"] = "issue-contract:#2525"
    lanes[0]["successor_issue_number"] = 2673
    lanes[0]["successor_current"] = True
    lanes[0]["successor_owns_residual_live_acceptance"] = True
    result = classify_issue_batch_completion(
        repository=REPOSITORY, issue_number=2524, lane_evidence=lanes
    )
    assert result["terminal"] is True
    assert "residual-live-acceptance-owned-by-current-successor" in result["lanes"][0]["reason_codes"]


def test_batch_live_consumer_evidence_is_per_lane_not_mission_level() -> None:
    """Heterogeneous lanes must not homogenize: lane A requires a proven
    live consumer, lane B (repository-only) must still terminalize."""
    lane_a = _pr_lane(3278, 3280)
    lane_a["live_consumer_required"] = True
    lane_a["live_consumer_requirement_source"] = "issue-contract:#3278"
    lane_b = _pr_lane(2600, 2606)
    result = classify_issue_batch_completion(
        repository=REPOSITORY, issue_number=3277, lane_evidence=[lane_a, lane_b]
    )
    assert result["terminal"] is False
    assert result["unfinished_issue_numbers"] == [3278]
    assert result["lanes"][1]["terminal"] is True


def test_batch_tool_no_pr_lane_ignores_live_consumer_keys() -> None:
    """The no-PR lane path never calls admission, so per-lane live-consumer
    keys are naturally a no-op there."""
    result = mcp_server.classify_agent_os_issue_batch_completion_tool(
        repository=REPOSITORY,
        issue_number=2607,
        lane_evidence=[
            {
                "issue_number": 1386,
                "current_state": "open-external-boundary",
                "repository_gap": "no",
                "implementation_authorized": False,
                "pr_required": "no",
                "no_pr_reason": "external-only",
                "canonical_no_pr_evidence_verified": True,
                "remaining_owner": "ChatGPT Orchestrator",
                "live_consumer_required": True,
            },
        ],
    )
    assert result["terminal"] is True
    assert result["lanes"][0]["reason_codes"] == ["no-pr-terminal:external-only"]


def test_batch_tool_rejects_live_consumer_gap_through_mcp_tool() -> None:
    """End-to-end through `classify_agent_os_issue_batch_completion_tool`."""
    lane = _pr_lane(3278, 3280)
    lane["live_consumer_required"] = True
    lane["live_consumer_requirement_source"] = "issue-contract:#3278"
    result = mcp_server.classify_agent_os_issue_batch_completion_tool(
        repository=REPOSITORY, issue_number=3277, lane_evidence=[lane]
    )
    assert result["terminal"] is False
    assert "required-live-consumer-reachability-not-proven" in result["lanes"][0]["reason_codes"]


# False-completion fixtures modelled on closed false-completion history.
# Each models repository-green delivery refused completion because no
# live-host observation backs the completion claim.


def test_false_completion_hostless_consumer_2731() -> None:
    """#2731: classifier consumed only by a hostless caller — no live
    consumer reachability was ever proven."""
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2731",
        live_consumer_reachability_proven=False,
    )
    assert result["completion_admissible"] is False
    assert "required-live-consumer-reachability-not-proven" in result["reason_codes"]


def test_false_completion_no_composition_seam_1456() -> None:
    """#1456: no pre-PR composition seam — reachability was claimed but no
    live consumer identity was tied to the observation."""
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#1456",
        live_consumer_reachability_proven=True,
        live_consumer_identity=None,
    )
    assert result["completion_admissible"] is False
    assert "required-live-consumer-identity-not-proven" in result["reason_codes"]


def test_false_completion_uncalled_publication_route_687() -> None:
    """#687: uncalled publication route — a live consumer was observed once
    but the observation is no longer current."""
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#687",
        live_consumer_reachability_proven=True,
        live_consumer_identity="chatgpt-host:agent-os",
        live_consumer_evidence_source="stale-host-readback",
        live_consumer_evidence_current=False,
        live_consumer_evidence_kind="live-consumer-observation",
    )
    assert result["completion_admissible"] is False
    assert "required-live-consumer-evidence-not-current" in result["reason_codes"]


def test_false_completion_zero_production_importers_2992() -> None:
    """#2992: zero production importers — current evidence exists but it is
    repository-only (unit tests), not live-host observation."""
    result = mcp_server.classify_agent_os_mission_completion_tool(
        **_admissible_kwargs(),
        live_consumer_required=True,
        live_consumer_requirement_source="issue-contract:#2992",
        live_consumer_reachability_proven=True,
        live_consumer_identity="chatgpt-host:agent-os",
        live_consumer_evidence_source="pytest-run",
        live_consumer_evidence_current=True,
        live_consumer_evidence_kind="unit-tests",
    )
    assert result["completion_admissible"] is False
    assert "required-live-consumer-evidence-not-live-observation" in result["reason_codes"]


def test_false_completion_batch_lane_2731() -> None:
    """The batch path refuses the same false completion per lane."""
    lane = _pr_lane(2731, 2732)
    lane["live_consumer_required"] = True
    lane["live_consumer_requirement_source"] = "issue-contract:#2731"
    result = classify_issue_batch_completion(
        repository=REPOSITORY, issue_number=2730, lane_evidence=[lane]
    )
    assert result["terminal"] is False
    assert result["unfinished_issue_numbers"] == [2731]
