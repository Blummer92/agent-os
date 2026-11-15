"""Routing-evidence producer tests (local candidate).

Real: GovernedInvocationDescriptor, request/plan identities, trusted-host refusal path.
The persisted route decision is a REAL ExecutorRouteDecision built by the real select_executor_route.
Named double: only the injected reader that returns it (production: HostCurrentInvocationSources.route_decision).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import test_ai_navigation_trusted_host as th_tests
from test_ai_navigation_pathway import nav, _clock
from test_ai_navigation_trusted_host import _comp, _parts
from agent_os_execution_service.ai_navigation_invocation_routing import (
    invocation_routing_evidence_provider, routing_evidence_from_invocation,
)
from agent_os_execution_service.ai_navigation_trusted_host import run_trusted_host_navigation
from agent_os_execution_service.executor_routing import ExecutorCapability as C, ExecutorRoute, executor_route_decision_id, select_executor_route
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME, INVOCATION_DESCRIPTOR_SCHEMA_VERSION, GovernedInvocationDescriptor,
)


def _id(domain, name):
    import hashlib
    return f"{domain}:{hashlib.sha256(name.encode()).hexdigest()}"


def _descriptor(fingerprint, **over):
    values = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME, "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": "Blummer92/agent-os", "issue_number": 560, "issue_or_handoff_identity": "issue:560",
        "handoff_id": _id("executor-handoff", "h"), "route_decision_id": _id("executor-route-decision", "r"),
        "execution_service_request_fingerprint": fingerprint, "authorization_id": _id("authorization", "a"),
        "source_ref": "refs/heads/agent/560-x", "source_sha": "a" * 40,
        "checkpoint_id": _id("agent-os.execution-checkpoint", "c"), "resume_plan_id": _id("resume", "p"),
        "environment_profile_id": _id("environment-profile", "p"), "environment_health_evidence_id": _id("env-health", "h"),
        "required_environment_id": _id("required-env", "e"), "dependency_readiness_evidence_id": _id("dep", "d"),
        "execution_surface_id": _id("surface", "s"), "workspace_identity": "workspace-1",
        "workflow_runtime_identity": _id("workflow-runtime", "w"), "candidate_packet_id": _id("candidate-packet", "k"),
        "runtime_configuration_fingerprint": _id("concrete-adapters", "f"), "execution_id": "execution-560-a",
        "invocation_id": "invocation-560-a",
    }
    values.update(over)
    return GovernedInvocationDescriptor(**values)


REQ_CAPS = tuple(sorted((C.CHECKOUT, C.ISOLATED_WORKTREE, C.PROCESS_EXECUTION, C.TEST_EXECUTION, C.EXACT_HEAD_VALIDATION),
                        key=lambda c: c.value))
NOW = _clock()


def _decision(descriptor, plan_id, request=None, **over):
    """Real decision from the real selector (matching the descriptor's ids by default)."""
    request = request or _parts()[1]
    kw = dict(
        repository="Blummer92/agent-os", issue_or_handoff_identity=request.issue_or_handoff_identity,
        requested_operation="validation-only", required_capabilities=REQ_CAPS, governed_runner_capabilities=REQ_CAPS,
        governed_runner_available=True, external_fallback_available=False, external_fallback_explicitly_permitted=False,
        created_at=request.created_at, expires_at=request.expires_at, invalidation_conditions=("expected-sha-changed",),
        execution_service_request_fingerprint_or_none=descriptor.execution_service_request_fingerprint,
        authorization_id_or_none="authorization:" + "a" * 64, validation_command_plan_id_or_none=plan_id,
        execution_authorized=True, operating_mode_decision_id_or_none="operating-mode:t1",
        executable_lane_selection_id_or_none="lane-selection:t1",
        environment_profile_id_or_none=descriptor.environment_profile_id,
        environment_health_evidence_id_or_none=descriptor.environment_health_evidence_id,
        workflow_runtime_identity_or_none=descriptor.workflow_runtime_identity)
    kw.update(over)
    return select_executor_route(**kw)


def _pair(over_decision=None, **over_descriptor):
    """(request, plan, descriptor, decision, plan_id) where the descriptor names the decision's real id."""
    _, request, plan = _parts()
    plan_id = nav.validation_command_plan_id(plan)
    base = _descriptor(request.request_fingerprint, **over_descriptor)
    decision = _decision(base, plan_id, request, **(over_decision or {}))
    descriptor = _descriptor(request.request_fingerprint, route_decision_id=executor_route_decision_id(decision),
                             **over_descriptor)
    return request, plan, descriptor, decision, plan_id


def _setup():
    request, plan, descriptor, decision, plan_id = _pair()
    return request, plan, descriptor, decision


def _run(request, plan, descriptor, decision, now=NOW):
    return routing_evidence_from_invocation(descriptor, decision, request, plan, now=now)


def test_real_decision_produces_all_five_identities():
    request, plan, descriptor, decision = _setup()
    assert decision.selected_route is ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    out = _run(request, plan, descriptor, decision)
    assert out.environment_profile_id == descriptor.environment_profile_id
    assert out.environment_health_evidence_id == descriptor.environment_health_evidence_id
    assert out.workflow_runtime_identity == descriptor.workflow_runtime_identity
    assert (out.operating_mode_decision_id, out.executable_lane_selection_id) == ("operating-mode:t1", "lane-selection:t1")


@pytest.mark.parametrize("over", [
    dict(authority_ambiguous=True), dict(ownership_ambiguous=True), dict(source_of_truth_ambiguous=True),
    dict(target_ambiguous=True), dict(scope_ambiguous=True), dict(excluded_surface_involved=True),
    dict(evidence_stale=True), dict(evidence_contradictory=True), dict(irreversible_or_uncertain_mutation=True),
    dict(execution_authorized=False), dict(governed_runner_available=False),
])
def test_non_dispatchable_persisted_decision_yields_none(over):
    request, plan, descriptor, decision, _ = _pair(over)
    assert _run(request, plan, descriptor, decision) is None


def test_non_governed_runner_route_yields_none():
    request, plan, descriptor, decision, _ = _pair(dict(governed_runner_available=False, external_fallback_available=True,
                                                          external_fallback_explicitly_permitted=True,
                                                          external_fallback_capabilities=REQ_CAPS))
    assert decision.selected_route is not ExecutorRoute.CHATGPT_GOVERNED_RUNNER
    assert _run(request, plan, descriptor, decision) is None


def test_expired_decision_yields_none_and_boundary_is_exclusive():
    from datetime import timedelta
    request, plan, descriptor, decision, _ = _pair()
    from agent_os_execution_service.models import parse_canonical_utc
    expires = parse_canonical_utc(decision.expires_at)
    assert _run(request, plan, descriptor, decision, now=expires - timedelta(seconds=1)) is not None
    assert _run(request, plan, descriptor, decision, now=expires) is None
    assert _run(request, plan, descriptor, decision, now=expires + timedelta(seconds=1)) is None


def test_naive_or_missing_clock_yields_none():
    from datetime import datetime
    request, plan, descriptor, decision = _setup()
    assert _run(request, plan, descriptor, decision, now=datetime(2026, 7, 29, 14, 0, 0)) is None
    assert _run(request, plan, descriptor, decision, now=None) is None


def test_real_selector_cannot_persist_none_bindings():
    request, plan, descriptor, _, plan_id = _pair()
    for key in ("execution_service_request_fingerprint_or_none", "operating_mode_decision_id_or_none",
                "executable_lane_selection_id_or_none", "validation_command_plan_id_or_none"):
        with pytest.raises(ValueError):
            _decision(descriptor, plan_id, request, **{key: None})


@pytest.mark.parametrize("over", [
    {"decision_id": "other"}, {"execution_service_request_fingerprint_or_none": "f" * 64},
    {"validation_command_plan_id_or_none": "other-plan"}, {"environment_profile_id_or_none": "environment-profile:other"},
    {"environment_health_evidence_id_or_none": "x"}, {"workflow_runtime_identity_or_none": "x"},
])
def test_binding_disagreement_yields_none(over):
    request, plan, descriptor, decision, _ = _pair()
    # the real decision is frozen; disagreement is exercised by changing what the descriptor or request side says
    descriptor_side = {"environment_profile_id_or_none": "environment_profile_id", "environment_health_evidence_id_or_none": "environment_health_evidence_id",
                       "workflow_runtime_identity_or_none": "workflow_runtime_identity"}
    if "decision_id" in over:
        d2 = _descriptor(request.request_fingerprint, route_decision_id=_id("executor-route-decision", "other"))
        assert _run(request, plan, d2, decision) is None
    elif next(iter(over)) in descriptor_side:
        name = descriptor_side[next(iter(over))]
        d2 = _descriptor(request.request_fingerprint, route_decision_id=descriptor.route_decision_id, **{name: _id(name, "other")})
        assert _run(request, plan, d2, decision) is None
    else:
        _, _, d3, bad, _ = _pair(dict(**over))
        assert _run(request, plan, descriptor, bad) is None


def test_descriptor_for_another_request_yields_none():
    request, plan, _, decision = _setup()
    other = _descriptor("e" * 64, route_decision_id=executor_route_decision_id(decision))
    assert _run(request, plan, other, decision) is None


def _comp_for(tmp_path, monkeypatch, descriptor, decision, reader=None):
    return _comp(tmp_path, monkeypatch, payload_parts=_parts(),
                 routing=invocation_routing_evidence_provider(descriptor, reader or (lambda d: decision), clock=_clock))


def test_trusted_host_dispatches_once_for_dispatchable_real_decision(tmp_path, monkeypatch):
    request, plan, descriptor, decision = _setup()
    payload, comp = _comp_for(tmp_path, monkeypatch, descriptor, decision)
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "completed" and out["execution_attempted"]


@pytest.mark.parametrize("over", [dict(authority_ambiguous=True), dict(execution_authorized=False),
                                  dict(governed_runner_available=False), dict(evidence_stale=True),
                                  dict(scope_ambiguous=True)])
def test_trusted_host_never_dispatches_for_non_dispatchable_real_decision(tmp_path, monkeypatch, over):
    request, plan, descriptor, decision, _ = _pair(over)
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    payload, comp = _comp_for(tmp_path, monkeypatch, descriptor, decision)
    out = run_trusted_host_navigation(payload, comp)
    assert calls == [] and not out["execution_attempted"]


def test_trusted_host_never_dispatches_for_expired_decision(tmp_path, monkeypatch):
    from datetime import timedelta
    from agent_os_execution_service.models import parse_canonical_utc
    request, plan, descriptor, decision = _setup()
    late = parse_canonical_utc(decision.expires_at) + timedelta(seconds=1)
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(),
                          routing=invocation_routing_evidence_provider(descriptor, lambda d: decision, clock=lambda: late))
    out = run_trusted_host_navigation(payload, comp)
    assert calls == [] and not out["execution_attempted"]


def test_reader_outage_is_not_swallowed_into_evidence(tmp_path, monkeypatch):
    request, plan, descriptor, decision = _setup()

    def boom(_):
        raise OSError("store down")
    payload, comp = _comp_for(tmp_path, monkeypatch, descriptor, decision, reader=boom)
    out = run_trusted_host_navigation(payload, comp)
    assert not out["execution_attempted"]


def test_module_has_no_io_or_network_imports():
    import ast, pathlib
    import agent_os_execution_service.ai_navigation_invocation_routing as m
    tree = ast.parse(pathlib.Path(m.__file__).read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not mods & {"os", "subprocess", "socket", "urllib", "http", "requests", "pathlib", "shutil", "tempfile"}


# Defense in depth: the real ExecutorRouteDecision already routes every flagged input away from the
# governed runner, so each individual check below is only reachable with an inconsistent object.
# These use a named double (a copy of a real decision with one field forced) to prove each check stands alone.
from types import SimpleNamespace as _NS


def _forced(decision, **changes):
    values = {name: getattr(decision, name) for name in decision.__dataclass_fields__}
    values.update(changes)
    return _NS(**values)


@pytest.mark.parametrize("field,value", [
    ("selected_route", ExecutorRoute.HUMAN_DECISION_REQUIRED), ("selected_route", "chatgpt-governed-runner"),
    ("execution_authorized", False), ("governed_runner_available", False),
    *[(flag, True) for flag in ("authority_ambiguous", "ownership_ambiguous", "source_of_truth_ambiguous",
                                "target_ambiguous", "scope_ambiguous", "excluded_surface_involved",
                                "evidence_stale", "evidence_contradictory", "irreversible_or_uncertain_mutation")],
])
def test_each_disposition_check_stands_alone_on_a_forced_copy_of_a_real_decision(field, value):
    request, plan, descriptor, decision = _setup()
    assert _run(request, plan, descriptor, _forced(decision)) is not None  # the unforced copy passes
    assert _run(request, plan, descriptor, _forced(decision, **{field: value})) is None


def test_missing_disposition_attributes_fail_closed():
    request, plan, descriptor, decision = _setup()
    for name in ("selected_route", "execution_authorized", "governed_runner_available", "expires_at", "evidence_stale"):
        values = {n: getattr(decision, n) for n in decision.__dataclass_fields__ if n != name}
        assert _run(request, plan, descriptor, _NS(**values)) is None
