from __future__ import annotations

from importlib.metadata import version

import pytest
from hypothesis import assume, find, given, seed, settings, strategies as st
from hypothesis.errors import FailedHealthCheck, FlakyFailure, InvalidArgument, Unsatisfiable

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorHandoff,
    ExecutorRoute,
    ExecutorRouteDecision,
    build_executor_handoff,
    executor_handoff_id,
    executor_route_decision_id,
    select_executor_route,
    serialize_executor_route_decision,
)

QUALIFIED_HYPOTHESIS_VERSION = "6.165.9"

BASE = {
    "repository": "Blummer92/agent-os",
    "issue_or_handoff_identity": "issue:1138",
    "requested_operation": "qualify-hypothesis",
    "governed_runner_available": False,
    "external_fallback_available": False,
    "external_fallback_explicitly_permitted": False,
    "created_at": "2026-08-15T21:00:00Z",
    "expires_at": "2026-08-15T22:00:00Z",
    "invalidation_conditions": (
        "authorization-changed",
        "repository-head-changed",
    ),
    "execution_service_request_fingerprint_or_none": "execution-request:1138",
    "operating_mode_decision_id_or_none": "operating-mode:1138",
    "executable_lane_selection_id_or_none": "lane-selection:1138",
}

HUMAN_FLAGS = (
    "authority_ambiguous",
    "ownership_ambiguous",
    "source_of_truth_ambiguous",
    "target_ambiguous",
    "scope_ambiguous",
    "excluded_surface_involved",
    "evidence_stale",
    "evidence_contradictory",
    "irreversible_or_uncertain_mutation",
)

SAFE_SEGMENT = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=12,
)
SAFE_PATH = st.lists(SAFE_SEGMENT, min_size=1, max_size=3).map(lambda parts: "/".join(parts))


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
        "environment_profile_id_or_none": "environment-profile:1138",
        "environment_health_evidence_id_or_none": "environment-health:1138",
        "workflow_runtime_identity_or_none": "workflow-runtime:1138",
    }
    if set(ordered) & {
        ExecutorCapability.COMPILE_OR_LINT,
        ExecutorCapability.TEST_EXECUTION,
        ExecutorCapability.EXACT_HEAD_VALIDATION,
    }:
        payload["validation_command_plan_id_or_none"] = "command-plan:1138"
    payload.update(overrides)
    return decision(**payload)


def handoff(
    decision_value: ExecutorRouteDecision,
    **overrides: object,
) -> ExecutorHandoff:
    payload: dict[str, object] = {
        "source_ref_or_none": "refs/heads/agent/1138-hypothesis-qualification",
        "source_sha_or_none": "a" * 40,
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": (".github/workflows",),
        "required_return_evidence": ("exact-head-sha", "test-results"),
        "stop_conditions": ("excluded-surface-entered", "scope-expanded"),
    }
    payload.update(overrides)
    return build_executor_handoff(decision_value, **payload)


def test_qualification_uses_one_exact_hypothesis_version() -> None:
    assert version("hypothesis") == QUALIFIED_HYPOTHESIS_VERSION


@seed(1138)
@settings(max_examples=40, deadline=None, database=None)
@given(
    governed_runner_available=st.booleans(),
    external_fallback_available=st.booleans(),
    external_fallback_explicitly_permitted=st.booleans(),
)
def test_generated_connector_decisions_round_trip_deterministically(
    governed_runner_available: bool,
    external_fallback_available: bool,
    external_fallback_explicitly_permitted: bool,
) -> None:
    value = decision(
        governed_runner_available=governed_runner_available,
        external_fallback_available=external_fallback_available,
        external_fallback_explicitly_permitted=external_fallback_explicitly_permitted,
    )
    rebuilt = ExecutorRouteDecision.from_dict(value.to_dict())
    assert rebuilt == value
    assert executor_route_decision_id(rebuilt) == value.decision_id
    assert serialize_executor_route_decision(rebuilt) == serialize_executor_route_decision(value)


@seed(1138)
@settings(max_examples=60, deadline=None, database=None)
@given(flags=st.dictionaries(st.sampled_from(HUMAN_FLAGS), st.booleans(), min_size=1))
def test_generated_human_review_conditions_fail_closed(flags: dict[str, bool]) -> None:
    assume(any(flags.values()))
    value = runner_decision(
        ExecutorCapability.CHECKOUT,
        external_fallback_available=True,
        external_fallback_explicitly_permitted=True,
        execution_authorized=True,
        authorization_id_or_none="authorization:1138",
        **flags,
    )
    assert value.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
    assert not any(
        (
            value.execution_authorized,
            value.github_writes_authorized,
            value.external_writes_authorized,
            value.merge_authorized,
        )
    )


@seed(1138)
@settings(max_examples=50, deadline=None, database=None)
@given(path=SAFE_PATH)
def test_generated_safe_paths_round_trip_in_handoffs(path: str) -> None:
    value = handoff(
        runner_decision(ExecutorCapability.CHECKOUT),
        allowed_paths=(path,),
    )
    rebuilt = ExecutorHandoff.from_dict(value.to_dict())
    assert rebuilt == value
    assert executor_handoff_id(rebuilt) == value.handoff_id


@seed(1138)
@settings(max_examples=30, deadline=None, database=None)
@given(segment=SAFE_SEGMENT)
def test_generated_path_traversal_fails_closed(segment: str) -> None:
    route = runner_decision(ExecutorCapability.CHECKOUT)
    with pytest.raises(ValueError):
        handoff(route, allowed_paths=(f"{segment}/../escape",))


def test_minimized_overlap_counterexample_is_preserved_as_regression() -> None:
    route = runner_decision(ExecutorCapability.CHECKOUT)

    def overlaps(pair: tuple[str, str]) -> bool:
        left, right = pair
        try:
            handoff(route, allowed_paths=(left,), forbidden_paths=(right,))
        except ValueError:
            return True
        return False

    counterexample = find(
        st.tuples(st.just("a"), st.just("a")),
        overlaps,
        settings=settings(max_examples=10, deadline=None, database=None),
    )
    assert counterexample == ("a", "a")

    # Normal deterministic pytest regression retained after shrinking.
    with pytest.raises(ValueError):
        handoff(route, allowed_paths=("a",), forbidden_paths=("a",))


def test_deliberately_flawed_property_shrinks_to_duplicate_pair() -> None:
    counterexample = find(
        st.lists(st.integers(), min_size=2, max_size=8),
        lambda values: len(values) != len(set(values)),
        settings=settings(max_examples=200, deadline=None, database=None),
    )
    assert counterexample == [0, 0]


def test_flaky_property_is_diagnosed_not_hidden() -> None:
    state = {"first": True}

    @settings(max_examples=5, deadline=None, database=None)
    @seed(1138)
    @given(st.integers())
    def flaky(_: int) -> None:
        if state["first"]:
            state["first"] = False
            assert False

    with pytest.raises(FlakyFailure):
        flaky()


def test_excessive_filtering_or_bad_assumption_is_diagnosed() -> None:
    @settings(max_examples=10, deadline=None, database=None)
    @seed(1138)
    @given(st.integers())
    def impossible(value: int) -> None:
        assume(value != value)

    with pytest.raises((FailedHealthCheck, Unsatisfiable)):
        impossible()


def test_invalid_strategy_definition_is_rejected() -> None:
    with pytest.raises(InvalidArgument):
        @settings(max_examples=5, deadline=None, database=None)
        @seed(1138)
        @given(st.lists(st.integers(), min_size=2, max_size=1))
        def invalid(_: list[int]) -> None:
            pass

        invalid()


def test_pytest_only_negative_cases_remain_explicit() -> None:
    avoid_when = (
        "exact closed-vocabulary assertion",
        "single known regression example",
        "package or version surface assertion",
        "current local code already answers the question",
    )
    assert "single known regression example" in avoid_when
    assert len(avoid_when) == 4
