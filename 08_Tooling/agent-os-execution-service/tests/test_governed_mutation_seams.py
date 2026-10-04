"""MCP seam tools for the governed GitHub mutation guard/readback contracts (#3281).

Reproduction first: ``comment_mutation_readback`` (#2785),
``defect_evidence_mutation_guard`` (#2741), and
``lane_post_pr_issue_reconciliation`` (#2791) are pure contracts with no host
consumer. These tests prove each seam is reachable from the registered MCP
surface and that the seam semantics hold end to end through the tools.

Every test in this file fails before the seam tools are registered.
"""
from __future__ import annotations

import pytest

from agent_os_execution_service import mcp_server


# ---------------------------------------------------------------------------
# Seam 1: issue-comment write boundary
# (pre-write guard #2741 + post-write readback #2785)
# ---------------------------------------------------------------------------

def test_3281_seam1_unknown_phase_fails_closed() -> None:
    with pytest.raises(ValueError, match="phase must be one of"):
        mcp_server.admit_agent_os_issue_comment_mutation_tool(
            phase="write",
            issue_number=3281,
        )


def test_3281_seam2_unknown_phase_fails_closed() -> None:
    with pytest.raises(ValueError, match="phase must be one of"):
        mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
            phase="reconcile",
            issue_number=3281,
        )

def test_3281_seam1_guard_tool_registered_on_mcp_surface() -> None:
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3281,
        evidence_kind="defect",
        target_open=True,
        state_current=True,
    )
    assert result["decision"] == "admitted"
    assert result["reason_codes"] == ["mutation.target-open-verified"]
    assert result["side_effects_performed"] is False
    assert result["github_writes_authorized"] is False


def test_3281_seam1_guard_refuses_closed_issue_routes_to_open_owner() -> None:
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3100,
        evidence_kind="defect",
        target_open=False,
        state_current=True,
        open_owner_issue_number=3102,
        historical_lineage_issue_number=3100,
    )
    assert result["decision"] == "refused"
    assert result["directive"] == "route-to-open-owner"
    assert result["open_owner_issue_number"] == 3102
    assert result["reason_codes"] == [
        "mutation.target-closed-historical-only",
        "mutation.route-to-open-owner",
    ]
    assert result["agent_os_continuation"]["action"] == "route-evidence-to-open-owner"
    assert result["agent_os_continuation"]["blocked"] is False
    assert result["side_effects_performed"] is False


def test_3281_seam1_guard_refuses_stale_state_for_reacquire() -> None:
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3281,
        evidence_kind="process",
        target_open=True,
        state_current=False,
    )
    assert result["decision"] == "refused"
    assert result["directive"] == "reacquire-target-state"
    assert result["reason_codes"] == ["mutation.target-state-not-current"]
    assert result["agent_os_continuation"]["action"] == "reacquire-target-state-before-write"


def test_3281_seam1_guard_refuses_closed_issue_without_owner_creates_new_bug() -> None:
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3100,
        evidence_kind="defect",
        target_open=False,
        state_current=True,
    )
    assert result["decision"] == "refused"
    assert result["directive"] == "create-new-bug"
    assert result["reason_codes"] == [
        "mutation.target-closed-historical-only",
        "mutation.no-open-owner-create-new-bug",
    ]
    assert result["agent_os_continuation"]["action"] == "create-new-bug-for-evidence"


def test_3281_seam1_subordinate_comment_persisted_only_after_canonical_readback() -> None:
    body = "subordinate evidence write"
    readback = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="post-write-readback",
        issue_number=3281,
        intended_body=body,
        provider_reported_success=True,
        readback_complete=True,
        comments=[
            {"comment_id": 901, "issue_number": 3281, "body": body},
        ],
    )
    assert readback["status"] == "persisted"
    assert readback["persisted_comment_id"] == 901
    assert readback["retry_safe"] is False
    assert readback["reason_codes"] == ["readback.persisted"]
    assert readback["agent_os_continuation"]["terminal"] is True
    assert readback["side_effects_performed"] is False


def test_3281_seam1_provider_success_alone_never_reports_persisted() -> None:
    readback = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="post-write-readback",
        issue_number=3281,
        intended_body="subordinate evidence write",
        provider_reported_success=True,
        readback_complete=True,
        comments=[],
    )
    assert readback["status"] == "not-persisted"
    assert readback["persisted_comment_id"] is None
    assert readback["retry_safe"] is True
    assert readback["reason_codes"] == ["provider-success-without-persistence"]
    assert readback["agent_os_continuation"]["terminal"] is False
    assert readback["agent_os_continuation"]["action"] == "retry-write-once"


def test_3281_seam1_incomplete_readback_never_reports_persisted() -> None:
    readback = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="post-write-readback",
        issue_number=3281,
        intended_body="subordinate evidence write",
        provider_reported_success=True,
        readback_complete=False,
        comments=[],
    )
    assert readback["status"] == "uncertain"
    assert readback["persisted_comment_id"] is None
    assert readback["reason_codes"] == ["readback.incomplete"]
    assert readback["agent_os_continuation"]["action"] == "reconcile-manually-no-automatic-retry"


def test_3281_seam1_uncertain_duplicate_content_never_retries() -> None:
    body = "subordinate evidence write"
    readback = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="post-write-readback",
        issue_number=3281,
        intended_body=body,
        provider_reported_success=True,
        readback_complete=True,
        comments=[
            {"comment_id": 901, "issue_number": 3281, "body": body},
            {"comment_id": 902, "issue_number": 3281, "body": body},
        ],
    )
    assert readback["status"] == "uncertain"
    assert readback["reason_codes"] == ["readback.duplicate-content"]
    assert readback["retry_safe"] is False
    assert readback["agent_os_continuation"]["action"] == "reconcile-manually-no-automatic-retry"


# ---------------------------------------------------------------------------
# Seam 2: Safe Implementation Lane post-PR issue reconciliation (#2791)
# ---------------------------------------------------------------------------

def _seam2_evidence(**overrides):
    evidence = {
        "issue_number": 3281,
        "issue_open": True,
        "lifecycle_labels": ["status:ready"],
        "linked_pull_request_number": 3300,
        "pr_state": "draft",
        "pr_head_sha": "a" * 40,
        "pr_readback_current": True,
        "closure_authorized": False,
        "evidence_current": True,
    }
    evidence.update(overrides)
    return evidence


def test_3281_seam2_plan_tool_registered_on_mcp_surface() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        **_seam2_evidence(),
    )
    assert plan["disposition"] == "reconcile-ready-awaiting-closure-authority"
    assert plan["expected_mutations"] == ["remove-lifecycle-label"]
    assert plan["ready_label"] == "status:ready"
    assert plan["readback_required"] is True
    assert plan["fully_reconciled"] is False
    assert plan["merge_authorized"] is False
    assert plan["ready_authorized"] is False
    assert plan["side_effects_performed"] is False


def test_3281_seam2_reconciliation_cannot_grant_ready_or_merge() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        **_seam2_evidence(closure_authorized=True),
    )
    assert plan["disposition"] == "reconcile-ready-and-close"
    assert plan["expected_mutations"] == ["remove-lifecycle-label", "close-issue"]
    assert plan["ready_authorized"] is False
    assert plan["merge_authorized"] is False


def test_3281_seam2_stale_ready_never_reports_fully_reconciled() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        **_seam2_evidence(),
    )
    proof = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="readback-proof",
        issue_number=3281,
        issue_open=True,
        lifecycle_labels=["status:ready"],
        evidence_current=True,
        plan=plan,
    )
    assert proof["fully_reconciled"] is False
    assert proof["reason_codes"] == ["lane-post-pr.ready-still-present"]
    assert proof["agent_os_continuation"]["terminal"] is False


def test_3281_seam2_open_issue_without_closure_never_reports_fully_reconciled() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        **_seam2_evidence(),
    )
    proof = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="readback-proof",
        issue_number=3281,
        issue_open=True,
        lifecycle_labels=[],
        evidence_current=True,
        plan=plan,
    )
    assert proof["fully_reconciled"] is False
    assert proof["reason_codes"] == ["lane-post-pr.closure-authority-still-missing"]


def test_3281_seam2_closed_issue_after_authorized_close_proves_reconciled() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        **_seam2_evidence(closure_authorized=True),
    )
    assert plan["agent_os_continuation"]["action"] == "perform-expected-mutations-then-canonical-readback"
    proof = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="readback-proof",
        issue_number=3281,
        issue_open=False,
        lifecycle_labels=[],
        evidence_current=True,
        plan=plan,
    )
    assert proof["fully_reconciled"] is True
    assert proof["reason_codes"] == ["lane-post-pr.issue-closed"]
    assert proof["agent_os_continuation"]["terminal"] is True


def test_3281_seam2_needs_decision_blocks_without_manual_action() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        **_seam2_evidence(evidence_current=False),
    )
    assert plan["disposition"] == "needs-decision"
    assert plan["fully_reconciled"] is False
    assert plan["agent_os_continuation"]["blocked"] is True
    proof = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="readback-proof",
        issue_number=3281,
        issue_open=True,
        lifecycle_labels=["status:ready"],
        evidence_current=True,
        plan=plan,
    )
    assert proof["fully_reconciled"] is False
    assert proof["reason_codes"] == ["lane-post-pr.plan-was-needs-decision"]
