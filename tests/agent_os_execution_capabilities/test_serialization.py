import json

import pytest

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    CapabilityEvidence,
    CapabilityEvidenceEnvelope,
    CapabilityStatus,
    EvidenceStrength,
    ExecutionDecision,
    RepositoryIdentity,
    serialize_capability_evidence,
)

SHA = "a" * 40
DIGEST = "d" * 64


def _capability(capability_id, strength=EvidenceStrength.OBSERVED, reason="bounded"):
    return CapabilityEvidence(
        capability_id=capability_id,
        status=CapabilityStatus.AVAILABLE,
        evidence_strength=strength,
        operation_scope="repository-read",
        repository_scope="blummer92/agent-os",
        ref_scope="main",
        sha_scope=SHA,
        reason_code="adapter.incompatible",
        reason=reason,
    )


def _envelope(capabilities=None):
    return CapabilityEvidenceEnvelope(
        schema_name=CAPABILITY_EVIDENCE_SCHEMA_NAME,
        evidence_schema_version=CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        serializer_version="1.0",
        producer_adapter="fixture-adapter",
        producer_adapter_version="1.0",
        correlation_id="issue-361",
        environment_class="repository-validate-only",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        base_ref="main",
        head_ref="agent/gex1b-read-only-evidence",
        observed_sha=SHA,
        contract_fingerprint=DIGEST,
        capabilities=capabilities
        or (
            _capability("repository-checkout-read"),
            _capability("aggregate-validation-run", EvidenceStrength.EXERCISED),
        ),
        invalidation_reasons=(),
        handoffs=(),
        decision=ExecutionDecision.PROCEED,
    )


def test_serialization_is_byte_exact_deterministic_and_newline_terminated():
    first = serialize_capability_evidence(_envelope())
    second = serialize_capability_evidence(_envelope())
    assert first == second
    assert first.endswith(b"\n")
    assert not first.endswith(b"\n\n")
    assert first.decode("utf-8") == json.dumps(
        json.loads(first),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def test_capability_order_is_canonical():
    forward = _envelope(
        capabilities=(
            _capability("repository-checkout-read"),
            _capability("aggregate-validation-run"),
        )
    )
    reverse = _envelope(capabilities=tuple(reversed(forward.capabilities)))
    assert serialize_capability_evidence(forward) == serialize_capability_evidence(reverse)


def test_serializer_has_exact_governed_top_level_keys():
    payload = json.loads(serialize_capability_evidence(_envelope()))
    assert set(payload) == {
        "schema_name",
        "evidence_schema_version",
        "serializer_version",
        "producer_adapter",
        "producer_adapter_version",
        "correlation_id",
        "environment_class",
        "repository_identity",
        "base_ref",
        "head_ref",
        "observed_sha",
        "contract_fingerprint",
        "capabilities",
        "invalidation_reasons",
        "handoffs",
        "decision",
        "execution_authorized",
        "side_effects_performed",
    }
    assert payload["execution_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_serializer_rejects_wrong_type():
    with pytest.raises(TypeError):
        serialize_capability_evidence({})


def test_serializer_rejects_secret_like_content():
    envelope = _envelope(
        capabilities=(
            _capability(
                "repository-checkout-read",
                reason="github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
            ),
        )
    )
    with pytest.raises(ValueError):
        serialize_capability_evidence(envelope)


def test_serialized_output_contains_no_secret_or_absolute_host_path():
    output = serialize_capability_evidence(_envelope()).decode("utf-8")
    assert "ghp_" not in output
    assert "github_pat_" not in output
    assert "PRIVATE KEY" not in output
    assert "/home/" not in output
    assert "C:\\Users\\" not in output
