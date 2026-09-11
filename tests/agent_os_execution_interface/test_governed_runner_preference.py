from __future__ import annotations

from agent_os_execution_service.executor_routing import (
    ExecutorCapability,
    ExecutorRoute,
    select_executor_route,
)
from scripts.agent_os_execution_interface.governed_runner_preference import (
    GovernedRunnerCandidate,
    GovernedRunnerKind,
    GovernedRunnerPreferenceReason,
    choose_governed_runner,
    executor_route_inputs,
)


def _caps(*values: ExecutorCapability) -> tuple[ExecutorCapability, ...]:
    return tuple(sorted(values, key=lambda item: item.value))


def _candidate(
    kind: GovernedRunnerKind,
    *,
    available: bool = True,
    current: bool = True,
    capabilities: tuple[ExecutorCapability, ...] | None = None,
) -> GovernedRunnerCandidate:
    caps = capabilities or _caps(
        ExecutorCapability.CHECKOUT,
        ExecutorCapability.ISOLATED_WORKTREE,
        ExecutorCapability.DEPENDENCY_INSTALLATION,
        ExecutorCapability.PROCESS_EXECUTION,
        ExecutorCapability.TEST_EXECUTION,
        ExecutorCapability.GIT_RECONCILIATION,
    )
    label = kind.value
    return GovernedRunnerCandidate(
        kind=kind,
        available=available,
        current=current,
        capabilities=caps,
        execution_surface_id=f"execution-surface:{label}",
        environment_profile_id=f"environment-profile:{label}",
        environment_health_evidence_id=f"environment-health:{label}",
        workflow_runtime_identity=f"workflow-runtime:{label}",
    )


def _route(preference, required):
    inputs = executor_route_inputs(preference)
    return select_executor_route(
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:2299",
        requested_operation="developer-loop-repair",
        required_capabilities=required,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        created_at="2026-09-11T20:00:00Z",
        expires_at="2026-09-11T21:00:00Z",
        invalidation_conditions=("environment-health-changed", "repository-head-changed"),
        execution_service_request_fingerprint_or_none="execution-request:2299",
        validation_command_plan_id_or_none="command-plan:2299",
        operating_mode_decision_id_or_none="operating-mode:2299",
        executable_lane_selection_id_or_none="lane-selection:2299",
        **inputs,
    )


def test_codespaces_is_preferred_for_capable_developer_loop() -> None:
    required = _caps(ExecutorCapability.CHECKOUT, ExecutorCapability.TEST_EXECUTION)
    preference = choose_governed_runner(
        required_capabilities=required,
        codespaces=_candidate(GovernedRunnerKind.CODESPACES),
        gce=_candidate(GovernedRunnerKind.GCE),
    )
    assert preference.selected is not None
    assert preference.selected.kind is GovernedRunnerKind.CODESPACES
    assert preference.reason_codes == (GovernedRunnerPreferenceReason.CODESPACES_CAPABLE,)
    route = _route(preference, required)
    assert route.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert route.environment_profile_id_or_none == "environment-profile:codespaces"


def test_stale_codespaces_falls_back_to_current_gce_same_route() -> None:
    required = _caps(ExecutorCapability.CHECKOUT, ExecutorCapability.TEST_EXECUTION)
    preference = choose_governed_runner(
        required_capabilities=required,
        codespaces=_candidate(GovernedRunnerKind.CODESPACES, current=False),
        gce=_candidate(GovernedRunnerKind.GCE),
    )
    assert preference.selected is not None
    assert preference.selected.kind is GovernedRunnerKind.GCE
    assert preference.reason_codes == (
        GovernedRunnerPreferenceReason.CODESPACES_STALE,
        GovernedRunnerPreferenceReason.GCE_CAPABLE,
    )
    assert _route(preference, required).selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER


def test_codespaces_missing_required_capability_falls_back_to_gce() -> None:
    required = _caps(ExecutorCapability.CHECKOUT, ExecutorCapability.RUNTIME_INSPECTION)
    preference = choose_governed_runner(
        required_capabilities=required,
        codespaces=_candidate(
            GovernedRunnerKind.CODESPACES,
            capabilities=_caps(ExecutorCapability.CHECKOUT),
        ),
        gce=_candidate(
            GovernedRunnerKind.GCE,
            capabilities=_caps(ExecutorCapability.CHECKOUT, ExecutorCapability.RUNTIME_INSPECTION),
        ),
    )
    assert preference.selected is not None
    assert preference.selected.kind is GovernedRunnerKind.GCE
    assert GovernedRunnerPreferenceReason.CODESPACES_MISSING_CAPABILITY in preference.reason_codes


def test_autonomous_host_requirement_never_selects_codespaces() -> None:
    required = _caps(ExecutorCapability.PROCESS_EXECUTION)
    preference = choose_governed_runner(
        required_capabilities=required,
        codespaces=_candidate(GovernedRunnerKind.CODESPACES),
        gce=_candidate(GovernedRunnerKind.GCE),
        autonomous_host_required=True,
    )
    assert preference.selected is not None
    assert preference.selected.kind is GovernedRunnerKind.GCE
    assert preference.reason_codes == (
        GovernedRunnerPreferenceReason.AUTONOMOUS_HOST_REQUIRED,
        GovernedRunnerPreferenceReason.GCE_CAPABLE,
    )


def test_no_capable_runner_projects_unavailable_into_existing_router() -> None:
    required = _caps(ExecutorCapability.TEST_EXECUTION)
    preference = choose_governed_runner(
        required_capabilities=required,
        codespaces=_candidate(GovernedRunnerKind.CODESPACES, available=False),
        gce=_candidate(GovernedRunnerKind.GCE, available=False),
    )
    assert preference.selected is None
    assert preference.reason_codes[-1] is GovernedRunnerPreferenceReason.NO_CAPABLE_GOVERNED_RUNNER
    route = _route(preference, required)
    assert route.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED


def test_preference_never_creates_authority() -> None:
    preference = choose_governed_runner(
        required_capabilities=_caps(ExecutorCapability.CHECKOUT),
        codespaces=_candidate(GovernedRunnerKind.CODESPACES),
        gce=_candidate(GovernedRunnerKind.GCE),
    )
    assert preference.execution_authorized is False
    assert preference.github_writes_authorized is False
    assert preference.merge_authorized is False
    assert preference.external_writes_authorized is False
    assert preference.side_effects_performed is False
