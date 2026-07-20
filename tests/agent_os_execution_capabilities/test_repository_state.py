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
        "worktree_state": WorktreeState.CLEAN,
        "worktree_reason_codes": (),
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
    payload["worktree_state"] = state.worktree_state.value
    payload.pop("execution_authorized", None)
    payload.pop("side_effects_performed", None)
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
                "reason_code": "adapter.incompatible",
                "reason": "Bounded fixture evidence.",
            }
        ],
        "invalidation_reasons": [],
        "handoffs": [],
        "decision": ExecutionDecision.PROCEED.value,
    }
    values.update(overrides)
    return values


def test_valid_branch_head_preserves_all_bindings():
    result = validate_repository_state_evidence(
        _state(),
        expected_repository=_identity(),
        expected_base_ref="main",
        expected_base_sha=SHA_B,
        expected_head_ref="agent/gex1b-read-only-evidence",
        expected_head_sha=SHA_A,
        expected_requested_sha=SHA_A,
        expected_contract_fingerprint=DIGEST,
        expected_pr_sha=SHA_A,
    )
    assert result.outcome == "valid"
    assert result.repository_identity == _identity()
    assert result.base_sha == SHA_B
    assert result.head_sha == SHA_A
    assert result.tested_sha == SHA_A
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"expected_base_sha": SHA_C}, "ref.base-mismatch"),
        ({"expected_head_sha": SHA_C}, "ref.branch-moved"),
        ({"expected_contract_fingerprint": "e" * 64}, "ref.contract-mismatch"),
        ({"expected_pr_sha": SHA_C}, "ref.pr-head-mismatch"),
    ],
)
def test_binding_changes_are_stale(kwargs, reason):
    result = validate_repository_state_evidence(_state(), **kwargs)
    assert result.outcome == "stale"
    assert reason in result.reason_codes


def test_wrong_repository_and_fork_are_distinct():
    wrong = validate_repository_state_evidence(
        _state(), expected_repository=_identity(owner="different")
    )
    assert wrong.outcome == "stale"
    assert "repo.identity-mismatch" in wrong.reason_codes

    fork = _identity(
        is_fork=True,
        upstream_owner="blummer92",
        upstream_repository="agent-os",
    )
    mismatch = validate_repository_state_evidence(_state(), expected_repository=fork)
    assert "repo.fork-upstream-mismatch" in mismatch.reason_codes


def test_missing_or_mismatched_test_sha_is_stale():
    missing = validate_repository_state_evidence(_state(tested_sha=None))
    assert missing.outcome == "stale"
    assert "ref.test-sha-mismatch" in missing.reason_codes

    mismatch = validate_repository_state_evidence(_state(tested_sha=SHA_C))
    assert mismatch.outcome == "stale"
    assert "ref.stale-sha" in mismatch.reason_codes


def test_synthetic_merge_evidence_remains_distinct():
    synthetic = _state(
        observed_sha=SHA_C,
        tested_sha=SHA_C,
        synthetic_merge_sha=SHA_C,
        external_build_sha=SHA_C,
        evidence_type=RepositoryEvidenceType.SYNTHETIC_PR_MERGE,
    )
    result = validate_repository_state_evidence(synthetic)
    assert result.outcome == "valid"
    assert result.evidence_type == RepositoryEvidenceType.SYNTHETIC_PR_MERGE

    mislabeled = validate_repository_state_evidence(
        _state(tested_sha=SHA_C, evidence_type=RepositoryEvidenceType.BRANCH_HEAD)
    )
    assert mislabeled.outcome == "stale"


def test_worktree_outcomes_are_separate():
    blocked = validate_repository_state_evidence(
        _state(
            worktree_state=WorktreeState.DIRTY,
            worktree_reason_codes=("worktree.untracked",),
        )
    )
    assert blocked.outcome == "blocked"
    assert "worktree.untracked" in blocked.reason_codes

    undecided = validate_repository_state_evidence(
        _state(
            worktree_state=WorktreeState.INDETERMINATE,
            worktree_reason_codes=("worktree.indeterminate",),
        )
    )
    assert undecided.outcome == "needs-decision"


def test_malformed_and_unsupported_versions_are_invalid():
    malformed = _mapping()
    malformed["evidence_schema_version"] = ["1.0"]
    result = validate_repository_state_evidence(malformed)
    assert result.outcome == "invalid"
    assert "schema.malformed-version" in result.reason_codes

    unsupported = _mapping()
    unsupported["evidence_schema_version"] = "2.0"
    result = validate_repository_state_evidence(unsupported)
    assert result.outcome == "invalid"
    assert "schema.unsupported-version" in result.reason_codes


def test_unknown_field_flood_is_bounded():
    payload = _mapping()
    payload.update({f"unknown_{index}": index for index in range(500)})
    result = validate_repository_state_evidence(payload)
    assert result.outcome == "invalid"
    assert result.reason_codes.count("schema.unknown-field") == 1
    assert set(result.reason_codes) <= APPROVED_REASON_CODES


def test_capability_decisions_remain_non_authorizing():
    available = validate_capability_evidence(_capability_mapping())
    assert available.decision == ExecutionDecision.PROCEED
    assert available.execution_authorized is False
    assert available.side_effects_performed is False

    unavailable = _capability_mapping()
    unavailable["capabilities"][0]["status"] = "unavailable"
    result = validate_capability_evidence(unavailable)
    assert result.decision == ExecutionDecision.HANDOFF_REQUIRED


def test_secret_like_values_fail_closed_without_echo():
    payload = _capability_mapping(correlation_id="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
    result = validate_capability_evidence(payload)
    assert result.decision == ExecutionDecision.NEEDS_DECISION
    assert "ghp_" not in repr(result)


def test_validators_do_not_require_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("external operation attempted")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    assert validate_repository_state_evidence(_state()).outcome == "valid"
