"""Routing-evidence producer for the AI Navigation trusted host (local candidate).

The five identities the router needs already exist in the repository's governed
invocation records. This module only *reads and cross-checks* them; it derives,
defaults and fabricates nothing, performs no I/O of its own and grants no authority:

* ``environment_profile_id``, ``environment_health_evidence_id`` and
  ``workflow_runtime_identity`` come from the ``GovernedInvocationDescriptor``
  (non-authorizing references written by the existing checkpoint producers).
* ``operating_mode_decision_id`` and ``executable_lane_selection_id`` come from the
  persisted ``ExecutorRouteDecision`` named by the descriptor, read through an injected
  reader (in a host, ``HostCurrentInvocationSources.route_decision``).

The persisted route decision's own disposition is honored, not just mined for ids:
the selected route must be the governed runner, the decision must carry
``execution_authorized``, the governed runner must be available, none of the
ambiguity, stale, contradiction, excluded-surface or irreversible-mutation flags the
router encodes may be set, and ``expires_at`` must be after the trusted host clock.
No new policy is added; the router's own denials are simply not ignored.

Every identity must agree between descriptor and route decision, and the descriptor
and decision must be bound to the same execution request and command plan as the
work being run. Any gap or disagreement returns ``None``, which the trusted host
turns into a refusal.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .ai_navigation_pathway import NavigationRoutingEvidence
from .command_planning import validation_command_plan_id
from .executor_routing import ExecutorRoute
from .models import ExecutionServiceRequest, parse_canonical_utc

__all__ = ["invocation_routing_evidence_provider", "routing_evidence_from_invocation"]


def _text(value: object) -> str | None:
    return value if type(value) is str and value.strip() else None


_DENIAL_FLAGS = (
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


def _dispatchable(route_decision: Any, now: datetime) -> bool:
    route = getattr(route_decision, "selected_route", None)
    if route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER:
        return False
    if getattr(route_decision, "execution_authorized", None) is not True:
        return False
    if getattr(route_decision, "governed_runner_available", None) is not True:
        return False
    if any(getattr(route_decision, flag, None) is not False for flag in _DENIAL_FLAGS):
        return False
    try:
        return parse_canonical_utc(getattr(route_decision, "expires_at", None)) > now
    except (TypeError, ValueError):
        return False


def routing_evidence_from_invocation(
    descriptor: Any,
    route_decision: Any,
    request: ExecutionServiceRequest,
    plan: Any,
    *,
    now: datetime,
) -> NavigationRoutingEvidence | None:
    if type(now) is not datetime or now.tzinfo is None or not _dispatchable(route_decision, now):
        return None
    if _text(getattr(descriptor, "execution_service_request_fingerprint", None)) != request.request_fingerprint:
        return None
    decision_id = _text(getattr(route_decision, "decision_id", None))
    if decision_id is None or decision_id != getattr(descriptor, "route_decision_id", None):
        return None
    bound_request = getattr(route_decision, "execution_service_request_fingerprint_or_none", None)
    if bound_request is not None and bound_request != request.request_fingerprint:
        return None
    bound_plan = getattr(route_decision, "validation_command_plan_id_or_none", None)
    if bound_plan is not None and bound_plan != validation_command_plan_id(plan):
        return None
    pairs = (
        ("environment_profile_id", "environment_profile_id_or_none"),
        ("environment_health_evidence_id", "environment_health_evidence_id_or_none"),
        ("workflow_runtime_identity", "workflow_runtime_identity_or_none"),
    )
    values: dict[str, str] = {}
    for descriptor_name, decision_name in pairs:
        from_descriptor = _text(getattr(descriptor, descriptor_name, None))
        from_decision = _text(getattr(route_decision, decision_name, None))
        if from_descriptor is None or from_decision is None or from_descriptor != from_decision:
            return None
        values[descriptor_name] = from_descriptor
    mode = _text(getattr(route_decision, "operating_mode_decision_id_or_none", None))
    lane = _text(getattr(route_decision, "executable_lane_selection_id_or_none", None))
    if mode is None or lane is None:
        return None
    return NavigationRoutingEvidence(
        operating_mode_decision_id=mode,
        executable_lane_selection_id=lane,
        **values,
    )


def invocation_routing_evidence_provider(
    descriptor: Any,
    route_decision_reader: Callable[[Any], Any],
    *,
    clock: Callable[[], datetime],
) -> Callable[[ExecutionServiceRequest, Any], NavigationRoutingEvidence | None]:
    """Build the ``routing_evidence_provider`` a ``TrustedHostComposition`` expects.

    A reader failure propagates (the pathway reports it as a routing-provider outage,
    infrastructure, no dispatch); a missing or inconsistent record returns ``None``.
    """

    def provider(request: ExecutionServiceRequest, plan: Any) -> NavigationRoutingEvidence | None:
        return routing_evidence_from_invocation(descriptor, route_decision_reader(descriptor), request, plan, now=clock())

    return provider
