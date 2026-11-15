"""#3333 MCP connection repair: B01 request binding + B04 attempt type.

These tests target the pilot's new gates directly. The B01 comparison
itself is unit-tested through ``_bind_request_id`` (no full admission
chain needed); the integration path -- the real dispatcher carrying the
derived id and the pilot comparing it -- is covered by the existing
fixed-codespace-pilot suite's completed probes plus the dispatch tests
appended to test_codespace_implementation_dispatch.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    _bind_request_id,
    _valid_transport,
)

HANDOFF = "executor-handoff:" + "a" * 64
SHA = "b" * 40


def _transport(**overrides):
    transport = {
        "schema_version": "1.0",
        "status": "accepted",
        "reason": "accepted-codespace-implementation-envelope",
        "repository": "Blummer92/agent-os",
        "issue_number": 3333,
        "actor": "Blummer92",
        "run_attempt": 1,
        "logical_trigger_id_or_none": "issue-comment-trigger:1",
        "codespace_implementation_handoff_id_or_none": HANDOFF,
        "codespace_implementation_sha_or_none": SHA,
    }
    transport.update(overrides)
    return transport


def test_b01_matching_result_id_binds():
    outcome = SimpleNamespace(request_or_none="request-derived-1")
    result = SimpleNamespace(request_id="request-derived-1")
    request_id, failure = _bind_request_id(outcome, result)
    assert request_id == "request-derived-1"
    assert failure is None


def test_b01_foreign_result_id_is_rejected_but_canonical_id_is_kept():
    outcome = SimpleNamespace(request_or_none="request-derived-1")
    result = SimpleNamespace(request_id="request:stale-other-invocation")
    request_id, failure = _bind_request_id(outcome, result)
    assert request_id == "request-derived-1"
    assert failure == "transport-request-id-mismatch"


def test_b01_missing_derived_id_is_unavailable_not_trusted():
    outcome = SimpleNamespace(request_or_none=None)
    result = SimpleNamespace(request_id="request-asserted-by-driver")
    request_id, failure = _bind_request_id(outcome, result)
    assert request_id is None
    assert failure == "transport-request-unavailable"


def test_b01_legacy_outcome_without_request_field_is_unavailable():
    outcome = SimpleNamespace()
    result = SimpleNamespace(request_id="request-asserted-by-driver")
    request_id, failure = _bind_request_id(outcome, result)
    assert request_id is None
    assert failure == "transport-request-unavailable"


def test_b04_exact_integer_attempt_is_accepted():
    assert _valid_transport(_transport(run_attempt=1)) is True


def test_b04_boolean_attempt_is_rejected():
    # True == 1 in Python; the exact-type check must reject it.
    assert _valid_transport(_transport(run_attempt=True)) is False
    assert _valid_transport(_transport(run_attempt=False)) is False


def test_b04_float_attempt_is_rejected():
    # 1.0 == 1 in Python; the exact-type check must reject it.
    assert _valid_transport(_transport(run_attempt=1.0)) is False


def test_b04_string_attempt_is_rejected():
    assert _valid_transport(_transport(run_attempt="1")) is False


def test_b04_other_attempt_values_are_rejected():
    assert _valid_transport(_transport(run_attempt=2)) is False
    assert _valid_transport(_transport(run_attempt=None)) is False
