"""Regression proof for the surviving #918 canonical executor router."""

from agent_os_execution_service.executor_routing import ExecutorRoute, ExecutorRouteReason

CANONICAL_ROUTE_NAMES = frozenset({"chatgpt-connector-native", "chatgpt-governed-runner", "external-coding-agent-fallback", "human-decision-required"})

def test_canonical_route_vocabulary_is_exactly_four():
    """The #918 route vocabulary is closed: exactly the four canonical names."""
    names = frozenset(route.value for route in ExecutorRoute)
    assert names == CANONICAL_ROUTE_NAMES, (
        f"route vocabulary drift: extra={sorted(names - CANONICAL_ROUTE_NAMES)}, "
        f"missing={sorted(CANONICAL_ROUTE_NAMES - names)}"
    )


def test_prior_route_resume_invariant_survives():
    """The #907 resume invariant was ported; it must remain present."""
    import agent_os_execution_service.executor_routing as routing

    assert callable(routing._prior_route_available), (  # noqa: SLF001
        "_prior_route_available is not callable"
    )
    reason_values = frozenset(reason.value for reason in ExecutorRouteReason)
    assert "prior-route-preserved" in reason_values
    assert "prior-route-not-available" in reason_values


