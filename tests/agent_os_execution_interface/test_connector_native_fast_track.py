"""Focused #1330/#1337 regression coverage for connector-native route consumption."""

from __future__ import annotations

import pytest

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    select_executor_route,
)
from scripts.agent_os_execution_interface.connector_native_fast_track import (
    ConnectorNativeFastTrackAction,
    ConnectorNativeFastTrackReason,
    POST_SELECTION_CONTINUATION_OWNER,
    consume_executor_route_decision,
)


def _route(*, required_capabilities=(), **overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "issue_or_handoff_identity": "issue:1337",
        "requested_operation": "update-documentation",
        "required_capabilities": required_capabilities,
        "governed_runner_capabilities": required_capabilities,
        "governed_runner_available": bool(required_capabilities),
        "external_fallback_available": False,
        "external_fallback_explicitly_permitted": False,
        "created_at": "2026-08-21T17:30:00Z",
        "expires_at": "2026-08-21T18:30:00Z",
        "invalidation_conditions": ("repository-head-changed",),
        "execution_service_request_fingerprint_or_none": "execution-request:1337",
        "operating_mode_decision_id_or_none": "operating-mode:1337",
        "executable_lane_selection_id_or_none": "lane-selection:1337",
        "authorization_id_or_none": "authorization:1337",
        "execution_authorized": True,
        "github_writes_authorized": True,
    }
    if required_capabilities:
        values.update(
            validation_command_plan_id_or_none="validation-plan:1337",
            environment_profile_id_or_none="environment-profile:1337",
            environment_health_evidence_id_or_none="environment-health:1337",
            workflow_runtime_identity_or_none="workflow-runtime:1337",
        )
    values.update(overrides)
    return select_executor_route(**values)


def test_zero_runtime_route_uses_connector_native_without_runtime_side_effects():
    route = _route()
    assert route.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE

    decision = consume_executor_route_decision(route)

    assert decision.action is ConnectorNativeFastTrackAction.USE_CONNECTOR_NATIVE
    assert decision.reason_codes == (
        ConnectorNativeFastTrackReason.CONNECTOR_NATIVE_SELECTED,
    )
    assert decision.route_decision_id == route.decision_id
    assert decision.selected_route is route.selected_route
    assert decision.local_cli_prerequisite_required is False
    assert decision.governed_runner_invoked is False
    assert decision.cloud_build_invoked is False
    assert decision.mutation_permitted is False
    assert decision.side_effects_performed is False


@pytest.mark.parametrize(
    "operation",
    (
        "update-documentation",
        "update-pr-body",
        "reconcile-authorized-labels",
        "update-file-with-exact-blob",
    ),
)
def test_zero_runtime_repository_operations_remain_connector_native(operation):
    route = _route(requested_operation=operation)
    assert route.required_capabilities == ()
    assert route.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE
    decision = consume_executor_route_decision(route)
    assert decision.action is ConnectorNativeFastTrackAction.USE_CONNECTOR_NATIVE
    assert decision.governed_runner_invoked is False
    assert decision.cloud_build_invoked is False


def test_zero_command_static_validation_requires_no_runtime_evidence():
    route = _route(
        requested_operation="static-zero-command-validation",
        validation_command_plan_id_or_none="validation-plan:static-zero-command",
        environment_profile_id_or_none=None,
        environment_health_evidence_id_or_none=None,
        workflow_runtime_identity_or_none=None,
    )
    assert route.required_capabilities == ()
    assert route.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE
    decision = consume_executor_route_decision(route)
    assert decision.action is ConnectorNativeFastTrackAction.USE_CONNECTOR_NATIVE
    assert decision.governed_runner_invoked is False
    assert decision.cloud_build_invoked is False


def test_zero_runtime_continuation_does_not_inherit_an_earlier_runtime_route():
    earlier = _route(
        requested_operation="run-focused-tests",
        required_capabilities=(ExecutorCapability.TEST_EXECUTION,),
    )
    assert earlier.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER

    next_operation = _route(requested_operation="update-pr-body")
    assert next_operation.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE
    decision = consume_executor_route_decision(next_operation)
    assert decision.action is ConnectorNativeFastTrackAction.USE_CONNECTOR_NATIVE


@pytest.mark.parametrize(
    "capability",
    (ExecutorCapability.TEST_EXECUTION, ExecutorCapability.COMPILE_OR_LINT),
)
def test_runtime_capability_preserves_the_existing_governed_runner_route(capability):
    route = _route(required_capabilities=(capability,))
    assert route.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER

    decision = consume_executor_route_decision(route)

    assert decision.action is ConnectorNativeFastTrackAction.DELEGATE_SELECTED_ROUTE
    assert decision.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert decision.reason_codes == (
        ConnectorNativeFastTrackReason.EXISTING_RUNTIME_ROUTE_SELECTED,
    )
    assert decision.governed_runner_invoked is False


def test_runtime_requirement_without_capable_route_is_explicit_human_decision():
    route = _route(
        required_capabilities=(ExecutorCapability.TEST_EXECUTION,),
        governed_runner_capabilities=(),
        governed_runner_available=False,
    )
    assert route.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    decision = consume_executor_route_decision(route)
    assert decision.action is ConnectorNativeFastTrackAction.NEEDS_DECISION
    assert decision.reason_codes == (
        ConnectorNativeFastTrackReason.HUMAN_DECISION_SELECTED,
    )


def test_connector_native_fails_closed_without_upstream_write_authority():
    route = _route(
        authorization_id_or_none=None,
        execution_authorized=False,
        github_writes_authorized=False,
    )

    decision = consume_executor_route_decision(route)

    assert decision.action is ConnectorNativeFastTrackAction.NEEDS_DECISION
    assert decision.reason_codes == (
        ConnectorNativeFastTrackReason.UPSTREAM_REPOSITORY_WRITE_AUTHORITY_MISSING,
    )


def test_connector_native_does_not_absorb_merge_or_external_authority():
    route = _route(merge_authorized=True)

    decision = consume_executor_route_decision(route)

    assert decision.action is ConnectorNativeFastTrackAction.NEEDS_DECISION
    assert decision.reason_codes == (
        ConnectorNativeFastTrackReason.EXCLUDED_AUTHORITY_PRESENT,
    )


def test_human_decision_route_stays_a_human_decision():
    route = _route(
        required_capabilities=(ExecutorCapability.TEST_EXECUTION,),
        governed_runner_capabilities=(),
        governed_runner_available=False,
        authorization_id_or_none=None,
        execution_authorized=False,
        github_writes_authorized=False,
    )
    assert route.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED

    decision = consume_executor_route_decision(route)

    assert decision.action is ConnectorNativeFastTrackAction.NEEDS_DECISION
    assert decision.reason_codes == (
        ConnectorNativeFastTrackReason.HUMAN_DECISION_SELECTED,
    )


def test_post_selection_connector_failure_remains_owned_by_1237():
    decision = consume_executor_route_decision(_route())

    assert (
        decision.post_selection_continuation_owner
        == POST_SELECTION_CONTINUATION_OWNER
    )
    assert POST_SELECTION_CONTINUATION_OWNER.endswith("post_selection_continuation")


def test_adapter_accepts_only_the_existing_route_decision_contract():
    with pytest.raises(TypeError, match="exact ExecutorRouteDecision"):
        consume_executor_route_decision(object())
