from scripts.agent_os_execution_interface.investigation_completion_admission import (
    evaluate_investigation_completion_admission,
)


def admission(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "issue_number": 2522,
        "material_branch_states": ("resolved-supported",),
        "executable_next_action_available": False,
        "subordinate_write_performed": False,
    }
    values.update(overrides)
    return evaluate_investigation_completion_admission(**values)


def test_issue_2522_checkpoint_cannot_finish_while_event_history_branch_remains():
    result = admission(
        material_branch_states=("resolved-supported", "in-progress"),
        executable_next_action_available=True,
        subordinate_write_performed=True,
    )
    assert result.completion_admissible is False
    assert result.next_action == "continue-same-lineage-investigation"
    assert result.reason_codes == (
        "material-investigation-branch-remains-intermediate",
        "subordinate-write-is-progress-not-investigation-completion",
        "authorized-executable-next-action-remains",
    )


def test_available_read_only_next_action_prevents_terminal_report_even_without_write():
    result = admission(
        material_branch_states=("resolved-supported", "in-progress"),
        executable_next_action_available=True,
    )
    assert result.completion_admissible is False
    assert "authorized-executable-next-action-remains" in result.reason_codes


def test_no_route_with_intermediate_branch_reports_real_blocker_not_success():
    result = admission(
        material_branch_states=("resolved-supported", "in-progress"),
        executable_next_action_available=False,
    )
    assert result.completion_admissible is False
    assert result.next_action == "report-investigation-blocker-with-clearing-condition"


def test_all_material_branches_terminal_admits_reconciled_report():
    result = admission(
        material_branch_states=(
            "resolved-supported",
            "resolved-not-supported",
            "not-applicable-after-evidence",
        ),
    )
    assert result.completion_admissible is True
    assert result.next_action == "report-reconciled-investigation-result"
    assert result.reason_codes == ("all-material-investigation-branches-terminal",)


def test_blocked_branch_is_terminal_only_when_owner_and_clearing_condition_are_classified():
    result = admission(material_branch_states=("blocked-with-owner-and-clearing-condition",))
    assert result.completion_admissible is True


def test_guard_grants_no_dangerous_authority():
    result = admission()
    assert result.github_writes_authorized is False
    assert result.merge_authorized is False
    assert result.issue_closure_authorized is False
    assert result.workflow_authorized is False
    assert result.production_authorized is False
    assert result.external_system_write_authorized is False
