from __future__ import annotations

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    select_executor_route,
)
from scripts.agent_os_execution_interface.validation_route_preference import (
    ValidationRoute,
    ValidationTiming,
    choose_validation_route,
)


def route(*, runner: bool, fallback: bool = False, permit_fallback: bool = False):
    caps = tuple(sorted((
        ExecutorCapability.CHECKOUT,
        ExecutorCapability.EXACT_HEAD_VALIDATION,
        ExecutorCapability.PROCESS_EXECUTION,
        ExecutorCapability.TEST_EXECUTION,
    ), key=lambda item: item.value))
    return select_executor_route(
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:1573",
        requested_operation="pre-pr-developer-loop",
        required_capabilities=caps,
        governed_runner_capabilities=caps if runner else (),
        governed_runner_available=runner,
        external_fallback_available=fallback,
        external_fallback_explicitly_permitted=permit_fallback,
        external_fallback_capabilities=caps if fallback else None,
        created_at="2026-09-01T01:40:00Z",
        expires_at="2026-09-01T02:40:00Z",
        invalidation_conditions=("repository-head-changed",),
        validation_command_plan_id_or_none="command-plan:1573" if runner or fallback else None,
        environment_profile_id_or_none="environment-profile:1573" if runner else None,
        environment_health_evidence_id_or_none="environment-health:1573" if runner else None,
        workflow_runtime_identity_or_none="workflow-runtime:1573" if runner else None,
    )


def test_pre_pr_prefers_capable_governed_runner_over_manual_terminal() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.PRE_PR_DEVELOPER_LOOP,
        executor_route=route(runner=True),
        exact_head_ci_available=True,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.GOVERNED_EXECUTOR
    assert decision.manual_fallback_justified is False


def test_pre_pr_does_not_use_ci_as_first_execution_when_runner_unavailable() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.PRE_PR_DEVELOPER_LOOP,
        executor_route=route(runner=False),
        exact_head_ci_available=True,
        manual_terminal_available=False,
        manual_terminal_appropriate=False,
    )
    assert decision.selected_route is ValidationRoute.NEEDS_DECISION


def test_pre_pr_uses_explicitly_permitted_capable_fallback_before_manual() -> None:
    selected = route(runner=False, fallback=True, permit_fallback=True)
    assert selected.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK
    decision = choose_validation_route(
        timing=ValidationTiming.PRE_PR_DEVELOPER_LOOP,
        executor_route=selected,
        exact_head_ci_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.GOVERNED_EXECUTOR
    assert decision.manual_fallback_justified is False


def test_manual_terminal_is_only_fallback_after_no_capable_automated_route() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.PRE_PR_DEVELOPER_LOOP,
        executor_route=route(runner=False),
        exact_head_ci_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.MANUAL_TERMINAL
    assert decision.manual_fallback_justified is True


def test_no_route_and_inappropriate_manual_execution_needs_decision() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.PRE_PR_DEVELOPER_LOOP,
        executor_route=route(runner=False),
        exact_head_ci_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=False,
    )
    assert decision.selected_route is ValidationRoute.NEEDS_DECISION


def test_final_aggregate_prefers_exact_head_ci_and_suppresses_duplicate_manual_run() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.FINAL_EXACT_HEAD_AGGREGATE,
        executor_route=route(runner=True),
        exact_head_ci_available=True,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.EXACT_HEAD_CI
    assert decision.duplicate_aggregate_avoided is True
    assert decision.manual_fallback_justified is False


def test_final_aggregate_can_use_governed_runner_when_ci_unavailable() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.FINAL_EXACT_HEAD_AGGREGATE,
        executor_route=route(runner=True),
        exact_head_ci_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.GOVERNED_EXECUTOR


def test_ci_diagnosis_reuses_connected_evidence_before_manual_reproduction() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.CI_FAILURE_DIAGNOSIS,
        executor_route=route(runner=False),
        exact_head_ci_available=True,
        connected_ci_evidence_available=True,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.EXACT_HEAD_CI
    assert decision.connected_evidence_reused is True
    assert decision.duplicate_aggregate_avoided is True
    assert decision.manual_fallback_justified is False


def test_ci_diagnosis_uses_governed_route_when_connected_evidence_unavailable() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.CI_FAILURE_DIAGNOSIS,
        executor_route=route(runner=True),
        exact_head_ci_available=False,
        connected_ci_evidence_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.GOVERNED_EXECUTOR
    assert decision.connected_evidence_reused is False
    assert decision.manual_fallback_justified is False


def test_ci_diagnosis_manual_terminal_requires_separate_appropriateness() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.CI_FAILURE_DIAGNOSIS,
        executor_route=route(runner=False),
        exact_head_ci_available=False,
        connected_ci_evidence_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=False,
    )
    assert decision.selected_route is ValidationRoute.NEEDS_DECISION
    assert decision.manual_fallback_justified is False


def test_ci_diagnosis_can_use_manual_terminal_only_as_proven_last_resort() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.CI_FAILURE_DIAGNOSIS,
        executor_route=route(runner=False),
        exact_head_ci_available=False,
        connected_ci_evidence_available=False,
        manual_terminal_available=True,
        manual_terminal_appropriate=True,
    )
    assert decision.selected_route is ValidationRoute.MANUAL_TERMINAL
    assert decision.manual_fallback_justified is True


def test_projection_never_grants_authority() -> None:
    decision = choose_validation_route(
        timing=ValidationTiming.PRE_PR_DEVELOPER_LOOP,
        executor_route=route(runner=True),
        exact_head_ci_available=False,
        manual_terminal_available=False,
        manual_terminal_appropriate=False,
    )
    assert decision.execution_authorized is False
    assert decision.github_writes_authorized is False
    assert decision.merge_authorized is False
    assert decision.issue_closure_authorized is False
    assert decision.production_authorized is False
    assert decision.external_writes_authorized is False
    assert decision.side_effects_performed is False
