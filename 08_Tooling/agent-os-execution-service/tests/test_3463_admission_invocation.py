"""Admission invocation tests for the governed mutation seams (#3463).

Problem shape: the two governed mutation seams are *registered* on the MCP
surface (``admit_agent_os_issue_comment_mutation_tool``,
``project_agent_os_lane_post_pr_issue_reconciliation_tool``) but registration
is not attachment and route existence does not grant mutation authority.
A test that merely asserts a tool name resolves proves nothing.

These tests EXECUTE both tools end to end:

- the entry guard runs before any seam logic (invalid operation identity is
  refused fail-closed and the implementation is never reached);
- the tool forwards the exact expected call to its seam implementation
  (a recording fake proves the wiring — a merely-registered stub would fail);
- the admission contract holds: authorized invocations are admitted with a
  canonical receipt, out-of-scope operations are refused, and no tool path
  ever authorizes a GitHub write or performs a side effect.
"""
from __future__ import annotations

import pytest

from agent_os_execution_service import mcp_server


# ---------------------------------------------------------------------------
# Wiring: the tool must be connected to its implementation, not just registered
# ---------------------------------------------------------------------------

def test_3463_seam1_tool_forwards_exact_call_to_implementation(monkeypatch) -> None:
    """A stub that only resolves the tool name would never call the fake."""
    calls: list[dict[str, object]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"_fake_receipt": True, "echoed_kwargs": kwargs}

    monkeypatch.setattr(
        mcp_server, "evaluate_issue_comment_mutation_boundary_for_host", fake
    )
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3281,
        evidence_kind="defect",
        target_open=True,
        state_current=True,
        open_owner_issue_number=3102,
        historical_lineage_issue_number=3100,
    )
    assert len(calls) == 1
    assert calls[0] == {
        "phase": "pre-write-guard",
        "issue_number": 3281,
        "evidence_kind": "defect",
        "target_open": True,
        "state_current": True,
        "open_owner_issue_number": 3102,
        "historical_lineage_issue_number": 3100,
        "intended_body": None,
        "provider_reported_success": None,
        "readback_complete": False,
        "comments": (),
    }
    # The tool returns the implementation's payload, not canned data.
    assert result["_fake_receipt"] is True


def test_3463_seam2_tool_forwards_exact_call_to_implementation(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"_fake_receipt": True}

    monkeypatch.setattr(
        mcp_server, "project_lane_post_pr_issue_reconciliation_for_host", fake
    )
    result = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        issue_number=3281,
        issue_open=True,
        lifecycle_labels=["status:ready"],
        linked_pull_request_number=3300,
        pr_state="draft",
        pr_head_sha="a" * 40,
        pr_readback_current=True,
        closure_authorized=False,
        evidence_current=True,
    )
    assert len(calls) == 1
    assert calls[0] == {
        "phase": "plan",
        "issue_number": 3281,
        "issue_open": True,
        "lifecycle_labels": ("status:ready",),
        "linked_pull_request_number": 3300,
        "pr_state": "draft",
        "pr_head_sha": "a" * 40,
        "pr_readback_current": True,
        "closure_authorized": False,
        "evidence_current": True,
        "plan": None,
        "repository": None,
        "state_reason": None,
    }
    assert result["_fake_receipt"] is True


def test_3463_entry_guard_runs_before_implementation_on_both_tools(monkeypatch) -> None:
    """Invalid operation identity must raise before the seam implementation runs."""
    calls: list[dict[str, object]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"_fake_receipt": True}

    monkeypatch.setattr(
        mcp_server, "evaluate_issue_comment_mutation_boundary_for_host", fake
    )
    monkeypatch.setattr(
        mcp_server, "project_lane_post_pr_issue_reconciliation_for_host", fake
    )
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server.admit_agent_os_issue_comment_mutation_tool(
            phase="pre-write-guard",
            issue_number=0,
        )
    assert exc_info.value.reason_code == "github-target-number-invalid"
    with pytest.raises(mcp_server.GitHubTargetRefused):
        mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
            phase="plan",
            issue_number=3281,
            linked_pull_request_number=-5,
        )
    assert calls == []


# ---------------------------------------------------------------------------
# Admission contract: invalid operation identity fails closed, no mutation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_number", [0, -1, -2**31, True, "3281", 3.0, None])
def test_3463_seam1_invalid_issue_identity_refused_fail_closed(bad_number) -> None:
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server.admit_agent_os_issue_comment_mutation_tool(
            phase="pre-write-guard",
            issue_number=bad_number,
        )
    assert exc_info.value.reason_code in {
        "github-target-ambiguous-or-missing",
        "github-target-number-invalid",
    }


def test_3463_seam1_invalid_owner_identity_refused_fail_closed() -> None:
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server.admit_agent_os_issue_comment_mutation_tool(
            phase="pre-write-guard",
            issue_number=3281,
            target_open=False,
            open_owner_issue_number=0,
        )
    assert exc_info.value.reason_code == "github-target-number-invalid"


def test_3463_seam2_invalid_pr_identity_refused_fail_closed() -> None:
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
            phase="plan",
            issue_number=3281,
            linked_pull_request_number=0 - 1,
        )
    assert exc_info.value.reason_code == "github-target-number-invalid"


def test_3463_target_guard_refuses_kind_incompatible_operation() -> None:
    """Route existence does not grant mutation authority: an issue target can
    never be admitted into a pull-request-scoped operation (or vice versa)."""
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server._github_target_entry_guard(
            repository=None,
            issue_number=3281,
            operation="merge-pull-request",
        )
    assert exc_info.value.reason_code == "github-target-kind-incompatible"
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server._github_target_entry_guard(
            repository=None,
            pr_number=3300,
            operation="update-issue",
        )
    assert exc_info.value.reason_code == "github-target-kind-incompatible"


def test_3463_target_guard_rejects_ambiguous_or_missing_target() -> None:
    with pytest.raises(mcp_server.GitHubTargetRefused) as exc_info:
        mcp_server._github_target_entry_guard(
            repository=None,
            issue_number=3281,
            pr_number=3300,
            operation="read-issue",
        )
    assert exc_info.value.reason_code == "github-target-ambiguous-or-missing"


# ---------------------------------------------------------------------------
# Admission contract: out-of-scope operations are refused
# ---------------------------------------------------------------------------

def test_3463_seam1_reconciliation_cannot_be_reached_through_comment_tool() -> None:
    """The comment tool's admitted scope is exactly its two phases; anything
    else fails closed before any seam logic runs."""
    with pytest.raises(ValueError, match="phase must be one of"):
        mcp_server.admit_agent_os_issue_comment_mutation_tool(
            phase="admit-merge",
            issue_number=3281,
        )


def test_3463_seam1_readback_phase_requires_intended_body() -> None:
    with pytest.raises(ValueError, match="intended_body is required"):
        mcp_server.admit_agent_os_issue_comment_mutation_tool(
            phase="post-write-readback",
            issue_number=3281,
        )


def test_3463_seam2_plan_never_grants_merge_or_ready_authority() -> None:
    """Even a fully authorized reconciliation plan grants no merge/Ready
    authority and performs no side effects."""
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        issue_number=3281,
        issue_open=True,
        lifecycle_labels=["status:ready"],
        linked_pull_request_number=3300,
        pr_state="merged",
        pr_head_sha="b" * 40,
        pr_readback_current=True,
        closure_authorized=True,
        evidence_current=True,
    )
    assert plan["merge_authorized"] is False
    assert plan["ready_authorized"] is False
    assert plan["github_writes_authorized"] is False
    assert plan["side_effects_performed"] is False


def test_3463_seam2_readback_phase_requires_plan() -> None:
    with pytest.raises(ValueError, match="plan is required"):
        mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
            phase="readback-proof",
            issue_number=3281,
        )


# ---------------------------------------------------------------------------
# Admission contract: authorized invocation admitted with canonical receipt
# ---------------------------------------------------------------------------

def test_3463_seam1_authorized_invocation_admitted_with_receipt() -> None:
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3281,
        evidence_kind="defect",
        target_open=True,
        state_current=True,
    )
    assert result["decision"] == "admitted"
    assert result["reason_codes"] == ["mutation.target-open-verified"]
    # Canonical receipt: the continuation payload the host must carry forward.
    continuation = result["agent_os_continuation"]
    assert continuation["terminal"] is False
    assert continuation["blocked"] is False
    assert continuation["action"] == "proceed-with-write-then-canonical-readback"
    # The tool admits the guard decision; it never authorizes the write itself.
    assert result["github_writes_authorized"] is False
    assert result["side_effects_performed"] is False


def test_3463_seam1_refused_invocation_carries_directive_not_authority() -> None:
    result = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3100,
        evidence_kind="defect",
        target_open=False,
        state_current=True,
    )
    assert result["decision"] == "refused"
    assert result["directive"] == "create-new-bug"
    assert result["github_writes_authorized"] is False
    assert result["side_effects_performed"] is False


def test_3463_seam2_authorized_plan_admitted_with_receipt() -> None:
    plan = mcp_server.project_agent_os_lane_post_pr_issue_reconciliation_tool(
        phase="plan",
        issue_number=3281,
        issue_open=True,
        lifecycle_labels=["status:ready"],
        linked_pull_request_number=3300,
        pr_state="draft",
        pr_head_sha="a" * 40,
        pr_readback_current=True,
        closure_authorized=False,
        evidence_current=True,
    )
    assert plan["disposition"] == "reconcile-ready-awaiting-closure-authority"
    assert plan["readback_required"] is True
    assert plan["agent_os_continuation"]["action"] == (
        "perform-expected-mutations-then-canonical-readback"
    )
    assert plan["github_writes_authorized"] is False
    assert plan["side_effects_performed"] is False


# ---------------------------------------------------------------------------
# Pre-write guard path exercised end to end (the seam a generic write bypasses)
# ---------------------------------------------------------------------------

def test_3463_seam1_full_guard_then_readback_lifecycle() -> None:
    """The path a generic issue-comment write bypasses: pre-write admission,
    then canonical post-write readback proving persistence."""
    admitted = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="pre-write-guard",
        issue_number=3281,
        evidence_kind="defect",
        target_open=True,
        state_current=True,
    )
    assert admitted["decision"] == "admitted"

    body = "governed subordinate evidence"
    readback = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="post-write-readback",
        issue_number=3281,
        intended_body=body,
        provider_reported_success=True,
        readback_complete=True,
        comments=[
            {"comment_id": 4242, "issue_number": 3281, "body": body},
        ],
    )
    assert readback["status"] == "persisted"
    assert readback["persisted_comment_id"] == 4242
    assert readback["agent_os_continuation"]["terminal"] is True
    assert readback["side_effects_performed"] is False


def test_3463_seam1_readback_detects_body_mismatch_without_admission_assumption() -> None:
    """The readback seam verifies canonically; it never assumes the admitted
    write happened."""
    readback = mcp_server.admit_agent_os_issue_comment_mutation_tool(
        phase="post-write-readback",
        issue_number=3281,
        intended_body="governed subordinate evidence",
        provider_reported_success=True,
        readback_complete=True,
        comments=[
            {"comment_id": 4242, "issue_number": 3281, "body": "something else"},
        ],
    )
    assert readback["status"] == "not-persisted"
    assert readback["persisted_comment_id"] is None
    assert readback["agent_os_continuation"]["terminal"] is False
