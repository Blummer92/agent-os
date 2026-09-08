from scripts.agent_os_execution_interface.mission_completion_admission import (
    evaluate_mission_completion_admission,
)


def admission(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "issue_number": 1985,
        "branch_exists": True,
        "implementation_commit_count": 1,
        "draft_pr_exists": True,
        "canonical_pr_readback_verified": True,
        "capable_route_available": True,
        "subordinate_writes_only": False,
    }
    values.update(overrides)
    return evaluate_mission_completion_admission(**values)


def test_canonical_pr_delivery_is_required_for_completion():
    result = admission()
    assert result.completion_admissible is True
    assert result.next_action == "report-canonically-verified-draft-pr-delivery"
    assert result.reason_codes == ("canonical-implementation-delivery-proven",)


def test_zero_commit_branch_is_implementation_not_started():
    result = admission(implementation_commit_count=0, draft_pr_exists=False, canonical_pr_readback_verified=False)
    assert result.completion_admissible is False
    assert "implementation-not-started" in result.reason_codes
    assert "draft-pr-not-proven" in result.reason_codes
    assert result.next_action == "continue-same-lineage-on-capable-implementation-route"


def test_handoff_comment_cannot_complete_parent_mission():
    result = admission(
        implementation_commit_count=0,
        draft_pr_exists=False,
        canonical_pr_readback_verified=False,
        subordinate_writes_only=True,
    )
    assert result.completion_admissible is False
    assert "subordinate-write-is-not-parent-completion" in result.reason_codes
    assert result.next_action == "continue-same-lineage-on-capable-implementation-route"


def test_missing_canonical_pr_readback_blocks_success_claim():
    result = admission(canonical_pr_readback_verified=False)
    assert result.completion_admissible is False
    assert "canonical-pr-readback-not-proven" in result.reason_codes


def test_no_capable_route_reports_exact_blocker_without_false_completion():
    result = admission(
        implementation_commit_count=0,
        draft_pr_exists=False,
        canonical_pr_readback_verified=False,
        capable_route_available=False,
        subordinate_writes_only=True,
    )
    assert result.completion_admissible is False
    assert result.next_action == "report-exact-patch-capability-blocker-without-completion-claim"


def test_guard_grants_no_dangerous_authority():
    result = admission()
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.workflow_authorized is False
    assert result.production_authorized is False
    assert result.external_system_write_authorized is False
