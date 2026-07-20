from dataclasses import asdict

import pytest

from scripts.agent_os_execution_capabilities import (
    CAPABILITY_EVIDENCE_SCHEMA_NAME,
    CAPABILITY_EVIDENCE_SCHEMA_VERSION,
    CapabilityStatus,
    EvidenceStrength,
    ExecutionDecision,
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateEvidence,
    WorktreeState,
    validate_capability_evidence,
    validate_repository_state_evidence,
)
from scripts.agent_os_execution_capabilities.reason_codes import APPROVED_REASON_CODES

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
DIGEST = "d" * 64


def _identity(**overrides):
    values = {
        "host": "github.com",
        "owner": "blummer92",
        "repository": "agent-os",
        "repository_id": 123,
        "is_fork": False,
        "default_branch": "main",
    }
    values.update(overrides)
    return RepositoryIdentity(**values)


def _state(**overrides):
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


def _mapping(state=None):
    state = state or _state()
    payload = asdict(state)
    payload["repository_identity"] = asdict(state.repository_identity)
    payload["evidence_type"] = state.evidence_type.value
    payload["worktree_state"] = [item.value for item in state.worktree_state]
    payload.pop("execution_authorized", None)
    return payload


def _capability_mapping(**overrides):
    values = {
        "schema_name": CAPABILITY_EVIDENCE_SCHEMA_NAME,
        "evidence_schema_version": CAPABILITY_EVIDENCE_SCHEMA_VERSION,
        "serializer_version": "1.0",
        "producer_adapter": "fixture-adapter",
        "producer_adapter_version": "1.0",
        "correlation_id": "issue-361",
        "environment_class": "repository-validate-only",
        "repository_identity": asdict(_identity()),
        "base_ref": "main",
        "head_ref": "agent/gex1b-read-only-evidence",
        "observed_sha": SHA_A,
        "contract_fingerprint": DIGEST,
        "capabilities": [
            {
                "capability_id": "repository-checkout-read",
                "status": CapabilityStatus.AVAILABLE.value,
                "evidence_strength": EvidenceStrength.OBSERVED.value,
                "operation_scope": "repository-read",
                "repository_scope": "blummer92/agent-os",
                "ref_scope": "main",
                "sha_scope": SHA_A,
                "principal_type": None,
                "runtime_fingerprint": None,
                "freshness_boundary": "workflow-run-1",
                "reason_code": "adapter.evidence-observed",
                "reason": "Bounded fixture evidence.",
                "required_handoff": None,
            }
        ],
        "invalidation_reasons": [],
        "handoffs": [],
        "decision": ExecutionDecision.PROCEED.value,
    }
    values.update(overrides)
    return values


def test_valid_branch_head_evidence_proceeds():
    state = _state()
    result = validate_repository_state_evidence(
        state,
        expected_repository=_identity(),
        expected_base_ref="main",
        expected_base_sha=SHA_B,
        expected_head_ref="agent/gex1b-read-only-evidence",
        expected_head_sha=SHA_A,
        expected_requested_sha=SHA_A,
        expected_contract_fingerprint=DIGEST,
        expected_pr_sha=SHA_A,
    )
    assert result.valid is True
    assert result.decision == ExecutionDecision.PROCEED
    assert result.reason_codes == ()
    assert result.tested_sha == SHA_A
    assert result.execution_authorized is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("base_ref", "release", "ref.base-mismatch"),
        ("base_sha", SHA_C, "ref.base-mismatch"),
        ("head_ref", "other", "ref.head-mismatch"),
        ("head_sha", SHA_C, "ref.branch-moved"),
        ("contract_fingerprint", "e" * 64, "ref.contract-mismatch"),
    ],
)
def test_expected_repository_bindings_fail_closed(field, value, reason):
    state = _state()
    kwargs = {
        "expected_base_ref": "main",
        "expected_base_sha": SHA_B,
        "expected_head_ref": "agent/gex1b-read-only-evidence",
        "expected_head_sha": SHA_A,
        "expected_contract_fingerprint": DIGEST,
    }
    expected_map = {
        "base_ref": "expected_base_ref",
        "base_sha": "expected_base_sha",
        "head_ref": "expected_head_ref",
        "head_sha": "expected_head_sha",
        "contract_fingerprint": "expected_contract_fingerprint",
    }
    kwargs[expected_map[field]] = value
    result = validate_repository_state_evidence(state, **kwargs)
    assert result.decision == ExecutionDecision.HANDOFF_REQUIRED
    assert reason in result.reason_codes


def test_wrong_repository_and_fork_mismatch_are_distinct():
    state = _state()
    wrong = validate_repository_state_evidence(
        state,
        expected_repository=_identity(owner="different"),
    )
    assert "repo.identity-mismatch" in wrong.reason_codes

    fork = _identity(
        is_fork=True,
        upstream_owner="blummer92",
        upstream_repository="agent-os",
    )
    mismatch = validate_repository_state_evidence(state, expected_repository=fork)
    assert "repo.fork-upstream-mismatch" in mismatch.reason_codes


def test_observed_sha_and_requested_sha_cannot_substitute_for_tested_sha():
    stale = validate_repository_state_evidence(_state(observed_sha=SHA_C))
    assert "ref.observed-sha-stale" in stale.reason_codes

    requested = validate_repository_state_evidence(_state(requested_sha=SHA_C))
    assert "ref.requested-tested-mismatch" in requested.reason_codes


def test_missing_tested_sha_needs_decision():
    result = validate_repository_state_evidence(_state(tested_sha=None))
    assert result.decision == ExecutionDecision.NEEDS_DECISION
    assert "ref.tested-sha-missing" in result.reason_codes


def test_branch_head_and_synthetic_merge_evidence_remain_distinct():
    branch = validate_repository_state_evidence(_state())
    assert branch.decision == ExecutionDecision.PROCEED

    synthetic = _state(
        tested_sha=SHA_C,
        synthetic_merge_sha=SHA_C,
        external_build_sha=SHA_C,
        evidence_type=RepositoryEvidenceType.SYNTHETIC_PR_MERGE,
    )
    result = validate_repository_state_evidence(synthetic)
    assert result.decision == ExecutionDecision.PROCEED
    assert result.tested_sha == SHA_C

    mislabeled = validate_repository_state_evidence(
        _state(tested_sha=SHA_C, evidence_type=RepositoryEvidenceType.BRANCH_HEAD)
    )
    assert "ref.tested-sha-mismatch" in mislabeled.reason_codes


def test_cloud_build_result_cannot_be_attached_to_another_sha():
    result = validate_repository_state_evidence(_state(external_build_sha=SHA_C))
    assert result.decision == ExecutionDecision.HANDOFF_REQUIRED
    assert "ref.build-sha-mismatch" in result.reason_codes


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (WorktreeState.DIRTY, "worktree.dirty"),
        (WorktreeState.UNTRACKED, "worktree.untracked"),
        (WorktreeState.IGNORED, "worktree.ignored-relevant"),
        (WorktreeState.DETACHED, "worktree.detached"),
        (WorktreeState.SHALLOW, "worktree.shallow"),
        (WorktreeState.UNRESOLVED_OPERATION, "worktree.unresolved-operation"),
        (WorktreeState.UNCOMMITTED, "worktree.uncommitted"),
    ],
)
def test_worktree_states_are_conservative(state, reason):
    result = validate_repository_state_evidence(_state(worktree_state=(state,)))
    assert result.decision == ExecutionDecision.HANDOFF_REQUIRED
    assert reason in result.reason_codes


def test_unknown_field_flood_collapses_to_one_bounded_reason():
    payload = _mapping()
    payload.update({f"unknown_{index}": index for index in range(500)})
    result = validate_repository_state_evidence(payload)
    assert result.decision == ExecutionDecision.NEEDS_DECISION
    assert result.reason_codes.count("schema.unknown-field") == 1
    assert set(result.reason_codes) <= APPROVED_REASON_CODES


@pytest.mark.parametrize("version", [["1.0"], {"value": "1.0"}, 1, True, None])
def test_unhashable_and_non_string_versions_fail_closed(version):
    payload = _mapping()
    payload["evidence_schema_version"] = version
    result = validate_repository_state_evidence(payload)
    assert result.decision == ExecutionDecision.NEEDS_DECISION
    assert any(code.startswith("schema.version-") for code in result.reason_codes)


def test_capability_validation_aggregates_decisions_without_authorization():
    available = validate_capability_evidence(_capability_mapping())
    assert available.decision == ExecutionDecision.PROCEED
    assert available.execution_authorized is False

    unavailable_payload = _capability_mapping()
    unavailable_payload["capabilities"][0]["status"] = "unavailable"
    unavailable_payload["capabilities"][0]["required_handoff"] = "local-shell"
    unavailable_payload["decision"] = "handoff-required"
    unavailable = validate_capability_evidence(unavailable_payload)
    assert unavailable.decision == ExecutionDecision.HANDOFF_REQUIRED

    indeterminate_payload = _capability_mapping()
    indeterminate_payload["capabilities"][0]["status"] = "indeterminate"
    indeterminate_payload["decision"] = "needs-decision"
    indeterminate = validate_capability_evidence(indeterminate_payload)
    assert indeterminate.decision == ExecutionDecision.NEEDS_DECISION


def test_capability_unknown_field_flood_is_bounded():
    payload = _capability_mapping()
    payload.update({f"unknown_{index}": index for index in range(500)})
    result = validate_capability_evidence(payload)
    assert result.invalidation_reasons.count("schema.unknown-field") == 1
    assert result.decision == ExecutionDecision.NEEDS_DECISION


def test_secret_like_supplied_values_fail_closed_without_echo():
    payload = _capability_mapping(correlation_id="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
    result = validate_capability_evidence(payload)
    assert "schema.secret-like-value" in result.invalidation_reasons
    assert "ghp_" not in repr(result)


def test_validators_do_not_require_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)

    assert validate_repository_state_evidence(_state()).decision == ExecutionDecision.PROCEED
    assert validate_capability_evidence(_capability_mapping()).decision == ExecutionDecision.PROCEED
