from dataclasses import FrozenInstanceError

import pytest

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    CapabilityEvidence,
    CapabilityEvidenceEnvelope,
    CapabilityStatus,
    EvidenceStrength,
    ExecutionDecision,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "d" * 64


def _identity(**overrides):
    values = {
        "host": "github.com",
        "owner": "Blummer92",
        "repository": "Agent-OS",
        "repository_id": 123,
        "is_fork": False,
        "default_branch": "main",
    }
    values.update(overrides)
    return RepositoryIdentity(**values)


def _capability(capability_id="repository-checkout-read", **overrides):
    values = {
        "capability_id": capability_id,
        "status": CapabilityStatus.AVAILABLE,
        "evidence_strength": EvidenceStrength.OBSERVED,
        "operation_scope": "repository-read",
        "repository_scope": "blummer92/agent-os",
        "ref_scope": "main",
        "sha_scope": SHA_A,
        "reason_code": "adapter.evidence-observed",
        "reason": "Repository identity and revision were supplied.",
    }
    values.update(overrides)
    return CapabilityEvidence(**values)


def _envelope(**overrides):
    values = {
        "schema_name": CAPABILITY_EVIDENCE_SCHEMA_NAME,
        "evidence_schema_version": CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        "serializer_version": "1.0",
        "producer_adapter": "fixture-adapter",
        "producer_adapter_version": "1.0",
        "correlation_id": "issue-361",
        "environment_class": "repository-validate-only",
        "repository_identity": _identity(),
        "base_ref": "main",
        "head_ref": "agent/gex1b-read-only-evidence",
        "observed_sha": SHA_A,
        "contract_fingerprint": DIGEST,
        "capabilities": (_capability(),),
        "invalidation_reasons": (),
        "handoffs": (),
        "decision": ExecutionDecision.PROCEED,
    }
    values.update(overrides)
    return CapabilityEvidenceEnvelope(**values)


def _repository_state(**overrides):
    values = {
        "schema_name": CAPABILITY_EVIDENCE_SCHEMA_NAME,
        "evidence_schema_version": CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        "producer_adapter": "fixture-adapter",
        "producer_adapter_version": "1.0",
        "correlation_id": "issue-361",
        "repository_identity": _identity(),
        "base_ref": "main",
        "base_sha": SHA_B,
        "head_ref": "agent/gex1b-read-only-evidence",
        "head_sha": SHA_A,
        "requested_ref": "agent/gex1b-read-only-evidence",
        "requested_sha": SHA_A,
        "observed_sha": SHA_A,
        "tested_sha": SHA_A,
        "pushed_sha": SHA_A,
        "proposed_pr_sha": SHA_A,
        "synthetic_merge_sha": None,
        "external_build_sha": SHA_A,
        "evidence_type": RepositoryEvidenceType.BRANCH_HEAD,
        "contract_fingerprint": DIGEST,
        "worktree_state": (WorktreeState.CLEAN,),
        "observed_at": "2026-07-20T02:00:00Z",
        "freshness_boundary": "workflow-run-1",
    }
    values.update(overrides)
    return RepositoryStateEvidence(**values)


def test_schema_identity_is_exact():
    assert CAPABILITY_EVIDENCE_SCHEMA_NAME == "agent-os-capability-evidence"
    assert CAPABILITY_EVIDENCE_SCHEMA_VERSION == "1.0"


def test_required_enum_values_are_exact():
    assert tuple(item.value for item in CapabilityStatus) == (
        "available",
        "unavailable",
        "indeterminate",
        "not-required",
    )
    assert tuple(item.value for item in EvidenceStrength) == (
        "declared",
        "observed",
        "exercised",
    )
    assert tuple(item.value for item in ExecutionDecision) == (
        "proceed",
        "proceed-with-limits",
        "handoff-required",
        "needs-decision",
    )


def test_models_are_frozen_and_authorization_is_not_constructible():
    envelope = _envelope()
    state = _repository_state()
    with pytest.raises(FrozenInstanceError):
        envelope.decision = ExecutionDecision.NEEDS_DECISION
    with pytest.raises(FrozenInstanceError):
        state.head_sha = SHA_B
    with pytest.raises(TypeError):
        _envelope(execution_authorized=True)


def test_repository_identity_is_canonicalized():
    identity = _identity()
    assert identity.host == "github.com"
    assert identity.owner == "blummer92"
    assert identity.repository == "agent-os"


def test_fork_identity_requires_upstream():
    with pytest.raises(ValueError):
        _identity(is_fork=True)
    fork = _identity(
        is_fork=True,
        upstream_owner="OpenAI",
        upstream_repository="Agent-OS",
    )
    assert fork.upstream_owner == "openai"
    assert fork.upstream_repository == "agent-os"


def test_capabilities_are_sorted_and_duplicate_ids_rejected():
    second = _capability("aggregate-validation-run")
    first = _capability("repository-checkout-read")
    envelope = _envelope(capabilities=(first, second))
    assert tuple(item.capability_id for item in envelope.capabilities) == (
        "aggregate-validation-run",
        "repository-checkout-read",
    )
    with pytest.raises(ValueError):
        _envelope(capabilities=(first, first))


def test_capability_id_must_be_lowercase_kebab_case():
    with pytest.raises(ValueError):
        _capability("Repository Checkout")


def test_repository_state_evidence_id_is_deterministic():
    first = _repository_state()
    second = _repository_state()
    assert first.evidence_id == second.evidence_id
    assert len(first.evidence_id) == 64


def test_repository_state_rejects_mismatched_supplied_id():
    with pytest.raises(ValueError):
        _repository_state(evidence_id="0" * 64)


def test_clean_state_cannot_be_combined_with_findings():
    with pytest.raises(ValueError):
        _repository_state(
            worktree_state=(WorktreeState.CLEAN, WorktreeState.UNTRACKED)
        )
