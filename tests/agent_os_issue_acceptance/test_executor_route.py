from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_issue_acceptance.executor_route import (
    CapabilityState,
    ExecutorRoute,
    ExecutorRouteEvidence,
    ExplicitExecutionSurface,
    RuntimeRequirement,
    evaluate_executor_route,
    format_executor_handoff,
)
from scripts.agent_os_issue_acceptance.issue_operational_state import (
    AuthorizationState,
    OperationalOutcome,
)
from scripts.agent_os_issue_acceptance.operating_mode import (
    OperatingModeOutcome,
    RequestedMode,
)

STATE_ID = "issue-operational-state:" + "1" * 64
MODE_ID = "operating-mode-decision:" + "2" * 64
SHA = "a" * 40


def evidence(**changes: object) -> ExecutorRouteEvidence:
    baseline = ExecutorRouteEvidence(
        source_operational_state_id=STATE_ID,
        operational_outcome=OperationalOutcome.READY,
        source_operating_mode_decision_id=MODE_ID,
        operating_mode_outcome=OperatingModeOutcome.BUILT,
        requested_mode=RequestedMode.BUILD,
        implementation_authorization=AuthorizationState.AUTHORIZED,
        target="#907",
        base_ref="main",
        source_revision=SHA,
        observed_revision=SHA,
        stop_condition="Open one Draft PR and stop.",
        goal="Implement deterministic executor routing.",
        scope=("executor route module", "focused tests"),
        validation=("pytest focused", "validate-all"),
        connector_state=CapabilityState.AVAILABLE,
        runner_state=CapabilityState.AVAILABLE,
        external_fallback_state=CapabilityState.AVAILABLE,
    )
    return replace(baseline, **changes)


def test_connector_native_bounded_work() -> None:
    decision = evaluate_executor_route(evidence())
    assert decision.route is ExecutorRoute.CHATGPT_CONNECTOR
    assert decision.handoff is None
    assert "route.chatgpt-connector" in decision.reason_codes


def test_governed_runner_required_for_local_tests() -> None:
    decision = evaluate_executor_route(evidence(runtime_requirements=(RuntimeRequirement.TESTS,)))
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER
    assert "runtime.required" in decision.reason_codes


def test_governed_runner_required_for_generated_artifacts() -> None:
    decision = evaluate_executor_route(
        evidence(runtime_requirements=(RuntimeRequirement.GENERATED_ARTIFACTS,))
    )
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER


def test_explicit_external_request_is_preserved() -> None:
    decision = evaluate_executor_route(
        evidence(explicit_surface=ExplicitExecutionSurface.EXTERNAL_FALLBACK)
    )
    assert decision.route is ExecutorRoute.EXTERNAL_FALLBACK
    assert "user.external-requested" in decision.reason_codes


def test_connector_unavailable_runner_available() -> None:
    decision = evaluate_executor_route(evidence(connector_state=CapabilityState.UNAVAILABLE))
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER


def test_connector_and_runner_unavailable_uses_external() -> None:
    decision = evaluate_executor_route(
        evidence(
            connector_state=CapabilityState.UNAVAILABLE,
            runner_state=CapabilityState.INSUFFICIENT,
        )
    )
    assert decision.route is ExecutorRoute.EXTERNAL_FALLBACK
    assert "fallback.connector-and-runner-unavailable" in decision.reason_codes


@pytest.mark.parametrize(
    ("authorization", "reason"),
    [
        (AuthorizationState.NOT_AUTHORIZED, "authorization.not-authorized"),
        (AuthorizationState.STALE, "authorization.stale"),
        (AuthorizationState.NEEDS_DECISION, "authorization.needs-decision"),
    ],
)
def test_authorization_uncertainty_fails_closed(
    authorization: AuthorizationState, reason: str
) -> None:
    decision = evaluate_executor_route(
        evidence(implementation_authorization=authorization)
    )
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert reason in decision.reason_codes


def test_excluded_surface_fails_closed() -> None:
    decision = evaluate_executor_route(evidence(excluded_surfaces=("merge",)))
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert "evidence.excluded-surface" in decision.reason_codes


def test_conflicting_operational_state_fails_closed() -> None:
    decision = evaluate_executor_route(
        evidence(operational_outcome=OperationalOutcome.CONFLICTING)
    )
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert "state.conflicting" in decision.reason_codes


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"target": ""}, "evidence.target-missing"),
        ({"base_ref": ""}, "evidence.base-missing"),
        ({"source_revision": ""}, "evidence.revision-missing"),
        ({"stop_condition": ""}, "evidence.stop-condition-missing"),
    ],
)
def test_missing_required_routing_evidence_fails_closed(
    changes: dict[str, object], reason: str
) -> None:
    decision = evaluate_executor_route(evidence(**changes))
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert reason in decision.reason_codes


def test_revision_conflict_fails_closed() -> None:
    decision = evaluate_executor_route(evidence(observed_revision="b" * 40))
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert "evidence.revision-conflict" in decision.reason_codes


def test_resume_preserves_same_valid_route() -> None:
    decision = evaluate_executor_route(
        evidence(
            runtime_requirements=(RuntimeRequirement.TESTS,),
            resume_route=ExecutorRoute.GOVERNED_RUNNER,
            resume_route_valid=True,
        )
    )
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER
    assert "resume.route-preserved" in decision.reason_codes


def test_resume_reselects_when_prior_route_is_no_longer_valid() -> None:
    decision = evaluate_executor_route(
        evidence(
            connector_state=CapabilityState.UNAVAILABLE,
            resume_route=ExecutorRoute.CHATGPT_CONNECTOR,
            resume_route_valid=True,
        )
    )
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER
    assert "resume.route-invalid" in decision.reason_codes


def test_compact_handoff_contains_required_fields() -> None:
    decision = evaluate_executor_route(
        evidence(runtime_requirements=(RuntimeRequirement.TESTS,))
    )
    assert decision.handoff is not None
    for prefix in (
        "@Runner",
        "Target:",
        "Mode:",
        "Goal:",
        "Route:",
        "Scope:",
        "Validate:",
        "Stop:",
        "Report:",
        "Reason:",
    ):
        assert prefix in decision.handoff


def test_handoff_is_compact_by_default() -> None:
    decision = evaluate_executor_route(
        evidence(runtime_requirements=(RuntimeRequirement.TESTS,))
    )
    assert decision.handoff is not None
    assert 8 <= len(decision.handoff.splitlines()) <= 12


def test_large_scope_is_compacted_without_failure() -> None:
    decision = evaluate_executor_route(
        evidence(
            runtime_requirements=(RuntimeRequirement.TESTS,),
            scope=tuple(f"scope-{index}-" + "x" * 200 for index in range(20)),
            validation=tuple(f"check-{index}-" + "y" * 200 for index in range(20)),
        )
    )
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER
    assert decision.handoff is not None
    assert "+17 more" in decision.handoff
    assert len(decision.handoff.encode("utf-8")) < 8 * 1024


def test_identical_evidence_produces_identical_decision() -> None:
    first = evaluate_executor_route(evidence(runtime_requirements=(RuntimeRequirement.TESTS,)))
    second = evaluate_executor_route(evidence(runtime_requirements=(RuntimeRequirement.TESTS,)))
    assert first == second
    assert first.decision_id == second.decision_id
    assert first.decision_id.startswith("executor-route-decision:")


def test_unknown_connector_capability_fails_closed() -> None:
    decision = evaluate_executor_route(evidence(connector_state=CapabilityState.UNKNOWN))
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert "capability.connector-unknown" in decision.reason_codes


def test_unknown_required_capability_fails_closed() -> None:
    decision = evaluate_executor_route(
        evidence(
            runtime_requirements=(RuntimeRequirement.TESTS,),
            runner_state=CapabilityState.UNKNOWN,
        )
    )
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert "capability.runner-unknown" in decision.reason_codes


def test_operating_mode_block_fails_closed() -> None:
    decision = evaluate_executor_route(
        evidence(operating_mode_outcome=OperatingModeOutcome.BLOCKED)
    )
    assert decision.route is ExecutorRoute.HUMAN_DECISION
    assert "mode.blocked" in decision.reason_codes


def test_external_unavailable_after_explicit_request_needs_human() -> None:
    decision = evaluate_executor_route(
        evidence(
            explicit_surface=ExplicitExecutionSurface.EXTERNAL_FALLBACK,
            external_fallback_state=CapabilityState.UNAVAILABLE,
        )
    )
    assert decision.route is ExecutorRoute.HUMAN_DECISION


def test_chatgpt_route_rejects_handoff_rendering() -> None:
    with pytest.raises(ValueError, match="does not require"):
        format_executor_handoff(
            ExecutorRoute.CHATGPT_CONNECTOR,
            evidence(),
            ("route.chatgpt-connector",),
        )


def test_explicit_runner_request_is_preserved() -> None:
    decision = evaluate_executor_route(
        evidence(explicit_surface=ExplicitExecutionSurface.GOVERNED_RUNNER)
    )
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER
    assert "user.runner-requested" in decision.reason_codes


def test_external_resume_is_not_preserved_when_lower_routes_are_available() -> None:
    decision = evaluate_executor_route(
        evidence(
            resume_route=ExecutorRoute.EXTERNAL_FALLBACK,
            resume_route_valid=True,
        )
    )
    assert decision.route is ExecutorRoute.CHATGPT_CONNECTOR
    assert "resume.route-invalid" in decision.reason_codes


def test_explicit_connector_request_escalates_for_runtime_requirement() -> None:
    decision = evaluate_executor_route(
        evidence(
            explicit_surface=ExplicitExecutionSurface.CHATGPT_CONNECTOR,
            runtime_requirements=(RuntimeRequirement.TESTS,),
        )
    )
    assert decision.route is ExecutorRoute.GOVERNED_RUNNER
    assert "user.connector-requested" in decision.reason_codes
