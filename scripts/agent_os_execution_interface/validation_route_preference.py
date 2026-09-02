"""Deterministic validation-route preference for CI-UX3 (#1573).

This module does not select executor capabilities, execute validation, open a PR,
or create authority. It consumes the canonical #918 executor route and classifies
how an already-required validation or CI diagnosis should be satisfied: connected
CI evidence, governed runtime, authoritative exact-head CI, explicit manual
fallback, or needs-decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from agent_os_execution_service.executor_routing import ExecutorRoute, ExecutorRouteDecision


class ValidationTiming(str, Enum):
    PRE_PR_DEVELOPER_LOOP = "pre-pr-developer-loop"
    FINAL_EXACT_HEAD_AGGREGATE = "final-exact-head-aggregate"
    CI_FAILURE_DIAGNOSIS = "ci-failure-diagnosis"


class ValidationRoute(str, Enum):
    GOVERNED_EXECUTOR = "governed-executor"
    EXACT_HEAD_CI = "exact-head-ci"
    MANUAL_TERMINAL = "manual-terminal"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationRoutePreference:
    timing: ValidationTiming
    route_decision_id: str
    selected_route: ValidationRoute
    reason: str
    manual_fallback_justified: bool
    duplicate_aggregate_avoided: bool
    connected_evidence_reused: bool = False
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.timing) is not ValidationTiming:
            raise TypeError("timing must be an exact ValidationTiming")
        if type(self.route_decision_id) is not str or not self.route_decision_id:
            raise ValueError("route_decision_id must be non-empty text")
        if type(self.selected_route) is not ValidationRoute:
            raise TypeError("selected_route must be an exact ValidationRoute")
        if type(self.reason) is not str or not self.reason:
            raise ValueError("reason must be non-empty text")
        for name in (
            "manual_fallback_justified",
            "duplicate_aggregate_avoided",
            "connected_evidence_reused",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.selected_route is ValidationRoute.MANUAL_TERMINAL and not self.manual_fallback_justified:
            raise ValueError("manual terminal requires explicit fallback justification")
        if self.selected_route is not ValidationRoute.MANUAL_TERMINAL and self.manual_fallback_justified:
            raise ValueError("manual fallback justification is valid only for manual terminal")
        if self.connected_evidence_reused and self.timing is not ValidationTiming.CI_FAILURE_DIAGNOSIS:
            raise ValueError("connected evidence reuse is valid only for CI failure diagnosis")
        if self.connected_evidence_reused and self.selected_route is not ValidationRoute.EXACT_HEAD_CI:
            raise ValueError("connected evidence reuse requires the exact-head CI evidence route")


def choose_validation_route(
    *,
    timing: ValidationTiming,
    executor_route: ExecutorRouteDecision,
    exact_head_ci_available: bool,
    manual_terminal_available: bool,
    manual_terminal_appropriate: bool,
    connected_ci_evidence_available: bool = False,
) -> ValidationRoutePreference:
    """Choose the evidence-appropriate validation surface after canonical routing.

    Pre-PR validation never uses PR CI as its first execution. A capable governed
    runner wins automatically. External fallback may be used only when #918 has
    already selected it. Manual terminal is considered only after #918 proves no
    capable approved automated route and the caller separately proves that manual
    execution is available and appropriate.

    Final aggregate validation prefers authoritative exact-head CI and therefore
    avoids redundant manual/local full-suite execution when CI is available.

    CI failure diagnosis is evidence-first: when connected run/check/job evidence
    already exists, inspect and reuse that evidence rather than asking the user to
    reproduce the aggregate manually. A request to fix code manually does not make
    manual validation execution appropriate; manual terminal remains a separately
    justified last resort after connected evidence and governed routes are absent.
    """
    if type(timing) is not ValidationTiming:
        raise TypeError("timing must be an exact ValidationTiming")
    if type(executor_route) is not ExecutorRouteDecision:
        raise TypeError("executor_route must be an exact ExecutorRouteDecision")
    for name, value in (
        ("exact_head_ci_available", exact_head_ci_available),
        ("manual_terminal_available", manual_terminal_available),
        ("manual_terminal_appropriate", manual_terminal_appropriate),
        ("connected_ci_evidence_available", connected_ci_evidence_available),
    ):
        if type(value) is not bool:
            raise TypeError(f"{name} must be an exact boolean")

    if timing is ValidationTiming.CI_FAILURE_DIAGNOSIS:
        if connected_ci_evidence_available:
            return ValidationRoutePreference(
                timing=timing,
                route_decision_id=executor_route.decision_id,
                selected_route=ValidationRoute.EXACT_HEAD_CI,
                reason="connected CI run/check/job evidence already exists; inspect it before requesting manual reproduction",
                manual_fallback_justified=False,
                duplicate_aggregate_avoided=True,
                connected_evidence_reused=True,
            )
        if executor_route.selected_route in (
            ExecutorRoute.CHATGPT_GOVERNED_RUNNER,
            ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK,
        ):
            return ValidationRoutePreference(
                timing=timing,
                route_decision_id=executor_route.decision_id,
                selected_route=ValidationRoute.GOVERNED_EXECUTOR,
                reason="connected CI evidence is unavailable; canonical routing selected a capable governed diagnostic route",
                manual_fallback_justified=False,
                duplicate_aggregate_avoided=False,
            )
        if (
            executor_route.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED
            and manual_terminal_available
            and manual_terminal_appropriate
        ):
            return ValidationRoutePreference(
                timing=timing,
                route_decision_id=executor_route.decision_id,
                selected_route=ValidationRoute.MANUAL_TERMINAL,
                reason="connected CI evidence and capable governed diagnostic routes are unavailable; manual terminal is explicitly appropriate",
                manual_fallback_justified=True,
                duplicate_aggregate_avoided=False,
            )
        return ValidationRoutePreference(
            timing=timing,
            route_decision_id=executor_route.decision_id,
            selected_route=ValidationRoute.NEEDS_DECISION,
            reason="no connected CI evidence or capable authorized diagnostic route is proven",
            manual_fallback_justified=False,
            duplicate_aggregate_avoided=False,
        )

    if timing is ValidationTiming.FINAL_EXACT_HEAD_AGGREGATE:
        if exact_head_ci_available:
            return ValidationRoutePreference(
                timing=timing,
                route_decision_id=executor_route.decision_id,
                selected_route=ValidationRoute.EXACT_HEAD_CI,
                reason="authoritative exact-head CI is available; redundant manual aggregate is suppressed",
                manual_fallback_justified=False,
                duplicate_aggregate_avoided=True,
            )
        if executor_route.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
            return ValidationRoutePreference(
                timing=timing,
                route_decision_id=executor_route.decision_id,
                selected_route=ValidationRoute.GOVERNED_EXECUTOR,
                reason="exact-head CI unavailable; canonical governed runner is the capable approved route",
                manual_fallback_justified=False,
                duplicate_aggregate_avoided=False,
            )
        if manual_terminal_available and manual_terminal_appropriate and executor_route.selected_route is ExecutorRoute.HUMAN_DECISION_REQUIRED:
            return ValidationRoutePreference(
                timing=timing,
                route_decision_id=executor_route.decision_id,
                selected_route=ValidationRoute.MANUAL_TERMINAL,
                reason="no capable automated exact-head route is available and manual execution is explicitly appropriate",
                manual_fallback_justified=True,
                duplicate_aggregate_avoided=False,
            )
        return ValidationRoutePreference(
            timing=timing,
            route_decision_id=executor_route.decision_id,
            selected_route=ValidationRoute.NEEDS_DECISION,
            reason="no capable authorized exact-head validation route is proven",
            manual_fallback_justified=False,
            duplicate_aggregate_avoided=False,
        )

    if executor_route.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        return ValidationRoutePreference(
            timing=timing,
            route_decision_id=executor_route.decision_id,
            selected_route=ValidationRoute.GOVERNED_EXECUTOR,
            reason="canonical executor routing selected a capable governed runner for the pre-PR developer loop",
            manual_fallback_justified=False,
            duplicate_aggregate_avoided=False,
        )
    if executor_route.selected_route is ExecutorRoute.EXTERNAL_CODING_AGENT_FALLBACK:
        return ValidationRoutePreference(
            timing=timing,
            route_decision_id=executor_route.decision_id,
            selected_route=ValidationRoute.GOVERNED_EXECUTOR,
            reason="canonical executor routing selected an explicitly permitted capable fallback for the pre-PR developer loop",
            manual_fallback_justified=False,
            duplicate_aggregate_avoided=False,
        )
    if executor_route.selected_route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE:
        return ValidationRoutePreference(
            timing=timing,
            route_decision_id=executor_route.decision_id,
            selected_route=ValidationRoute.NEEDS_DECISION,
            reason="pre-PR developer-loop validation requires runtime capability; connector-native routing is insufficient",
            manual_fallback_justified=False,
            duplicate_aggregate_avoided=False,
        )
    if manual_terminal_available and manual_terminal_appropriate:
        return ValidationRoutePreference(
            timing=timing,
            route_decision_id=executor_route.decision_id,
            selected_route=ValidationRoute.MANUAL_TERMINAL,
            reason="canonical routing found no capable approved automated route; manual terminal is available and explicitly appropriate",
            manual_fallback_justified=True,
            duplicate_aggregate_avoided=False,
        )
    return ValidationRoutePreference(
        timing=timing,
        route_decision_id=executor_route.decision_id,
        selected_route=ValidationRoute.NEEDS_DECISION,
        reason="canonical routing found no capable approved route and manual execution is unavailable or inappropriate",
        manual_fallback_justified=False,
        duplicate_aggregate_avoided=False,
    )
