from __future__ import annotations

import pytest

from agent_os_execution_service.execution_surface_availability import (
    ExecutionSurfaceAvailabilityOutcome,
    evaluate_execution_surface_availability,
)
from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    select_executor_route,
)


BASE = {
    "repository": "Blummer92/agent-os",
    "issue_or_handoff_identity": "issue:1236",
    "requested_operation": "implement-route-prerequisite-gating",
    "created_at": "2026-08-18T17:00:00Z",
    "expires_at": "2026-08-18T18:00:00Z",
    "invalidation_conditions": ("repository-head-changed",),
    "execution_service_request_fingerprint_or_none": "execution-request:1236",
    "operating_mode_decision_id_or_none": "operating-mode:1236",
    "executable_lane_selection_id_or_none": "lane-selection:1236",
}


def route(**overrides):
    values = dict(BASE)
    values.update(
        required_capabilities=(),
        governed_runner_capabilities=(),
        governed_runner_available=False,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
    )
    values.update(overrides)
    return select_executor_route(**values)


def governed_route():
    capabilities = (
        ExecutorCapability.CHECKOUT,
        ExecutorCapability.MULTI_FILE_IMPLEMENTATION,
        ExecutorCapability.TEST_EXECUTION,
    )
    capabilities = tuple(sorted(capabilities, key=lambda item: item.value))
    return route(
        required_capabilities=capabilities,
        governed_runner_capabilities=capabilities,
        governed_runner_available=True,
        validation_command_plan_id_or_none="command-plan:1236",
        environment_profile_id_or_none="environment-profile:gce",
        environment_health_evidence_id_or_none="environment-health:gce",
        workflow_runtime_identity_or_none="workflow-runtime:gce",
    )


def project(decision, **overrides):
    values = {
        "local_git_available": False,
        "local_gh_available": False,
        "connector_native_available": True,
        "local_cli_explicitly_selected": False,
    }
    values.update(overrides)
    return evaluate_execution_surface_availability(decision, **values)


def test_missing_local_gh_does_not_block_governed_runner() -> None:
    result = project(governed_route(), local_git_available=True, local_gh_available=False)
    assert result.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert result.outcome is ExecutionSurfaceAvailabilityOutcome.GOVERNED_RUNNER_AVAILABLE
    assert "not applicable" in result.reason


def test_local_gh_presence_does_not_override_governed_runner() -> None:
    result = project(governed_route(), local_git_available=True, local_gh_available=True)
    assert result.outcome is ExecutionSurfaceAvailabilityOutcome.GOVERNED_RUNNER_AVAILABLE


def test_connector_native_does_not_require_local_cli() -> None:
    decision = route(governed_runner_available=True)
    assert decision.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE
    result = project(decision, local_git_available=False, local_gh_available=False)
    assert result.outcome is ExecutionSurfaceAvailabilityOutcome.CONNECTOR_NATIVE_AVAILABLE


def test_connector_native_unavailable_is_surface_specific_blocker() -> None:
    decision = route()
    result = project(decision, connector_native_available=False)
    assert result.outcome is ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE
    assert "connector-native" in result.reason


def test_ambiguous_route_never_silently_falls_back_to_local_cli() -> None:
    decision = route(authority_ambiguous=True)
    assert decision.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    result = project(
        decision,
        local_git_available=True,
        local_gh_available=True,
        local_cli_explicitly_selected=True,
    )
    assert result.outcome is ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION


def test_local_cli_prerequisites_apply_only_after_explicit_selection() -> None:
    decision = route(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert decision.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK

    not_selected = project(decision, local_git_available=True, local_gh_available=True)
    assert not_selected.outcome is ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION

    selected = project(
        decision,
        local_git_available=True,
        local_gh_available=True,
        local_cli_explicitly_selected=True,
    )
    assert selected.outcome is ExecutionSurfaceAvailabilityOutcome.LOCAL_CLI_SELECTED


def test_explicit_local_cli_reports_missing_gh_accurately() -> None:
    decision = route(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    result = project(
        decision,
        local_git_available=True,
        local_gh_available=False,
        local_cli_explicitly_selected=True,
    )
    assert result.outcome is ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE
    assert "local git/gh" in result.reason


def test_projection_preserves_route_identity_and_creates_no_authority() -> None:
    decision = governed_route()
    result = project(decision)
    assert result.route_decision_id == decision.decision_id
    assert result.side_effects_performed is False
    assert not hasattr(result, "execution_authorized")
    assert not hasattr(result, "github_writes_authorized")


@pytest.mark.parametrize(
    "field",
    ["local_git_available", "local_gh_available", "connector_native_available", "local_cli_explicitly_selected"],
)
def test_boolean_inputs_are_strict(field: str) -> None:
    values = {
        "local_git_available": False,
        "local_gh_available": False,
        "connector_native_available": True,
        "local_cli_explicitly_selected": False,
    }
    values[field] = 1
    with pytest.raises(TypeError):
        evaluate_execution_surface_availability(governed_route(), **values)


def test_wrong_route_object_is_rejected() -> None:
    with pytest.raises(TypeError):
        evaluate_execution_surface_availability(
            object(),
            local_git_available=True,
            local_gh_available=True,
            connector_native_available=True,
        )
