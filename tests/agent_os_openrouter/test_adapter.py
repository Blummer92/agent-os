"""Adapter tests: fail-closed behavior, retries, budgets, redaction. Offline only."""

from __future__ import annotations

import io
import json
import socket
import urllib.error

import pytest

from scripts.agent_os_openrouter.adapter import (
    OpenRouterBudgetTracker,
    OpenRouterMalformedResponse,
    OpenRouterProposalAdapter,
)
from scripts.agent_os_openrouter.config import API_KEY_ENV_VAR, OpenRouterConfig
from scripts.agent_os_pr_remediation.high_reasoning_proposal import ProposalProviderUnavailable

from ._helpers import (
    TEST_API_KEY,
    TEST_MODEL_A,
    FakeTransport,
    make_adapter,
    make_config,
    make_envelope,
    make_request,
)


@pytest.fixture(autouse=True)
def _keyed_env(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)


def _payload(request):
    return {"request_fingerprint": request.request_fingerprint, "objective": "test"}


def _http_error(code):
    return urllib.error.HTTPError(
        "https://openrouter.ai/api/v1/chat/completions", code, "err", {}, io.BytesIO(b"{}")
    )


def test_success_returns_mapping_with_deterministic_identity_overwrite():
    adapter, fake, request = make_adapter()
    result = adapter.propose(_payload(request))
    assert result["provider_identity"] == "openrouter"
    assert result["model_identity"] == TEST_MODEL_A
    assert result["request_fingerprint"] == request.request_fingerprint
    assert "tampered-by-fixture" not in json.dumps(result)


def test_success_sends_bounded_body_and_bearer_auth():
    adapter, fake, request = make_adapter()
    adapter.propose(_payload(request))
    call = fake.calls[0]
    assert call["body"]["model"] == TEST_MODEL_A
    assert call["body"]["max_tokens"] == 512
    assert call["body"]["messages"][0]["role"] == "system"
    assert "canonical JSON" in call["body"]["messages"][0]["content"] or "JSON" in call["body"]["messages"][0]["content"]
    assert call["headers"]["Authorization"] == "Bearer " + TEST_API_KEY
    assert call["headers"]["Content-Type"] == "application/json"
    assert TEST_API_KEY not in json.dumps(call["body"])


def test_disabled_config_never_calls_network(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    config = make_config(enabled=False)
    adapter, fake, request = make_adapter(config=config)
    with pytest.raises(ProposalProviderUnavailable):
        adapter.propose(_payload(request))
    assert fake.calls == []


def test_missing_key_never_calls_network(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    adapter, fake, request = make_adapter()
    with pytest.raises(ProposalProviderUnavailable):
        adapter.propose(_payload(request))
    assert fake.calls == []


def test_malformed_json_raises_malformed_response():
    envelope = {
        "choices": [{"message": {"content": "not json {{{"}}],
        "usage": {"total_tokens": 10},
    }
    adapter, fake, request = make_adapter(transport=FakeTransport([envelope]))
    with pytest.raises(OpenRouterMalformedResponse):
        adapter.propose(_payload(request))


def test_non_object_json_raises_malformed_response():
    envelope = {"choices": [{"message": {"content": "[1, 2, 3]"}}], "usage": {"total_tokens": 10}}
    adapter, fake, request = make_adapter(transport=FakeTransport([envelope]))
    with pytest.raises(OpenRouterMalformedResponse):
        adapter.propose(_payload(request))


def test_missing_choices_raises_malformed_response():
    envelope = {"choices": [], "usage": {"total_tokens": 10}}
    adapter, fake, request = make_adapter(transport=FakeTransport([envelope]))
    with pytest.raises(OpenRouterMalformedResponse):
        adapter.propose(_payload(request))


def test_http_500_retries_then_unavailable():
    config = make_config(max_retries=2)
    fake = FakeTransport([_http_error(500), _http_error(500), _http_error(500)])
    adapter = OpenRouterProposalAdapter(config, TEST_MODEL_A, transport=fake)
    request = make_request()
    with pytest.raises(ProposalProviderUnavailable):
        adapter.propose(_payload(request))
    assert len(fake.calls) == 3  # initial + 2 retries
    assert adapter.stats["retries"] == 2


def test_timeout_retries_then_unavailable():
    config = make_config(max_retries=1)
    fake = FakeTransport([socket.timeout("timed out"), socket.timeout("timed out")])
    adapter = OpenRouterProposalAdapter(config, TEST_MODEL_A, transport=fake)
    with pytest.raises(ProposalProviderUnavailable):
        adapter.propose(_payload(make_request()))
    assert len(fake.calls) == 2
    assert adapter.stats["retries"] == 1


def test_401_is_terminal_without_retry():
    fake = FakeTransport([_http_error(401)])
    adapter = OpenRouterProposalAdapter(make_config(), TEST_MODEL_A, transport=fake)
    with pytest.raises(ProposalProviderUnavailable):
        adapter.propose(_payload(make_request()))
    assert len(fake.calls) == 1
    assert adapter.stats["retries"] == 0


def test_429_is_retried_then_succeeds():
    request = make_request()
    fake = FakeTransport([_http_error(429), make_envelope(request)])
    adapter = OpenRouterProposalAdapter(make_config(), TEST_MODEL_A, transport=fake)
    result = adapter.propose(_payload(request))
    assert result["provider_identity"] == "openrouter"
    assert len(fake.calls) == 2
    assert adapter.stats["retries"] == 1


def test_budget_exhaustion_fails_before_any_network_call():
    config = make_config(max_total_tokens=100)
    request = make_request()
    tracker = OpenRouterBudgetTracker(config.max_total_tokens)
    fake = FakeTransport([make_envelope(request, tokens=100)])
    adapter = OpenRouterProposalAdapter(config, TEST_MODEL_A, transport=fake, budget_tracker=tracker)
    adapter.propose(_payload(request))
    assert adapter.stats["tokens_used"] == 100

    never_called = FakeTransport([])
    adapter2 = OpenRouterProposalAdapter(
        config, TEST_MODEL_A, transport=never_called, budget_tracker=tracker
    )
    with pytest.raises(ProposalProviderUnavailable, match="budget"):
        adapter2.propose(_payload(request))
    assert never_called.calls == []


def test_usage_recorded_in_stats_and_tracker():
    adapter, fake, request = make_adapter()
    adapter.propose(_payload(request))
    assert adapter.stats["requests_made"] == 1
    assert adapter.stats["tokens_used"] == 150
    assert adapter.stats["latency_seconds"] >= 0.0


def test_oversized_response_rejected():
    big = "x" * (128 * 1024 + 1)
    envelope = {"choices": [{"message": {"content": big}}], "usage": {"total_tokens": 1}}
    adapter, fake, request = make_adapter(transport=FakeTransport([envelope]))
    with pytest.raises(ProposalProviderUnavailable, match="size bound"):
        adapter.propose(_payload(request))


def test_oversized_payload_value_refused_before_network():
    adapter, fake, request = make_adapter(transport=FakeTransport([]))
    payload = {"request_fingerprint": request.request_fingerprint, "blob": "y" * 5000}
    with pytest.raises(ProposalProviderUnavailable, match="text bound"):
        adapter.propose(payload)
    assert fake.calls == []


def test_key_never_appears_in_errors():
    request = make_request()
    for outcomes in (
        [_http_error(401)],
        [_http_error(500), _http_error(500), _http_error(500)],
        {"choices": [{"message": {"content": "garbage"}}]},
    ):
        adapter, fake, _ = make_adapter(transport=FakeTransport(list(outcomes)))
        try:
            adapter.propose(_payload(request))
        except Exception as exc:  # noqa: BLE001
            assert TEST_API_KEY not in str(exc), type(exc).__name__
        else:
            raise AssertionError("expected an exception")


def test_budget_tracker_rejects_nonsense():
    with pytest.raises(ValueError):
        OpenRouterBudgetTracker(0)
    tracker = OpenRouterBudgetTracker(10)
    with pytest.raises(ValueError):
        tracker.record_spent(-1)
