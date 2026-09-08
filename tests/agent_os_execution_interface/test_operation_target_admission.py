from scripts.agent_os_execution_interface.operation_target_admission import (
    LifecycleOperation,
    TargetKind,
    evaluate_operation_target_admission,
)


def test_issue_close_bound_to_pr_target_is_rejected_before_mutation():
    result = evaluate_operation_target_admission(
        repository="Blummer92/agent-os",
        target_number=1284,
        operation=LifecycleOperation.CLOSE_ISSUE,
        selected_target_kind=TargetKind.PULL_REQUEST,
        prior_effect_none_proven=True,
        current_target_reacquired=False,
        capable_alternative_available=True,
    )
    assert result.mutation_admissible is False
    assert result.expected_target_kind is TargetKind.ISSUE
    assert "operation-target-kind-mismatch" in result.reason_codes
    assert result.next_action == "reacquire-issue-currentness-before-alternative"


def test_known_zero_effect_wrong_action_continues_after_currentness_reacquisition():
    result = evaluate_operation_target_admission(
        repository="Blummer92/agent-os",
        target_number=1514,
        operation=LifecycleOperation.CLOSE_ISSUE,
        selected_target_kind=TargetKind.PULL_REQUEST,
        prior_effect_none_proven=True,
        current_target_reacquired=True,
        capable_alternative_available=True,
    )
    assert result.mutation_admissible is False
    assert result.next_action == "continue-via-approved-alternative-on-same-lineage"


def test_ambiguous_prior_effect_requires_readback_before_any_alternative_mutation():
    result = evaluate_operation_target_admission(
        repository="Blummer92/agent-os",
        target_number=1284,
        operation=LifecycleOperation.CLOSE_ISSUE,
        selected_target_kind=TargetKind.PULL_REQUEST,
        prior_effect_none_proven=False,
        current_target_reacquired=True,
        capable_alternative_available=True,
    )
    assert result.mutation_admissible is False
    assert result.next_action == "read-back-canonical-state-before-any-mutation"


def test_correct_issue_operation_binding_can_continue():
    result = evaluate_operation_target_admission(
        repository="Blummer92/agent-os",
        target_number=1284,
        operation=LifecycleOperation.CLOSE_ISSUE,
        selected_target_kind=TargetKind.ISSUE,
        prior_effect_none_proven=True,
        current_target_reacquired=True,
        capable_alternative_available=True,
    )
    assert result.mutation_admissible is True
    assert result.reason_codes == ("operation-target-binding-current",)
    assert result.next_action == "continue-selected-operation"


def test_guard_grants_no_lifecycle_or_workflow_authority():
    result = evaluate_operation_target_admission(
        repository="Blummer92/agent-os",
        target_number=1284,
        operation=LifecycleOperation.CLOSE_ISSUE,
        selected_target_kind=TargetKind.ISSUE,
        prior_effect_none_proven=True,
        current_target_reacquired=True,
        capable_alternative_available=True,
    )
    assert result.github_writes_authorized is False
    assert result.issue_closure_authorized is False
    assert result.merge_authorized is False
    assert result.workflow_authorized is False
