from scripts.agent_os_execution_interface.validated_workspace_continuation import (
    SAFE_IMPLEMENTATION_TERMINAL,
    VALIDATED_WORKSPACE_TERMINAL,
    ValidatedWorkspaceObservation,
    decide_validated_workspace_continuation,
)


def test_completed_pilot_continues_to_draft_pr_delivery():
    decision = decide_validated_workspace_continuation(
        ValidatedWorkspaceObservation(
            pilot_status="completed",
            validation_passed=True,
            changed_paths_contained=True,
        )
    )
    assert VALIDATED_WORKSPACE_TERMINAL == "validated-workspace"
    assert SAFE_IMPLEMENTATION_TERMINAL == "draft-pr-handoff"
    assert decision.action == "materialize-draft-pr"
    assert decision.terminal is False
    assert decision.blocked is False


def test_repairable_validation_failure_reenters_existing_repair_path():
    decision = decide_validated_workspace_continuation(
        ValidatedWorkspaceObservation(
            pilot_status="failed",
            validation_passed=False,
            changed_paths_contained=True,
            repair_admissible=True,
        )
    )
    assert decision.action == "repair-validation-failure"
    assert decision.blocked is False


def test_failed_validation_without_repair_admission_stops():
    decision = decide_validated_workspace_continuation(
        ValidatedWorkspaceObservation(
            pilot_status="failed",
            validation_passed=False,
            changed_paths_contained=True,
            repair_admissible=False,
        )
    )
    assert decision.blocked is True
    assert decision.action == ""


def test_excluded_surface_still_fails_closed():
    decision = decide_validated_workspace_continuation(
        ValidatedWorkspaceObservation(
            pilot_status="completed",
            validation_passed=True,
            changed_paths_contained=True,
            excluded_surface_required=True,
        )
    )
    assert decision.blocked is True
    assert "excluded-surface-authorization-required" in decision.reason_codes
