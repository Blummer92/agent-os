from __future__ import annotations

import pytest

from agent_os_execution_service.executor_routing import select_executor_route
from agent_os_execution_service.route_decision_store import (
    AppendRouteDecisionOutcome,
    RouteDecisionNotFound,
    append_route_decision,
    load_route_decision,
)
from scripts.agent_os_execution_checkpoint.store import CheckpointStoreIntegrityConflict

BASE = {
    "repository": "Blummer92/agent-os",
    "issue_or_handoff_identity": "issue:1304",
    "requested_operation": "implement-recoverable-artifacts",
    "required_capabilities": (),
    "governed_runner_capabilities": (),
    "governed_runner_available": False,
    "external_fallback_available": False,
    "external_fallback_explicitly_permitted": False,
    "created_at": "2026-08-20T14:00:00Z",
    "expires_at": "2026-08-20T15:00:00Z",
    "invalidation_conditions": ("repository-head-changed",),
    "execution_service_request_fingerprint_or_none": "execution-request:" + "1" * 6,
    "operating_mode_decision_id_or_none": "operating-mode:current",
    "executable_lane_selection_id_or_none": "lane-selection:current",
}


def _decision(**overrides: object):
    payload = dict(BASE)
    payload.update(overrides)
    return select_executor_route(**payload)


def test_append_and_load_round_trip_recomputes_identity(tmp_path) -> None:
    value = _decision()
    outcome = append_route_decision(tmp_path, value)
    assert type(outcome) is AppendRouteDecisionOutcome
    assert outcome.decision_id == value.decision_id
    assert outcome.already_present is False

    loaded = load_route_decision(tmp_path, value.decision_id)
    assert loaded == value
    assert loaded.decision_id == value.decision_id


def test_repeated_append_of_identical_decision_is_idempotent(tmp_path) -> None:
    value = _decision()
    first = append_route_decision(tmp_path, value)
    second = append_route_decision(tmp_path, value)
    assert first.already_present is False
    assert second.already_present is True
    assert first.path == second.path


def test_load_missing_decision_fails_closed(tmp_path) -> None:
    missing_id = "executor-route-decision:" + "0" * 64
    with pytest.raises(RouteDecisionNotFound):
        load_route_decision(tmp_path, missing_id)


def test_tampered_persisted_bytes_are_rejected_on_load(tmp_path) -> None:
    value = _decision()
    outcome = append_route_decision(tmp_path, value)
    outcome.path.write_bytes(b'{"tampered": true}')
    with pytest.raises(CheckpointStoreIntegrityConflict):
        load_route_decision(tmp_path, value.decision_id)


def test_malformed_decision_id_is_rejected(tmp_path) -> None:
    with pytest.raises(TypeError):
        load_route_decision(tmp_path, "not-a-canonical-id")


def test_append_rejects_non_exact_type(tmp_path) -> None:
    with pytest.raises(TypeError):
        append_route_decision(tmp_path, object())


def test_two_route_decisions_persist_independently(tmp_path) -> None:
    first = _decision()
    second = _decision(requested_operation="implement-a-different-operation")
    append_route_decision(tmp_path, first)
    append_route_decision(tmp_path, second)
    assert load_route_decision(tmp_path, first.decision_id) == first
    assert load_route_decision(tmp_path, second.decision_id) == second


def test_store_module_performs_no_network_or_process_effects() -> None:
    import ast
    import inspect

    import agent_os_execution_service.route_decision_store as store_module

    source = inspect.getsource(store_module)
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("subprocess", "socket", "requests", "urllib", "google.cloud", "boto", "github")
    assert not any(any(token in name.lower() for token in forbidden) for name in imported)
