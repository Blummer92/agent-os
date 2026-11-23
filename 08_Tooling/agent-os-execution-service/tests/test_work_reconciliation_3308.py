"""#3308: real host-facing request-triage consumer and issue-create gate."""
from __future__ import annotations

from agent_os_execution_service import mcp_server


def evidence(**changes):
    payload = {
        "subject": "Repair worksheet visual placement",
        "github_search_complete": True,
        "github_issue_evidence_current": True,
        "pr_lineage_evidence_current": True,
        "capability_registry_evidence_current": True,
        "lineage": [],
        "capabilities": [],
        "navigation_applicable": False,
        "navigation_evidence_current": True,
        "navigation_outcome": None,
    }
    payload.update(changes)
    return payload


def test_merged_implementation_open_owner_reused_not_new_work():
    item = evidence(lineage=[{
        "issue_number": 3306, "state": "open", "match": "exact",
        "lifecycle_stage": "merged",
    }])
    result = mcp_server.reconcile_agent_os_proposed_work_tool(item)
    assert result["disposition"] == "reuse-current-owner"
    assert result["owner_issue_number"] == 3306
    assert result["authorizes_issue_creation"] is False
    assert result["execution_authorized"] is False


def test_draft_owner_continues_instead_of_duplicate_work():
    item = evidence(lineage=[{
        "issue_number": 3258, "state": "open", "match": "exact",
        "lifecycle_stage": "draft-pr",
    }])
    result = mcp_server.reconcile_agent_os_proposed_work_tool(item)
    assert result["disposition"] == "continue-current-work"
    assert result["owner_issue_number"] == 3258


def test_merged_completed_history_is_not_actionable():
    result = mcp_server.reconcile_agent_os_proposed_work_tool(evidence(lineage=[{
        "issue_number": 3585, "state": "closed", "state_reason": "completed",
        "match": "exact",
    }]))
    assert result["disposition"] == "historical-regression-evidence"
    assert result["owner_issue_number"] is None


def test_registry_reuse_precedes_new_work():
    result = mcp_server.reconcile_agent_os_proposed_work_tool(
        evidence(capabilities=[{"capability_id": "navigation-index-reader", "status": "active"}])
    )
    assert result["disposition"] == "extend-existing-capability"


def test_complete_no_match_is_non_authorizing_candidate_only():
    result = mcp_server.reconcile_agent_os_proposed_work_tool(evidence())
    assert result["disposition"] == "candidate-new-work"
    assert result["authorizes_issue_creation"] is False
    assert result["execution_authorized"] is False


def test_missing_incomplete_or_stale_evidence_fails_closed():
    for patch in (
        {"github_search_complete": False},
        {"github_issue_evidence_current": False},
        {"pr_lineage_evidence_current": False},
        {"capability_registry_evidence_current": False},
        {"lineage": None},
        {"capabilities": [{"status": "active"}]},
        {"lineage": [{"issue_number": 3307, "state": "open", "match": "exact"},
                     {"issue_number": 3307, "state": "closed", "state_reason": "completed", "match": "exact"}]},
        {"navigation_applicable": True, "navigation_evidence_current": False,
         "navigation_outcome": "no-cached-match"},
    ):
        result = mcp_server.reconcile_agent_os_proposed_work_tool(evidence(**patch))
        assert result["disposition"] == "manual-review", patch
        assert result["authorizes_issue_creation"] is False


def test_conditional_navigation_stale_cannot_create_work():
    result = mcp_server.reconcile_agent_os_proposed_work_tool(evidence(
        navigation_applicable=True,
        navigation_outcome="stale-or-unverified",
    ))
    assert result["disposition"] == "manual-review"


def test_connected_create_plan_blocks_on_current_owner_before_bug_admission():
    result = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body="## Summary\\nCanonical issue body required.",
        reconciliation_evidence=evidence(lineage=[{
            "issue_number": 3307, "state": "open",
            "match": "exact", "lifecycle_stage": "merged",
        }]),
    )
    assert result["create_allowed"] is False
    assert result["work_reconciliation"]["owner_issue_number"] == 3307
    assert result["side_effects_performed"] is False


def test_candidate_does_not_bypass_existing_duplicate_admission():
    result = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body="## Summary\\nCanonical issue body required.",
        reconciliation_evidence=evidence(),
    )
    assert result["create_allowed"] is False
    assert result["work_reconciliation"]["disposition"] == "candidate-new-work"


def test_missing_navigation_package_fails_closed_without_server_startup_failure(monkeypatch):
    """Host wheels that lack Navigation Registry must not crash unrelated MCP tools."""
    import builtins

    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "navigation_registry.reconciliation":
            raise ModuleNotFoundError("No module named 'navigation_registry'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    output = mcp_server.reconcile_agent_os_proposed_work_tool(evidence())
    assert output["disposition"] == "manual-review"
    assert "triage.canonical-classifier-unavailable" in output["reason_codes"]
    assert output["execution_authorized"] is False
    assert output["authorizes_issue_creation"] is False
    assert output["source_evidence_complete"] is False
