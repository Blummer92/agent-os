"""Consume #918 executor routing at the execution-interface fast-track seam.

This adapter is deliberately not a router. The caller must supply one already
validated :class:`ExecutorRouteDecision` from #918 for the exact next operation.
The adapter only turns that canonical decision into the execution-interface
instruction needed by #1330:

- connector-native + current repository-write authority -> use the connected
  GitHub API surface without a local CLI, governed runner, or Cloud Build just
  to perform the repository mutation;
- every non-connector route -> preserve and delegate the existing selected
  route unchanged;
- human-decision, missing upstream write authority, or excluded merge/external
  authority -> fail closed.

The adapter performs no write, validation, process, network, cloud, Scheduler,
lease, retry, persistence, or route selection. A later connector limitation is
owned by the existing #1237 post-selection continuation seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from agent_os_execution_service.executor_routing import (
    ExecutorRoute,
    ExecutorRouteDecision,
)

POST_SELECTION_CONTINUATION_OWNER = (
    "scripts.agent_os_execution_interface.post_selection_continuation"
)


class ConnectorNativeFastTrackAction(str, Enum):
    """Finite execution-interface actions derived from an existing route."""

    USE_CONNECTOR_NATIVE = "use-connector-native"
    DELEGATE_SELECTED_ROUTE = "delegate-selected-route"
    NEEDS_DECISION = "needs-decision"


class ConnectorNativeFastTrackReason(str, Enum):
    """Finite reasons for one route-consumption result."""

    CONNECTOR_NATIVE_SELECTED = "connector-native-selected"
    UPSTREAM_REPOSITORY_WRITE_AUTHORITY_MISSING = (
        "upstream-repository-write-authority-missing"
    )
    EXCLUDED_AUTHORITY_PRESENT = "excluded-authority-present"
    EXISTING_RUNTIME_ROUTE_SELECTED = "existing-runtime-route-selected"
    HUMAN_DECISION_SELECTED = "human-decision-selected"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectorNativeFastTrackDecision:
    """Pure, non-authorizing consumption of one #918 route decision."""

    route_decision: ExecutorRouteDecision
    action: ConnectorNativeFastTrackAction
    reason_codes: tuple[ConnectorNativeFastTrackReason, ...]
    post_selection_continuation_owner: Literal[
        "scripts.agent_os_execution_interface.post_selection_continuation"
    ] = field(default=POST_SELECTION_CONTINUATION_OWNER, init=False)
    local_cli_prerequisite_required: Literal[False] = field(default=False, init=False)
    governed_runner_invoked: Literal[False] = field(default=False, init=False)
    cloud_build_invoked: Literal[False] = field(default=False, init=False)
    mutation_permitted: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.route_decision) is not ExecutorRouteDecision:
            raise TypeError("route_decision must be an exact ExecutorRouteDecision")
        if type(self.action) is not ConnectorNativeFastTrackAction:
            raise TypeError("action must be an exact ConnectorNativeFastTrackAction")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(
            type(item) is not ConnectorNativeFastTrackReason
            for item in self.reason_codes
        ):
            raise TypeError("reason_codes contain an invalid value")
        canonical_reasons = tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        )
        if self.reason_codes != canonical_reasons:
            raise ValueError("reason_codes must be sorted and unique")
        expected_action, expected_reasons = _expected_consumption(self.route_decision)
        if self.action is not expected_action:
            raise ValueError("action does not match the supplied #918 route decision")
        if self.reason_codes != expected_reasons:
            raise ValueError("reason_codes do not match the supplied #918 route decision")

    @property
    def route_decision_id(self) -> str:
        """Expose the exact upstream route identity without creating a new one."""

        return self.route_decision.decision_id

    @property
    def selected_route(self) -> ExecutorRoute:
        """Expose the existing selected route unchanged."""

        return self.route_decision.selected_route


def _expected_consumption(
    route_decision: ExecutorRouteDecision,
) -> tuple[
    ConnectorNativeFastTrackAction,
    tuple[ConnectorNativeFastTrackReason, ...],
]:
    route = route_decision.selected_route
    if route is ExecutorRoute.CHATGPT_CONNECTOR_NATIVE:
        if route_decision.required_capabilities:
            raise ValueError(
                "connector-native route cannot carry runtime capabilities"
            )
        if route_decision.merge_authorized or route_decision.external_writes_authorized:
            return (
                ConnectorNativeFastTrackAction.NEEDS_DECISION,
                (ConnectorNativeFastTrackReason.EXCLUDED_AUTHORITY_PRESENT,),
            )
        if not (
            route_decision.execution_authorized
            and route_decision.github_writes_authorized
        ):
            return (
                ConnectorNativeFastTrackAction.NEEDS_DECISION,
                (
                    ConnectorNativeFastTrackReason.UPSTREAM_REPOSITORY_WRITE_AUTHORITY_MISSING,
                ),
            )
        return (
            ConnectorNativeFastTrackAction.USE_CONNECTOR_NATIVE,
            (ConnectorNativeFastTrackReason.CONNECTOR_NATIVE_SELECTED,),
        )

    if route is ExecutorRoute.HUMAN_DECISION_REQUIRED:
        return (
            ConnectorNativeFastTrackAction.NEEDS_DECISION,
            (ConnectorNativeFastTrackReason.HUMAN_DECISION_SELECTED,),
        )

    return (
        ConnectorNativeFastTrackAction.DELEGATE_SELECTED_ROUTE,
        (ConnectorNativeFastTrackReason.EXISTING_RUNTIME_ROUTE_SELECTED,),
    )


def consume_executor_route_decision(
    route_decision: ExecutorRouteDecision,
) -> ConnectorNativeFastTrackDecision:
    """Consume one canonical #918 decision without rerouting or side effects."""

    if type(route_decision) is not ExecutorRouteDecision:
        raise TypeError("route_decision must be an exact ExecutorRouteDecision")
    action, reasons = _expected_consumption(route_decision)
    return ConnectorNativeFastTrackDecision(
        route_decision=route_decision,
        action=action,
        reason_codes=reasons,
    )
