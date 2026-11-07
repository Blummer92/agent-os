"""Kernel integration: the OpenRouter adapter through propose_high_reasoning_plan."""

from __future__ import annotations

import json

import pytest

from scripts.agent_os_openrouter.adapter import OpenRouterProposalAdapter
from scripts.agent_os_openrouter.config import API_KEY_ENV_VAR
from scripts.agent_os_pr_remediation.high_reasoning_proposal import (
    AUTHORITY_FIELDS,
    ProposalOutcome,
    propose_high_reasoning_plan,
)

from ._helpers import (
    TEST_API_KEY,
    TEST_MODEL_A,
    FakeTransport,
    make_adapter,
    make_envelope,
    make_request,
)


@pytest.fixture(autouse=True)
def _keyed_env(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)


def test_valid_proposal_accepted_with_all_authority_fields_false():
    adapter, _, request = make_adapter()
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.ACCEPTED
    assert result.adapter_invoked is True
    assert result.plan is not None
    assert all(getattr(result.plan, name) is False for name in AUTHORITY_FIELDS)
    assert result.plan.provider_identity == "openrouter"
    assert result.plan.model_identity == TEST_MODEL_A
    assert result.plan.request_fingerprint == request.request_fingerprint


def test_tampered_authority_field_rejected():
    request = make_request()
    fake = FakeTransport([make_envelope(request, execution_authorized=True)])
    adapter, _, _ = make_adapter(request=request, transport=fake)
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.invented-authority",)
    assert result.plan is None


def test_fingerprint_mismatch_rejected():
    # The adapter overwrites request_fingerprint deterministically, so a
    # forged binding cannot pass through it. This test proves the kernel's
    # binding check still rejects a non-conforming adapter response.
    request = make_request()
    other = make_request(issue_number=9999, invocation_id="other")

    class ForgingAdapter:
        def propose(self, request_payload):
            content = make_envelope(request)["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            parsed["request_fingerprint"] = other.request_fingerprint
            return parsed

    result = propose_high_reasoning_plan(request, ForgingAdapter())
    assert result.outcome is ProposalOutcome.REJECTED
    assert result.reason_codes == ("proposal.binding-mismatch",)


def test_adapter_unavailable_maps_to_needs_decision(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    adapter, _, request = make_adapter()
    result = propose_high_reasoning_plan(request, adapter)
    assert result.outcome is ProposalOutcome.NEEDS_DECISION
    assert result.reason_codes == ("provider.unavailable",)
    assert result.adapter_invoked is True
