from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorHandoff,
    ExecutorRoute,
    ExecutorRouteDecision,
    ExecutorRouteReason,
    build_executor_handoff,
    executor_handoff_id,
    executor_route_decision_id,
    select_executor_route,
    serialize_executor_route_decision,
)

BASE = dict(
    repository="Blummer92/agent-os",
    issue_or_handoff_identity="issue:918",
    requested_operation="implement-executor-routing",
    governed_runner_available=False,
    external_fallback_available=False,
    external_fallback_explicitly_permitted=False,
    created_at="2026-08-06T17:00:00Z",
    expires_at="2026-08-06T18:00:00Z",
    invalidation_conditions=("authorization-changed", "repository-head-changed"),
    execution_service_request_fingerprint_or_none="execution-request:abc123",
    operating_mode_decision_id_or_none="operating-mode:abc123",
    executable_lane_selection_id_or_none="lane-selection:abc123",
)


def decision(**overrides):
    payload = dict(BASE)
    payload.update(
        required_capabilities=(),
        governed_runner_capabilities=(),
    )
    payload.update(overrides)
    return select_executor_route(**payload)


def runner_decision(*caps: ExecutorCapability, **overrides):
    ordered = tuple(sorted(caps, key=lambda item: item.value))
    payload = dict(
        required_capabilities=ordered,
        governed_runner_capabilities=ordered,
        governed_runner_available=True,
        environment_profile_id_or_none="environment-profile:abc123",
        environment_health_evidence_id_or_none="environment-health:abc123",
        workflow_runtime_identity_or_none="workflow-runtime:abc123",
    )
    if set(ordered) & {
        ExecutorCapability.COMPILE_OR_LINT,
        ExecutorCapability.TEST_EXECUTION,
        ExecutorCapability.EXACT_HEAD_VALIDATION,
    }:
        payload["validation_command_plan_id_or_none"] = "command-plan:abc123"
    if ExecutorCapability.CHECKPOINTED_RESUME in ordered:
        payload["checkpoint_id_or_none"] = "checkpoint:abc123"
        payload["resume_plan_id_or_none"] = "resume-plan:abc123"
    payload.update(overrides)
    return decision(**payload)


def handoff(decision_value: ExecutorRouteDecision, **overrides):
    payload = dict(
        source_ref_or_none="refs/heads/agent/918-executor-routing",
        source_sha_or_none="a" * 40,
        allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github/workflows",),
        required_return_evidence=("exact-head-sha", "test-results"),
        stop_conditions=("excluded-surface-entered", "scope-expanded"),
    )
    payload.update(overrides)
    return build_executor_handoff(decision_value, **payload)


def test_connector_native_when_no_runtime_capability_is_required():
    result = decision(
        governed_runner_available=True,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert result.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE
    assert result.route_reasons == (ExecutorRouteReason.CONNECTOR_SUFFICIENT,)
    assert result.rejected_lower_cost_routes == ()


@pytest.mark.parametrize("capability", tuple(ExecutorCapability))
def test_every_capability_forces_runtime_route(capability):
    result = runner_decision(capability)
    assert result.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert ExecutorRouteReason.RUNTIME_CAPABILITY_REQUIRED in result.route_reasons


def test_governed_runner_is_preferred_over_available_fallback():
    result = runner_decision(
        ExecutorCapability.CHECKOUT,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert result.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER


def test_missing_runner_capability_uses_explicit_fallback():
    result = decision(
        required_capabilities=(ExecutorCapability.TEST_EXECUTION,),
        governed_runner_capabilities=(),
        governed_runner_available=True,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        validation_command_plan_id_or_none="command-plan:abc123",
    )
    assert result.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK
    assert (
        ExecutorRouteReason.GOVERNED_RUNNER_MISSING_REQUIRED_CAPABILITY
        in result.route_reasons
    )


@pytest.mark.parametrize(
    "available,permitted,missing_reason",
    [
        (False, True, ExecutorRouteReason.EXTERNAL_FALLBACK_UNAVAILABLE),
        (True, False, ExecutorRouteReason.EXTERNAL_FALLBACK_NOT_PERMITTED),
    ],
)
def test_fallback_requires_availability_and_permission(
    available, permitted, missing_reason
):
    result = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        external_fallback_available=available,
        external_fallback_explicitly_permitted=permitted,
    )
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert missing_reason in result.route_reasons
    assert ExecutorRouteReason.NO_CAPABLE_APPROVED_ROUTE in result.route_reasons


@pytest.mark.parametrize(
    "flag,reason",
    [
        ("authority_ambiguous", ExecutorRouteReason.AUTHORITY_AMBIGUOUS),
        ("ownership_ambiguous", ExecutorRouteReason.OWNERSHIP_AMBIGUOUS),
        (
            "source_of_truth_ambiguous",
            ExecutorRouteReason.SOURCE_OF_TRUTH_AMBIGUOUS,
        ),
        ("target_ambiguous", ExecutorRouteReason.TARGET_AMBIGUOUS),
        ("scope_ambiguous", ExecutorRouteReason.SCOPE_AMBIGUOUS),
        (
            "excluded_surface_involved",
            ExecutorRouteReason.EXCLUDED_SURFACE_INVOLVED,
        ),
        ("evidence_stale", ExecutorRouteReason.EVIDENCE_STALE),
        (
            "evidence_contradictory",
            ExecutorRouteReason.EVIDENCE_CONTRADICTORY,
        ),
        (
            "irreversible_or_uncertain_mutation",
            ExecutorRouteReason.IRREVERSIBLE_OR_UNCERTAIN_MUTATION,
        ),
    ],
)
def test_human_override_flags_win(flag, reason):
    result = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_available=True,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        execution_authorized=True,
        authorization_id_or_none="authorization:abc123",
        **{flag: True},
    )
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert result.route_reasons == (reason,)
    assert result.execution_authorized is False
    assert result.github_writes_authorized is False


def test_capability_tuples_must_be_sorted_unique_and_exact():
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(
                ExecutorCapability.TEST_EXECUTION,
                ExecutorCapability.CHECKOUT,
            )
        )
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(
                ExecutorCapability.CHECKOUT,
                ExecutorCapability.CHECKOUT,
            )
        )
    with pytest.raises(TypeError):
        decision(required_capabilities=("checkout",))


def test_reason_vocabulary_is_closed():
    result = decision()
    data = result.to_dict()
    data["route_reasons"] = ["free-form-reason"]
    with pytest.raises(ValueError):
        ExecutorRouteDecision.from_dict(data)


def test_opaque_identifiers_are_bounded_and_required():
    with pytest.raises(ValueError):
        decision(execution_service_request_fingerprint_or_none=None)
    with pytest.raises(ValueError):
        decision(operating_mode_decision_id_or_none="bad id with spaces")
    with pytest.raises(ValueError):
        decision(executable_lane_selection_id_or_none="x" * 257)


def test_authority_requires_authorization_identity_and_is_never_inferred():
    result = decision()
    assert not result.execution_authorized
    assert not result.github_writes_authorized
    with pytest.raises(ValueError):
        decision(execution_authorized=True)
    supplied = decision(
        execution_authorized=True,
        github_writes_authorized=True,
        authorization_id_or_none="authorization:abc123",
    )
    assert supplied.execution_authorized
    assert supplied.github_writes_authorized


def test_validation_and_resume_capabilities_require_owned_identity_references():
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(ExecutorCapability.TEST_EXECUTION,),
            governed_runner_capabilities=(),
            external_fallback_available=True,
            external_fallback_explicitly_permitted=True,
        )
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(ExecutorCapability.CHECKPOINTED_RESUME,),
            governed_runner_capabilities=(),
            external_fallback_available=True,
            external_fallback_explicitly_permitted=True,
        )


def test_runner_route_requires_environment_identity_references():
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(ExecutorCapability.CHECKOUT,),
            governed_runner_capabilities=(ExecutorCapability.CHECKOUT,),
            governed_runner_available=True,
        )


def test_timestamps_are_canonical_and_ordered():
    with pytest.raises(ValueError):
        decision(created_at="2026-08-06T17:00:00+00:00")
    with pytest.raises(ValueError):
        decision(expires_at="2026-08-06T16:00:00Z")


def test_decision_serialization_and_identity_are_deterministic():
    first = decision()
    second = decision()
    assert first == second
    assert executor_route_decision_id(first) == first.decision_id
    assert serialize_executor_route_decision(first) == serialize_executor_route_decision(
        second
    )
    assert (
        json.loads(serialize_executor_route_decision(first))[
            "side_effects_performed"
        ]
        is False
    )
    assert ExecutorRouteDecision.from_dict(first.to_dict()) == first


def test_unknown_decision_fields_are_rejected():
    data = decision().to_dict()
    data["unknown"] = True
    with pytest.raises(ValueError):
        ExecutorRouteDecision.from_dict(data)


def test_handoff_only_for_runner_and_fallback_routes():
    with pytest.raises(ValueError):
        handoff(decision())
    with pytest.raises(ValueError):
        handoff(decision(authority_ambiguous=True))
    assert (
        handoff(runner_decision(ExecutorCapability.CHECKOUT)).destination_route
        is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    )
    fallback = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert (
        handoff(fallback).destination_route
        is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK
    )


def test_handoff_identity_is_deterministic_and_round_trips():
    value = handoff(runner_decision(ExecutorCapability.CHECKOUT))
    assert executor_handoff_id(value) == value.handoff_id
    assert ExecutorHandoff.from_dict(value.to_dict()) == value


def test_checkpoint_resume_and_environment_drift_are_rejected():
    route = runner_decision(ExecutorCapability.CHECKPOINTED_RESUME)
    with pytest.raises(ValueError):
        handoff(route, checkpoint_id_or_none="checkpoint:different")
    with pytest.raises(ValueError):
        handoff(route, resume_plan_id_or_none="resume-plan:different")
    with pytest.raises(ValueError):
        handoff(
            route, environment_profile_id_or_none="environment-profile:different"
        )


def test_path_overlap_and_unsafe_paths_are_rejected():
    route = runner_decision(ExecutorCapability.CHECKOUT)
    with pytest.raises(ValueError):
        handoff(route, forbidden_paths=("08_Tooling",))
    with pytest.raises(ValueError):
        handoff(route, allowed_paths=("../bad",))


def test_handoff_collections_are_sorted_unique_and_bounded():
    route = runner_decision(ExecutorCapability.CHECKOUT)
    with pytest.raises(ValueError):
        handoff(route, required_return_evidence=("z", "a"))
    with pytest.raises(ValueError):
        handoff(route, stop_conditions=("same", "same"))


def test_exactly_two_new_core_dataclasses_and_no_retired_exports():
    module = __import__(
        "agent_os_execution_service.executor_routing", fromlist=["*"]
    )
    models = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and value.__module__ == module.__name__
        and dataclasses.is_dataclass(value)
    ]
    assert {model.__name__ for model in models} == {
        "ExecutorRouteDecision",
        "ExecutorHandoff",
    }
    for retired in (
        "ExecutorCapabilityEvidence",
        "GovernedRunnerHandoff",
        "ExternalExecutorHandoff",
    ):
        assert not hasattr(module, retired)


def test_module_imports_no_operational_or_upstream_concrete_packages():
    module = __import__(
        "agent_os_execution_service.executor_routing", fromlist=["*"]
    )
    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imports & {
        "os",
        "pathlib",
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "github",
        "scripts",
        "workflow_scheduler",
    }
