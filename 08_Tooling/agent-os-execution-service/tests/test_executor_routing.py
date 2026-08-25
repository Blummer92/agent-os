from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
import tomllib
from pathlib import Path

import pytest

import agent_os_execution_service.executor_routing as routing
from agent_os_execution_service.executor_routing import (
    EXECUTOR_ROUTING_SCHEMA_VERSION,
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

BASE = {
    "repository": "Blummer92/agent-os",
    "issue_or_handoff_identity": "issue:918",
    "requested_operation": "implement-executor-routing",
    "governed_runner_available": False,
    "external_fallback_available": False,
    "external_fallback_explicitly_permitted": False,
    "created_at": "2026-08-06T17:00:00Z",
    "expires_at": "2026-08-06T18:00:00Z",
    "invalidation_conditions": (
        "authorization-changed",
        "repository-head-changed",
    ),
    "execution_service_request_fingerprint_or_none": "execution-request:abc123",
    "operating_mode_decision_id_or_none": "operating-mode:abc123",
    "executable_lane_selection_id_or_none": "lane-selection:abc123",
}


def decision(**overrides: object) -> ExecutorRouteDecision:
    payload = dict(BASE)
    payload.update(required_capabilities=(), governed_runner_capabilities=())
    payload.update(overrides)
    return select_executor_route(**payload)


def runner_decision(
    *caps: ExecutorCapability,
    **overrides: object,
) -> ExecutorRouteDecision:
    ordered = tuple(sorted(caps, key=lambda item: item.value))
    payload: dict[str, object] = {
        "required_capabilities": ordered,
        "governed_runner_capabilities": ordered,
        "governed_runner_available": True,
        "environment_profile_id_or_none": "environment-profile:abc123",
        "environment_health_evidence_id_or_none": "environment-health:abc123",
        "workflow_runtime_identity_or_none": "workflow-runtime:abc123",
    }
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


def handoff(
    decision_value: ExecutorRouteDecision,
    **overrides: object,
) -> ExecutorHandoff:
    payload: dict[str, object] = {
        "source_ref_or_none": "refs/heads/agent/918-executor-routing",
        "source_sha_or_none": "a" * 40,
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": (".github/workflows",),
        "required_return_evidence": ("exact-head-sha", "test-results"),
        "stop_conditions": ("excluded-surface-entered", "scope-expanded"),
    }
    payload.update(overrides)
    return build_executor_handoff(decision_value, **payload)


def test_public_api_is_exact_and_documented() -> None:
    assert routing.__all__ == [
        "EXECUTOR_ROUTING_SCHEMA_VERSION",
        "ExecutorRoute",
        "ExecutorRouteReason",
        "ExecutorCapability",
        "ExecutorRouteDecision",
        "ExecutorHandoff",
        "select_executor_route",
        "build_executor_handoff",
        "serialize_executor_route_decision",
        "executor_route_decision_id",
        "executor_handoff_id",
    ]
    for name in routing.__all__[1:]:
        assert inspect.getdoc(getattr(routing, name))


def test_schema_and_closed_vocabularies() -> None:
    assert EXECUTOR_ROUTING_SCHEMA_VERSION == "1.0"
    assert [item.value for item in ExecutorRoute] == [
        "chatgpt-connector-native",
        "chatgpt-governed-runner",
        "external-coding-agent-fallback",
        "human-decision-required",
    ]
    assert [item.value for item in ExecutorCapability] == [
        "checkout",
        "isolated-worktree",
        "dependency-installation",
        "process-execution",
        "compile-or-lint",
        "test-execution",
        "runtime-inspection",
        "generated-artifact-inspection",
        "multi-file-implementation",
        "git-reconciliation",
        "exact-head-validation",
        "checkpointed-resume",
        "github-api-read",
        "github-api-write",
    ]


def test_connector_native_is_selected_when_sufficient() -> None:
    result = decision(
        governed_runner_available=True,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert result.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE
    assert result.route_reasons == (ExecutorRouteReason.CONNECTOR_SUFFICIENT,)
    assert result.rejected_lower_cost_routes == ()


@pytest.mark.parametrize("capability", tuple(ExecutorCapability))
def test_each_capability_requires_runtime(capability: ExecutorCapability) -> None:
    result = runner_decision(capability)
    assert result.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert ExecutorRouteReason.RUNTIME_CAPABILITY_REQUIRED in result.route_reasons


def test_runner_precedes_available_fallback() -> None:
    result = runner_decision(
        ExecutorCapability.CHECKOUT,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert result.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER


@pytest.mark.parametrize("runner_available", [False, True])
def test_explicit_fallback_handles_runner_unavailable_or_incapable(
    runner_available: bool,
) -> None:
    result = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        governed_runner_available=runner_available,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert result.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK


@pytest.mark.parametrize(
    "available,permitted,reason",
    [
        (False, True, ExecutorRouteReason.EXTERNAL_FALLBACK_UNAVAILABLE),
        (True, False, ExecutorRouteReason.EXTERNAL_FALLBACK_NOT_PERMITTED),
    ],
)
def test_fallback_requires_availability_and_permission(
    available: bool,
    permitted: bool,
    reason: ExecutorRouteReason,
) -> None:
    result = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        external_fallback_available=available,
        external_fallback_explicitly_permitted=permitted,
    )
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert reason in result.route_reasons
    assert ExecutorRouteReason.NO_CAPABLE_APPROVED_ROUTE in result.route_reasons


def test_fallback_with_unasserted_capability_evidence_preserves_prior_behavior() -> None:
    """``external_fallback_capabilities`` omitted (``None``) is unasserted
    evidence, not proof of zero capability: existing callers that never
    supply it keep today's available+permitted routing unchanged."""
    result = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert result.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK
    assert result.external_fallback_capabilities is None


def test_fallback_selected_when_asserted_capabilities_satisfy_requirement() -> None:
    result = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        external_fallback_capabilities=(ExecutorCapability.CHECKOUT,),
    )
    assert result.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK


def test_fallback_rejected_when_asserted_capabilities_are_missing_one() -> None:
    result = decision(
        required_capabilities=(
            ExecutorCapability.CHECKOUT,
            ExecutorCapability.GITHUB_API_READ,
        ),
        governed_runner_capabilities=(),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        external_fallback_capabilities=(ExecutorCapability.CHECKOUT,),
    )
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert (
        ExecutorRouteReason.EXTERNAL_FALLBACK_MISSING_REQUIRED_CAPABILITY
        in result.route_reasons
    )
    assert ExecutorRouteReason.NO_CAPABLE_APPROVED_ROUTE in result.route_reasons
    assert not any(
        (
            result.execution_authorized,
            result.github_writes_authorized,
            result.external_writes_authorized,
            result.merge_authorized,
        )
    )


def test_1363_external_surface_without_direct_github_api_capability_is_rejected() -> None:
    """Regression for #1363: an external coding-agent surface that has
    checkout/process/tests/git but lacks direct authenticated GitHub API
    capability must be rejected before execution, even though it is
    available and explicitly permitted, and even though the governed
    runner is also unavailable for this operation."""
    required = (
        ExecutorCapability.CHECKOUT,
        ExecutorCapability.GIT_RECONCILIATION,
        ExecutorCapability.PROCESS_EXECUTION,
        ExecutorCapability.TEST_EXECUTION,
        ExecutorCapability.GITHUB_API_WRITE,
    )
    required = tuple(sorted(required, key=lambda item: item.value))
    surface_b_capabilities = tuple(
        sorted(
            (
                ExecutorCapability.CHECKOUT,
                ExecutorCapability.GIT_RECONCILIATION,
                ExecutorCapability.PROCESS_EXECUTION,
                ExecutorCapability.TEST_EXECUTION,
            ),
            key=lambda item: item.value,
        )
    )
    result = decision(
        required_capabilities=required,
        governed_runner_capabilities=(),
        governed_runner_available=False,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        external_fallback_capabilities=surface_b_capabilities,
    )
    assert result.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert (
        ExecutorRouteReason.EXTERNAL_FALLBACK_MISSING_REQUIRED_CAPABILITY
        in result.route_reasons
    )

    capable_result = decision(
        required_capabilities=required,
        governed_runner_capabilities=(),
        governed_runner_available=False,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        external_fallback_capabilities=required,
        validation_command_plan_id_or_none="command-plan:1363",
    )
    assert capable_result.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK


@pytest.mark.parametrize(
    "flag,reason",
    [
        ("authority_ambiguous", ExecutorRouteReason.AUTHORITY_AMBIGUOUS),
        ("ownership_ambiguous", ExecutorRouteReason.OWNERSHIP_AMBIGUOUS),
        ("source_of_truth_ambiguous", ExecutorRouteReason.SOURCE_OF_TRUTH_AMBIGUOUS),
        ("target_ambiguous", ExecutorRouteReason.TARGET_AMBIGUOUS),
        ("scope_ambiguous", ExecutorRouteReason.SCOPE_AMBIGUOUS),
        ("excluded_surface_involved", ExecutorRouteReason.EXCLUDED_SURFACE_INVOLVED),
        ("evidence_stale", ExecutorRouteReason.EVIDENCE_STALE),
        ("evidence_contradictory", ExecutorRouteReason.EVIDENCE_CONTRADICTORY),
        (
            "irreversible_or_uncertain_mutation",
            ExecutorRouteReason.IRREVERSIBLE_OR_UNCERTAIN_MUTATION,
        ),
    ],
)
def test_human_overrides_win_and_reduce_authority(
    flag: str,
    reason: ExecutorRouteReason,
) -> None:
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
    assert not any(
        (
            result.execution_authorized,
            result.github_writes_authorized,
            result.external_writes_authorized,
            result.merge_authorized,
        )
    )


@pytest.mark.parametrize(
    "override,error_type",
    [
        ({"required_capabilities": (ExecutorCapability.TEST_EXECUTION, ExecutorCapability.CHECKOUT)}, ValueError),
        ({"required_capabilities": (ExecutorCapability.CHECKOUT, ExecutorCapability.CHECKOUT)}, ValueError),
        ({"required_capabilities": ("checkout",)}, TypeError),
        ({"operating_mode_decision_id_or_none": "bad id"}, ValueError),
        ({"executable_lane_selection_id_or_none": "x" * 257}, ValueError),
        ({"created_at": "2026-08-06T17:00:00+00:00"}, ValueError),
        ({"expires_at": "2026-08-06T16:00:00Z"}, ValueError),
    ],
)
def test_strict_input_validation(
    override: dict[str, object],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        decision(**override)


def test_required_owned_identities_fail_closed() -> None:
    with pytest.raises(ValueError):
        decision(execution_service_request_fingerprint_or_none=None)
    with pytest.raises(ValueError):
        decision(execution_authorized=True)
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(ExecutorCapability.TEST_EXECUTION,),
            external_fallback_available=True,
            external_fallback_explicitly_permitted=True,
        )
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(ExecutorCapability.CHECKPOINTED_RESUME,),
            external_fallback_available=True,
            external_fallback_explicitly_permitted=True,
        )
    with pytest.raises(ValueError):
        decision(
            required_capabilities=(ExecutorCapability.CHECKOUT,),
            governed_runner_capabilities=(ExecutorCapability.CHECKOUT,),
            governed_runner_available=True,
        )


def test_decision_serialization_identity_and_round_trip() -> None:
    first = decision()
    second = decision()
    assert first == second
    assert executor_route_decision_id(first) == first.decision_id
    assert serialize_executor_route_decision(first) == serialize_executor_route_decision(second)
    assert json.loads(serialize_executor_route_decision(first))["side_effects_performed"] is False
    assert ExecutorRouteDecision.from_dict(first.to_dict()) == first


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.__setitem__("requested_operation", "changed-operation"),
        lambda data: data.__setitem__("operating_mode_decision_id_or_none", "operating-mode:changed"),
    ],
)
def test_decision_tampering_is_rejected(mutation) -> None:
    data = decision().to_dict()
    mutation(data)
    with pytest.raises(ValueError):
        ExecutorRouteDecision.from_dict(data)


@pytest.mark.parametrize("mode", ["unknown", "missing", "side-effect", "tuple-array"])
def test_decision_deserialization_is_strict(mode: str) -> None:
    data = decision().to_dict()
    if mode == "unknown":
        data["unknown"] = True
    elif mode == "missing":
        data.pop("requested_operation")
    elif mode == "side-effect":
        data["side_effects_performed"] = True
    else:
        data["required_capabilities"] = ()
    with pytest.raises((TypeError, ValueError)):
        ExecutorRouteDecision.from_dict(data)


def test_handoff_only_for_runner_and_fallback() -> None:
    with pytest.raises(ValueError):
        handoff(decision())
    with pytest.raises(ValueError):
        handoff(decision(authority_ambiguous=True))
    assert handoff(runner_decision(ExecutorCapability.CHECKOUT)).destination_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    fallback = decision(
        required_capabilities=(ExecutorCapability.CHECKOUT,),
        governed_runner_capabilities=(),
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
    )
    assert handoff(fallback).destination_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK


def test_handoff_identity_and_round_trip() -> None:
    value = handoff(runner_decision(ExecutorCapability.CHECKOUT))
    assert executor_handoff_id(value) == value.handoff_id
    assert ExecutorHandoff.from_dict(value.to_dict()) == value


@pytest.mark.parametrize("authority_field", [
    "execution_authorized",
    "github_writes_authorized",
    "external_writes_authorized",
    "merge_authorized",
])
def test_direct_handoff_authority_requires_authorization_identity(
    authority_field: str,
) -> None:
    value = handoff(runner_decision(ExecutorCapability.CHECKOUT))
    kwargs = {
        item.name: getattr(value, item.name)
        for item in dataclasses.fields(ExecutorHandoff)
        if item.init
    }
    kwargs[authority_field] = True
    kwargs["authorization_id_or_none"] = None
    kwargs["handoff_id"] = ""
    with pytest.raises(ValueError):
        ExecutorHandoff(**kwargs)


def test_deserialized_handoff_authority_requires_authorization_identity() -> None:
    data = handoff(
        runner_decision(
            ExecutorCapability.CHECKOUT,
            execution_authorized=True,
            authorization_id_or_none="authorization:abc123",
        )
    ).to_dict()
    data["authorization_id_or_none"] = None
    with pytest.raises(ValueError):
        ExecutorHandoff.from_dict(data)


def test_validation_handoff_requires_validation_plan_identity() -> None:
    value = handoff(runner_decision(ExecutorCapability.TEST_EXECUTION))
    kwargs = {
        item.name: getattr(value, item.name)
        for item in dataclasses.fields(ExecutorHandoff)
        if item.init
    }
    kwargs["validation_command_plan_id_or_none"] = None
    kwargs["handoff_id"] = ""
    with pytest.raises(ValueError):
        ExecutorHandoff(**kwargs)
    data = value.to_dict()
    data["validation_command_plan_id_or_none"] = None
    with pytest.raises(ValueError):
        ExecutorHandoff.from_dict(data)


@pytest.mark.parametrize("missing", ["checkpoint_id_or_none", "resume_plan_id_or_none"])
def test_checkpointed_resume_handoff_requires_both_identities(missing: str) -> None:
    value = handoff(runner_decision(ExecutorCapability.CHECKPOINTED_RESUME))
    kwargs = {
        item.name: getattr(value, item.name)
        for item in dataclasses.fields(ExecutorHandoff)
        if item.init
    }
    kwargs[missing] = None
    kwargs["handoff_id"] = ""
    with pytest.raises(ValueError):
        ExecutorHandoff(**kwargs)
    data = value.to_dict()
    data[missing] = None
    with pytest.raises(ValueError):
        ExecutorHandoff.from_dict(data)


def test_valid_authority_and_checkpointed_resume_handoff() -> None:
    route = runner_decision(
        ExecutorCapability.CHECKPOINTED_RESUME,
        execution_authorized=True,
        authorization_id_or_none="authorization:abc123",
    )
    value = handoff(route)
    assert value.execution_authorized
    assert value.checkpoint_id_or_none == "checkpoint:abc123"
    assert value.resume_plan_id_or_none == "resume-plan:abc123"


@pytest.mark.parametrize(
    "field,value",
    [
        ("stop_conditions", ["scope-expanded"]),
        ("execution_authorized", True),
        ("checkpoint_id_or_none", "checkpoint:changed"),
    ],
)
def test_handoff_tampering_is_rejected(field: str, value: object) -> None:
    data = handoff(runner_decision(ExecutorCapability.CHECKOUT)).to_dict()
    data[field] = value
    if field == "execution_authorized":
        data["authorization_id_or_none"] = "authorization:abc123"
    with pytest.raises(ValueError):
        ExecutorHandoff.from_dict(data)


def test_handoff_drift_and_path_rules() -> None:
    route = runner_decision(ExecutorCapability.CHECKPOINTED_RESUME)
    with pytest.raises(ValueError):
        handoff(route, checkpoint_id_or_none="checkpoint:different")
    with pytest.raises(ValueError):
        handoff(route, resume_plan_id_or_none="resume-plan:different")
    with pytest.raises(ValueError):
        handoff(route, environment_profile_id_or_none="environment-profile:different")
    with pytest.raises(ValueError):
        handoff(route, forbidden_paths=("08_Tooling",))
    with pytest.raises(ValueError):
        handoff(route, allowed_paths=("../bad",))
    with pytest.raises(ValueError):
        handoff(route, required_return_evidence=("z", "a"))


def test_identity_payloads_cover_every_semantic_field() -> None:
    route = runner_decision(ExecutorCapability.CHECKOUT)
    value = handoff(route)
    decision_fields = {item.name for item in dataclasses.fields(ExecutorRouteDecision)}
    handoff_fields = {item.name for item in dataclasses.fields(ExecutorHandoff)}
    assert set(route.to_dict()) == decision_fields
    assert set(value.to_dict()) == handoff_fields
    assert set(routing._decision_payload(route, include_id=False)) == decision_fields - {"decision_id"}
    assert set(routing._handoff_payload(value, include_id=False)) == handoff_fields - {"handoff_id"}


def test_exactly_two_core_models_and_no_retired_contracts() -> None:
    models = {
        value.__name__
        for value in vars(routing).values()
        if isinstance(value, type)
        and value.__module__ == routing.__name__
        and dataclasses.is_dataclass(value)
    }
    assert models == {"ExecutorRouteDecision", "ExecutorHandoff"}
    for retired in (
        "ExecutorCapabilityEvidence",
        "GovernedRunnerHandoff",
        "ExternalExecutorHandoff",
    ):
        assert not hasattr(routing, retired)


def test_module_imports_no_operational_or_upstream_concrete_packages() -> None:
    source_path = Path(routing.__file__)
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


def test_version_surfaces_and_markdown_limits_are_aligned() -> None:
    package_root = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    project = tomllib.loads((package_root / "pyproject.toml").read_text(encoding="utf-8"))
    models_text = (
        package_root / "src/agent_os_execution_service/models.py"
    ).read_text(encoding="utf-8")
    map_text = (repo_root / "04_Registry/module-version-map.md").read_text(encoding="utf-8")
    details_text = (repo_root / "04_Registry/module-version-map-details.md").read_text(encoding="utf-8")
    assert project["project"]["version"] == "0.6.0"
    assert 'EXECUTION_SERVICE_VERSION = "0.6.0"' in models_text
    assert re.search(r"\| Agent OS Execution Service \| 0\.6\.0 \|", map_text)
    assert "moved `0.5.0` -> `0.6.0`" in details_text
    assert len((package_root / "README.md").read_text(encoding="utf-8").splitlines()) < 100
    assert len(map_text.splitlines()) < 100
