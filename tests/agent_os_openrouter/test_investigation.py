"""Dual-investigation tests: independence, per-model fail-closed, shared budget."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from scripts.agent_os_openrouter.config import API_KEY_ENV_VAR
from scripts.agent_os_openrouter.investigation import (
    run_dual_investigation,
    serialize_dual_investigation,
)

from ._helpers import (
    TEST_API_KEY,
    TEST_MODEL_A,
    TEST_MODEL_B,
    FakeTransport,
    make_config,
    make_envelope,
    make_request,
)


@pytest.fixture(autouse=True)
def _keyed_env(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)


def _http_error(code):
    return urllib.error.HTTPError(
        "https://openrouter.ai/api/v1/chat/completions", code, "err", {}, io.BytesIO(b"{}")
    )


class RoutingTransport:
    """Dispatch per model identity so both models can be observed independently."""

    def __init__(self, request, failing_models=()):
        self.request = request
        self.failing_models = set(failing_models)
        self.calls: list[dict] = []

    def __call__(self, body, headers, timeout):
        self.calls.append({"model": body["model"], "headers": headers})
        if body["model"] in self.failing_models:
            raise _http_error(500)
        tokens = 60 if body["model"] == TEST_MODEL_A else 40
        return make_envelope(self.request, tokens=tokens)


def test_two_models_each_invoked_once_with_independent_provenance():
    request = make_request()
    config = make_config()
    transport = RoutingTransport(request)
    result = run_dual_investigation(request, config, transport=transport)

    assert [c["model"] for c in transport.calls] == [TEST_MODEL_A, TEST_MODEL_B]
    assert result.model_a.model_identity == TEST_MODEL_A
    assert result.model_b.model_identity == TEST_MODEL_B
    assert result.model_a.outcome == "accepted"
    assert result.model_b.outcome == "accepted"
    assert result.model_a.request_fingerprint == request.request_fingerprint
    assert result.model_b.request_fingerprint == request.request_fingerprint
    assert result.model_a.tokens_used == 60
    assert result.model_b.tokens_used == 40
    assert result.total_tokens_used == 100
    assert result.budget_exhausted_before_model_b is False
    assert result.investigation_id.startswith("dual-investigation:")
    assert result.model_a.plan_id != result.model_b.plan_id  # distinct kernel plans

    payload = result.to_payload()
    assert payload["model_a"]["model_identity"] == TEST_MODEL_A
    assert payload["model_b"]["model_identity"] == TEST_MODEL_B
    assert TEST_API_KEY not in json.dumps(payload)
    assert serialize_dual_investigation(result).startswith(b'{"budget_exhausted_before_model_b"')


def test_one_model_failing_does_not_poison_the_other():
    request = make_request()
    config = make_config()
    transport = RoutingTransport(request, failing_models={TEST_MODEL_A})
    result = run_dual_investigation(request, config, transport=transport)

    assert result.model_a.outcome == "needs-decision"
    assert result.model_a.reason_codes == ("provider.unavailable",)
    assert result.model_a.plan_id is None
    assert result.model_b.outcome == "accepted"
    assert result.model_b.plan_id is not None


def test_shared_budget_exhaustion_aborts_second_model_fail_closed():
    request = make_request()
    config = make_config(max_total_tokens=60)
    transport = RoutingTransport(request)  # model A spends the whole budget
    result = run_dual_investigation(request, config, transport=transport)

    assert result.model_a.outcome == "accepted"
    assert result.budget_exhausted_before_model_b is True
    assert result.model_b.outcome == "needs-decision"
    assert result.model_b.reason_codes == ("provider.unavailable",)
    assert result.model_b.adapter_invoked is False
    assert [c["model"] for c in transport.calls] == [TEST_MODEL_A]


def test_result_is_content_addressed_and_deterministic():
    request = make_request()
    config = make_config()
    first = run_dual_investigation(request, config, transport=RoutingTransport(request))
    second = run_dual_investigation(request, config, transport=RoutingTransport(request))
    assert first.investigation_id == second.investigation_id


def test_rejects_non_request():
    with pytest.raises(TypeError):
        run_dual_investigation("not-a-request", make_config())
