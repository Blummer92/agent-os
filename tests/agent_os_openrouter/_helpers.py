"""Shared offline fixtures for the OpenRouter pilot tests. Zero network."""

from __future__ import annotations

import json
from typing import Any

from scripts.agent_os_openrouter.adapter import OpenRouterProposalAdapter
from scripts.agent_os_openrouter.config import OpenRouterConfig
from scripts.agent_os_pr_remediation.high_reasoning_proposal import (
    AUTHORITY_FIELDS,
    PROPOSAL_SCHEMA_VERSION,
    REQUEST_SCHEMA_VERSION,
    ProposalRequest,
    ProposalType,
)

SHA = "a" * 40
BASE_SHA = "b" * 40
AUTH_FP = "c" * 64
SOURCE_FP = "d" * 64

TEST_API_KEY = "sk-test-pilot-key-abc123XYZ"
TEST_MODEL_A = "vendor-a/model-a"
TEST_MODEL_B = "vendor-b/model-b"


def make_config(**changes) -> OpenRouterConfig:
    values: dict[str, Any] = dict(
        enabled=True,
        max_tokens_per_request=512,
        max_requests_per_investigation=8,
        max_total_tokens=100_000,
        timeout_seconds=5.0,
        max_retries=2,
        retry_backoff_seconds=0.0,
        model_a=TEST_MODEL_A,
        model_b=TEST_MODEL_B,
    )
    values.update(changes)
    return OpenRouterConfig(**values)


def make_request(**changes) -> ProposalRequest:
    values: dict[str, Any] = dict(
        schema_version=REQUEST_SCHEMA_VERSION,
        repository="Blummer92/agent-os",
        issue_number=3637,
        pr_number=None,
        invocation_id="issue-3637",
        source_sha=SHA,
        observed_source_sha=SHA,
        base_branch="main",
        base_sha=BASE_SHA,
        objective="Investigate the reported defect and propose a bounded repair plan.",
        non_goals=("No execution.", "No GitHub mutation."),
        allowed_paths=("scripts/agent_os_openrouter/",),
        forbidden_paths=(".github/",),
        required_validations=("pytest-focused",),
        required_prohibited_changes=("No new executor route.",),
        blockers=(),
        changed_paths=(),
        compute_route="high-reasoning-required",
        authorization_state="authorized",
        authorization_fingerprint=AUTH_FP,
        proposal_type=ProposalType.EXECUTION,
        contract_versions=("prr2:1.0",),
        source_fingerprints=(SOURCE_FP,),
        normalized_evidence_refs=("evidence:openrouter-pilot",),
        provider_capability_requirements=("high-reasoning",),
        human_evidence_state="clear",
    )
    values.update(changes)
    return ProposalRequest(**values)


def make_proposal_content(request: ProposalRequest, **changes) -> str:
    """Schema-valid proposal JSON, as the model would return it."""
    values: dict[str, Any] = dict(
        schema_version=PROPOSAL_SCHEMA_VERSION,
        plan_type=request.proposal_type.value,
        request_fingerprint="tampered-by-fixture",  # adapter overwrites deterministically
        provider_identity="tampered-by-fixture",  # adapter overwrites deterministically
        model_identity="tampered-by-fixture",  # adapter overwrites deterministically
        evidence_refs=list(request.normalized_evidence_refs),
        non_goals=list(request.non_goals),
        steps=[
            {
                "action": "inspect",
                "summary": "Inspect the bounded pilot module.",
                "target_paths": ["scripts/agent_os_openrouter/adapter.py"],
                "validation_refs": ["pytest-focused"],
            },
        ],
        proposed_files=["scripts/agent_os_openrouter/adapter.py"],
        prohibited_changes=list(request.required_prohibited_changes),
        validations=list(request.required_validations),
        blockers=list(request.blockers),
        rollback_concept="Revert the pilot package.",
        executor_route_requirements=["chatgpt-governed-runner"],
        insufficiency_reason="Classified high-reasoning-required by the kernel.",
        uncertainty=[],
        expiry_condition="Expires when any bound request evidence changes.",
        invalidation_conditions=["Regenerate after any bound request evidence changes."],
        **{name: False for name in AUTHORITY_FIELDS},
    )
    values.update(changes)
    return json.dumps(values)


def make_envelope(request: ProposalRequest, tokens: int = 150, **content_changes) -> dict[str, Any]:
    return {
        "id": "gen-test-1",
        "choices": [{"message": {"role": "assistant", "content": make_proposal_content(request, **content_changes)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": tokens},
    }


class FakeTransport:
    """Injectable transport. Records calls; replays scripted outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, body, headers, timeout):
        self.calls.append({"body": body, "headers": headers, "timeout": timeout})
        outcome = self.outcomes.pop(0) if self.outcomes else self.outcomes_default()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def outcomes_default(self):
        raise AssertionError("fake transport called more times than scripted")


def make_adapter(request=None, config=None, transport=None, model_identity=TEST_MODEL_A, **config_changes):
    cfg = config or make_config(**config_changes)
    req = request or make_request()
    fake = transport or FakeTransport([make_envelope(req)])
    adapter = OpenRouterProposalAdapter(cfg, model_identity, transport=fake)
    return adapter, fake, req
