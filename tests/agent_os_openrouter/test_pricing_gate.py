"""Pricing-gate tests: zero-cost enforcement in the invocation path. Offline only."""

from __future__ import annotations

import urllib.error

import pytest

from scripts.agent_os_openrouter.adapter import OpenRouterProposalAdapter
from scripts.agent_os_openrouter.config import API_KEY_ENV_VAR
from scripts.agent_os_openrouter.pricing import (
    FreeModelPricingGate,
    OpenRouterPricingGateError,
    is_zero_price,
)

from ._helpers import (
    TEST_API_KEY,
    TEST_MODEL_A,
    FakeTransport,
    make_adapter,
    make_config,
    make_envelope,
    make_request,
)

FREE_A = "vendor-a/model-a:free"
FREE_B = "vendor-b/model-b:free"


@pytest.fixture(autouse=True)
def _keyed_env(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)


def _catalog(*entries):
    """entries: (model_id, prompt_price, completion_price)."""
    return {
        "data": [
            {"id": model_id, "pricing": {"prompt": prompt, "completion": completion}}
            for model_id, prompt, completion in entries
        ]
    }


def _free_catalog():
    return _catalog((FREE_A, "0", "0"), (FREE_B, "0", "0"))


def _zero_cost_fetcher(generation_id="gen-test-1"):
    return lambda gid: {"data": [{"id": gid, "total_cost": 0}]}


def _gated_adapter(request, catalog=None, refetch=None, gen_fetcher=None,
                   model_identity=FREE_A, **config_changes):
    config = make_config(**config_changes)
    fake = FakeTransport([make_envelope(request)])
    gate = FreeModelPricingGate(
        catalog if catalog is not None else _free_catalog(), catalog_refetch=refetch
    )
    adapter = OpenRouterProposalAdapter(
        config,
        model_identity,
        transport=fake,
        pricing_gate=gate,
        generation_cost_fetcher=gen_fetcher if gen_fetcher is not None else _zero_cost_fetcher(),
    )
    return adapter, fake, gate


def _payload(request):
    return {"request_fingerprint": request.request_fingerprint, "objective": "test"}


# -- is_zero_price ----------------------------------------------------------

@pytest.mark.parametrize("value", ["0", "0.0", " 0 ", "0.00", 0, 0.0])
def test_is_zero_price_accepts_zero_forms(value):
    assert is_zero_price(value) is True


@pytest.mark.parametrize(
    "value",
    ["0.000001", "1e-9", 0.1, 1, -0.5, "free", "", None, True, False, [], {}],
)
def test_is_zero_price_rejects_nonzero_and_non_numeric(value):
    assert is_zero_price(value) is False


# -- verify_model_is_free ---------------------------------------------------

def test_zero_pricing_accepted_string_wire_format():
    gate = FreeModelPricingGate(_catalog((FREE_A, "0", "0")))
    evidence = gate.verify_model_is_free(FREE_A)
    assert evidence["model_id"] == FREE_A
    assert evidence["prompt_price"] == "0"
    assert evidence["completion_price"] == "0"


@pytest.mark.parametrize("prompt,completion", [(0, 0), (0.0, 0.0), ("0.0", "0")])
def test_zero_pricing_accepted_numeric_forms(prompt, completion):
    gate = FreeModelPricingGate(_catalog((FREE_A, prompt, completion)))
    assert gate.verify_model_is_free(FREE_A)["model_id"] == FREE_A


def test_paid_prompt_pricing_rejected():
    gate = FreeModelPricingGate(_catalog((FREE_A, "0.000001", "0")))
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_paid_completion_pricing_rejected():
    gate = FreeModelPricingGate(_catalog((FREE_A, "0", 0.5)))
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_tiny_nonzero_pricing_rejected():
    gate = FreeModelPricingGate(_catalog((FREE_A, "1e-9", "0")))
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_unknown_model_rejected():
    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free("vendor-x/model-x:free")


def test_missing_pricing_block_rejected():
    gate = FreeModelPricingGate({"data": [{"id": FREE_A}]})
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_missing_prompt_key_rejected():
    gate = FreeModelPricingGate({"data": [{"id": FREE_A, "pricing": {"completion": "0"}}]})
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_missing_completion_key_rejected():
    gate = FreeModelPricingGate({"data": [{"id": FREE_A, "pricing": {"prompt": "0"}}]})
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_non_free_suffix_rejected_even_with_zero_pricing():
    # The ':free'-stripping attempt: a stripped identity is rejected outright,
    # never silently accepted or re-suffixed.
    gate = FreeModelPricingGate(_catalog((TEST_MODEL_A, "0", "0")))
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(TEST_MODEL_A)


def test_empty_model_id_rejected():
    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free("")


def test_malformed_catalog_without_data_rejected():
    gate = FreeModelPricingGate({"unexpected": "shape"})
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_refetch_failure_fails_closed_without_stale_fallback():
    calls = []

    def _failing_refetch():
        calls.append(1)
        raise urllib.error.URLError("catalog unreachable")

    gate = FreeModelPricingGate(_free_catalog(), catalog_refetch=_failing_refetch)
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)
    assert calls == [1]


def test_refetch_success_applies_fresh_pricing():
    catalogs = [_free_catalog(), _catalog((FREE_A, "0.01", "0"))]
    gate = FreeModelPricingGate(catalogs[0], catalog_refetch=lambda: catalogs.pop(0))
    # First verification sees the stale zero-cost snapshot...
    gate.verify_model_is_free(FREE_A)
    # ...the refreshed snapshot prices the model as paid -> rejected.
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


def test_refetch_non_mapping_fails_closed():
    gate = FreeModelPricingGate(_free_catalog(), catalog_refetch=lambda: ["not", "a", "mapping"])
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_model_is_free(FREE_A)


# -- verify_generation_cost_zero --------------------------------------------

def test_zero_generation_cost_accepted():
    gate = FreeModelPricingGate(_free_catalog())
    evidence = gate.verify_generation_cost_zero(
        "gen-1", lambda gid: {"data": [{"id": gid, "total_cost": 0}]}
    )
    assert evidence["generation_id"] == "gen-1"
    assert evidence["total_cost"] == 0


def test_string_zero_generation_cost_accepted():
    gate = FreeModelPricingGate(_free_catalog())
    evidence = gate.verify_generation_cost_zero(
        "gen-1", lambda gid: {"data": [{"id": gid, "total_cost": "0"}]}
    )
    assert evidence["total_cost"] == "0"


def test_nonzero_generation_cost_rejected():
    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_generation_cost_zero(
            "gen-1", lambda gid: {"data": [{"id": gid, "total_cost": 0.000002}]}
        )


def test_unknown_generation_cost_rejected():
    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_generation_cost_zero(
            "gen-1", lambda gid: {"data": [{"id": gid}]}
        )


def test_missing_generation_id_rejected():
    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_generation_cost_zero(None, lambda gid: {"data": []})


def test_generation_fetch_failure_fails_closed():
    def _boom(gid):
        raise urllib.error.URLError("generation endpoint down")

    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_generation_cost_zero("gen-1", _boom)


def test_missing_generation_fetcher_fails_closed():
    gate = FreeModelPricingGate(_free_catalog())
    with pytest.raises(OpenRouterPricingGateError):
        gate.verify_generation_cost_zero("gen-1", None)


# -- adapter invocation-path enforcement ------------------------------------

def test_gate_verified_before_transport_call():
    request = make_request()
    adapter, fake, _ = _gated_adapter(request)
    adapter.propose(_payload(request))
    assert len(fake.calls) == 1
    assert adapter.stats["pricing_verifications"] == 1
    evidence = adapter.stats["pricing_evidence"]
    assert evidence["model_id"] == FREE_A


def test_free_suffix_never_stripped_in_request_body():
    request = make_request()
    adapter, fake, _ = _gated_adapter(request)
    adapter.propose(_payload(request))
    assert fake.calls[0]["body"]["model"] == FREE_A


def test_stripped_identity_rejected_before_any_transport_call():
    request = make_request()
    adapter, fake, _ = _gated_adapter(request, model_identity=TEST_MODEL_A)
    with pytest.raises(OpenRouterPricingGateError):
        adapter.propose(_payload(request))
    assert fake.calls == []


def test_paid_pricing_blocks_transport_call():
    request = make_request()
    adapter, fake, _ = _gated_adapter(request, catalog=_catalog((FREE_A, "0.01", "0")))
    with pytest.raises(OpenRouterPricingGateError):
        adapter.propose(_payload(request))
    assert fake.calls == []


def test_refetch_failure_blocks_transport_call():
    def _boom():
        raise urllib.error.URLError("catalog unreachable")

    request = make_request()
    adapter, fake, _ = _gated_adapter(request, refetch=_boom)
    with pytest.raises(OpenRouterPricingGateError):
        adapter.propose(_payload(request))
    assert fake.calls == []


def test_generation_cost_zero_recorded_in_stats():
    request = make_request()
    adapter, fake, _ = _gated_adapter(request)
    adapter.propose(_payload(request))
    evidence = adapter.stats["generation_cost_evidence"]
    assert evidence["generation_id"] == "gen-test-1"
    assert evidence["total_cost"] == 0


def test_nonzero_generation_cost_raises_from_propose():
    request = make_request()
    adapter, fake, _ = _gated_adapter(
        request,
        gen_fetcher=lambda gid: {"data": [{"id": gid, "total_cost": 0.000001}]},
    )
    with pytest.raises(OpenRouterPricingGateError):
        adapter.propose(_payload(request))
    # The transport call happened (pre-call pricing was fine); the defect is
    # raised post-call, fail-closed, before any plan is returned.
    assert len(fake.calls) == 1


def test_missing_generation_cost_fetcher_fails_closed():
    request = make_request()
    config = make_config()
    fake = FakeTransport([make_envelope(request)])
    gate = FreeModelPricingGate(_free_catalog())
    adapter = OpenRouterProposalAdapter(
        config, FREE_A, transport=fake, pricing_gate=gate, generation_cost_fetcher=None
    )
    with pytest.raises(OpenRouterPricingGateError):
        adapter.propose(_payload(request))


def _http_error(code):
    return urllib.error.HTTPError(
        "https://openrouter.ai/api/v1/chat/completions", code, "err", {}, None
    )


def test_429_exhausted_backoff_then_fails_closed_with_gate():
    request = make_request()
    config = make_config(max_retries=2, retry_backoff_seconds=0.0)
    fake = FakeTransport([_http_error(429), _http_error(429), _http_error(429)])
    gate = FreeModelPricingGate(_free_catalog())
    adapter = OpenRouterProposalAdapter(
        config, FREE_A, transport=fake, pricing_gate=gate,
        generation_cost_fetcher=_zero_cost_fetcher(),
    )
    from scripts.agent_os_pr_remediation.high_reasoning_proposal import (
        ProposalProviderUnavailable,
    )

    with pytest.raises(ProposalProviderUnavailable):
        adapter.propose(_payload(request))
    assert len(fake.calls) == 3
    assert adapter.stats["retries"] == 2
    # Pricing was verified once, before the first (failed) attempt.
    assert adapter.stats["pricing_verifications"] == 1


def test_pricing_gate_error_maps_to_provider_failure_in_kernel():
    from scripts.agent_os_pr_remediation import high_reasoning_proposal as kernel

    request = make_request()
    adapter, fake, _ = _gated_adapter(
        request, catalog=_catalog((FREE_A, "0.02", "0"))
    )
    result = kernel.propose_high_reasoning_plan(request, adapter)
    assert result.outcome == kernel.ProposalOutcome.NEEDS_DECISION
    assert result.reason_codes == ("provider.failure",)
    assert result.plan is None
    assert fake.calls == []
