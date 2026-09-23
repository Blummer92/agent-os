"""Pure prerequisite projection for an already-selected Agent OS execution route.

This module does not select an executor and does not create authority.  It consumes
one canonical :class:`ExecutorRouteDecision` and answers whether local CLI
prerequisites are relevant to that selected route.  In particular, a missing
local ``gh`` binary is never a global Agent OS blocker when the canonical route
is the governed runner or connector-native execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .executor_routing import ExecutorRoute, ExecutorRouteDecision


class ExecutionSurfaceAvailabilityOutcome(str, Enum):
    """Finite prerequisite outcomes after canonical route selection."""

    GOVERNED_RUNNER_AVAILABLE = "governed-runner-available"
    CONNECTOR_NATIVE_AVAILABLE = "connector-native-available"
    LOCAL_CLI_SELECTED = "local-cli-selected"
    SELECTED_SURFACE_UNAVAILABLE = "selected-surface-unavailable"
    NEEDS_DECISION = "needs-decision"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionSurfaceAvailabilityDecision:
    """Non-authorizing projection of prerequisites for one route decision."""

    route_decision_id: str
    selected_route: ExecutorRoute
    outcome: ExecutionSurfaceAvailabilityOutcome
    local_git_available: bool
    local_gh_available: bool
    connector_native_available: bool
    local_cli_explicitly_selected: bool
    reason: str
    side_effects_performed: bool = False

    def __post_init__(self) -> None:
        if type(self.route_decision_id) is not str or not self.route_decision_id:
            raise ValueError("route_decision_id must be a non-empty string")
        if type(self.selected_route) is not ExecutorRoute:
            raise TypeError("selected_route must be an exact ExecutorRoute")
        if type(self.outcome) is not ExecutionSurfaceAvailabilityOutcome:
            raise TypeError("outcome must be an exact ExecutionSurfaceAvailabilityOutcome")
        for name in (
            "local_git_available",
            "local_gh_available",
            "connector_native_available",
            "local_cli_explicitly_selected",
            "side_effects_performed",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.side_effects_performed:
            raise ValueError("availability projection must perform no side effects")
        if type(self.reason) is not str or not self.reason:
            raise ValueError("reason must be a non-empty string")


def evaluate_execution_surface_availability(
    route_decision: ExecutorRouteDecision,
    *,
    local_git_available: bool,
    local_gh_available: bool,
    connector_native_available: bool,
    local_cli_explicitly_selected: bool = False,
) -> ExecutionSurfaceAvailabilityDecision:
    """Evaluate prerequisites only after the canonical execution route is known.

    Local ``git``/``gh`` facts are intentionally ignored for governed-runner and
    connector-native routes.  They become blocking prerequisites only when a
    caller explicitly selects the local CLI surface.  Ambiguous/human routes
    remain fail-closed and cannot silently fall back to local CLI.
    """

    if type(route_decision) is not ExecutorRouteDecision:
        raise TypeError("route_decision must be an exact ExecutorRouteDecision")
    for name, value in (
        ("local_git_available", local_git_available),
        ("local_gh_available", local_gh_available),
        ("connector_native_available", connector_native_available),
        ("local_cli_explicitly_selected", local_cli_explicitly_selected),
    ):
        if type(value) is not bool:
            raise TypeError(f"{name} must be an exact boolean")

    route = route_decision.selected_route
    if route is ExecutorRoute.HUMAN_DECISION_REQUIRED:
        outcome = ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION
        reason = "canonical route requires a human decision; no local fallback is inferred"
    elif route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        outcome = ExecutionSurfaceAvailabilityOutcome.GOVERNED_RUNNER_AVAILABLE
        reason = "canonical governed runner selected; local git/gh prerequisites are not applicable"
    elif route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE:
        if connector_native_available:
            outcome = ExecutionSurfaceAvailabilityOutcome.CONNECTOR_NATIVE_AVAILABLE
            reason = "canonical connector-native route selected and available; local git/gh prerequisites are not applicable"
        else:
            outcome = ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE
            reason = "canonical connector-native route is unavailable"
    elif local_cli_explicitly_selected:
        outcome = (
            ExecutionSurfaceAvailabilityOutcome.LOCAL_CLI_SELECTED
            if local_git_available and local_gh_available
            else ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE
        )
        reason = (
            "local CLI explicitly selected and required local git/gh prerequisites are available"
            if outcome is ExecutionSurfaceAvailabilityOutcome.LOCAL_CLI_SELECTED
            else "local CLI explicitly selected but required local git/gh prerequisites are unavailable"
        )
    else:
        outcome = ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION
        reason = "non-local fallback route selected; local CLI cannot be inferred as a substitute"

    return ExecutionSurfaceAvailabilityDecision(
        route_decision_id=route_decision.decision_id,
        selected_route=route,
        outcome=outcome,
        local_git_available=local_git_available,
        local_gh_available=local_gh_available,
        connector_native_available=connector_native_available,
        local_cli_explicitly_selected=local_cli_explicitly_selected,
        reason=reason,
    )
