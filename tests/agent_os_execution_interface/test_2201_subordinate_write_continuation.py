from scripts.agent_os_execution_interface.mission_completion_admission import evaluate_mission_completion_admission


def test_subordinate_write_with_remaining_pr_delivery_cannot_complete_parent():
    result = evaluate_mission_completion_admission(
        repository="Blummer92/agent-os", issue_number=2188,
        branch_exists=True, implementation_commit_count=1,
        draft_pr_exists=False, canonical_pr_readback_verified=False,
        capable_route_available=True, subordinate_writes_only=True,
    )
    assert result.completion_admissible is False
    assert "subordinate-write-is-not-parent-completion" in result.reason_codes
    assert "draft-pr-not-proven" in result.reason_codes
    assert result.next_action == "continue-same-lineage-on-capable-implementation-route"
