import json

import pytest

from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    RepositoryStateValidationResult,
    WorktreeState,
    reconstruct_repository_state_validation_result,
    serialize_repository_state_validation_result,
    validate_repository_state_evidence,
)
from scripts.agent_os_execution_capabilities.repository_state import (
    _repository_state_validation_result_payload,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
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


def _result(**overrides):
    values = {
        "outcome": "valid",
        "schema_version": "1.0",
        "evidence_id": "evidence-1",
        "repository_identity": _identity(),
        "base_ref": "main",
        "base_sha": SHA_B,
        "head_ref": "agent/branch",
        "head_sha": SHA_A,
        "requested_ref": "agent/branch",
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
        "reason_codes": (),
        "details": (),
    }
    values.update(overrides)
    return RepositoryStateValidationResult(**values)


def test_round_trip_full_result():
    result = _result()
    payload = serialize_repository_state_validation_result(result)
    assert reconstruct_repository_state_validation_result(payload) == result


def test_round_trip_minimal_needs_decision_result():
    result = RepositoryStateValidationResult(
        outcome="needs-decision",
        schema_version="0.0",
        evidence_id="",
        repository_identity=None,
        base_ref=None,
        base_sha=None,
        head_ref=None,
        head_sha=None,
        requested_ref=None,
        requested_sha=None,
        observed_sha=None,
        tested_sha=None,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
        evidence_type=None,
        contract_fingerprint=None,
        worktree_state=None,
        reason_codes=("schema.unknown-field",),
        details=("reason:schema.unknown-field",),
    )
    payload = serialize_repository_state_validation_result(result)
    assert reconstruct_repository_state_validation_result(payload) == result


@pytest.mark.parametrize("outcome", ["valid", "stale", "blocked", "invalid", "needs-decision"])
def test_round_trip_each_outcome(outcome):
    result = _result(outcome=outcome)
    payload = serialize_repository_state_validation_result(result)
    assert reconstruct_repository_state_validation_result(payload) == result


def test_serialization_is_deterministic():
    result = _result()
    first = serialize_repository_state_validation_result(result)
    second = serialize_repository_state_validation_result(result)
    assert first == second
    assert json.loads(first) == json.loads(second)


def test_identity_round_trip_with_fork_fields():
    identity = _identity(
        is_fork=True,
        upstream_owner="upstream-owner",
        upstream_repository="upstream-repo",
        upstream_repository_id=456,
    )
    result = _result(repository_identity=identity)
    payload = serialize_repository_state_validation_result(result)
    reconstructed = reconstruct_repository_state_validation_result(payload)
    assert reconstructed.repository_identity == identity


def test_reconstruct_from_bytes_and_str_and_mapping():
    result = _result()
    payload_bytes = serialize_repository_state_validation_result(result)
    payload_text = payload_bytes.decode("utf-8")
    payload_mapping = _repository_state_validation_result_payload(result)
    assert reconstruct_repository_state_validation_result(payload_bytes) == result
    assert reconstruct_repository_state_validation_result(payload_text) == result
    assert reconstruct_repository_state_validation_result(payload_mapping) == result


def test_reject_noncanonical_bytes_with_reordered_keys():
    payload = _repository_state_validation_result_payload(_result())
    reordered_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert reordered_text.encode("utf-8") != serialize_repository_state_validation_result(
        _result()
    )
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(reordered_text.encode("utf-8"))


def test_reject_noncanonical_text_with_extra_whitespace():
    canonical = serialize_repository_state_validation_result(_result()).decode("utf-8")
    padded_text = canonical.replace(",", ", ")
    assert padded_text != canonical
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(padded_text)


def test_reject_bool_for_repository_id():
    payload = _repository_state_validation_result_payload(_result())
    payload["repository_identity"]["repository_id"] = True
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_bool_for_upstream_repository_id():
    identity = _identity(
        is_fork=True,
        upstream_owner="upstream-owner",
        upstream_repository="upstream-repo",
        upstream_repository_id=456,
    )
    payload = _repository_state_validation_result_payload(_result(repository_identity=identity))
    payload["repository_identity"]["upstream_repository_id"] = False
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_missing_field():
    payload = _repository_state_validation_result_payload(_result())
    del payload["evidence_id"]
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_unknown_field():
    payload = _repository_state_validation_result_payload(_result())
    payload["extra_field"] = "unexpected"
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_malformed_outcome():
    payload = _repository_state_validation_result_payload(_result())
    payload["outcome"] = "not-a-real-outcome"
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_malformed_evidence_type_enum():
    payload = _repository_state_validation_result_payload(_result())
    payload["evidence_type"] = "not-a-real-type"
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_malformed_worktree_state_enum():
    payload = _repository_state_validation_result_payload(_result())
    payload["worktree_state"] = "not-a-real-state"
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_malformed_identity_missing_field():
    payload = _repository_state_validation_result_payload(_result())
    del payload["repository_identity"]["host"]
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_non_list_reason_codes():
    payload = _repository_state_validation_result_payload(_result())
    payload["reason_codes"] = ("schema.unknown-field",)
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_non_list_details():
    payload = _repository_state_validation_result_payload(_result())
    payload["details"] = ("reason:schema.unknown-field",)
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_execution_authorized_drift():
    payload = _repository_state_validation_result_payload(_result())
    payload["execution_authorized"] = True
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_side_effects_performed_drift():
    payload = _repository_state_validation_result_payload(_result())
    payload["side_effects_performed"] = True
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_reject_noncanonical_payload_drift():
    payload = _repository_state_validation_result_payload(
        _result(reason_codes=("worktree.dirty", "schema.unknown-field"))
    )
    # Unsorted reason_codes drift from the canonical sorted transport form.
    payload["reason_codes"] = ["worktree.dirty", "schema.unknown-field"]
    with pytest.raises(ValueError):
        reconstruct_repository_state_validation_result(payload)


def test_serialize_rejects_wrong_type():
    with pytest.raises(TypeError):
        serialize_repository_state_validation_result(object())


def test_reconstruct_rejects_wrong_type():
    with pytest.raises(TypeError):
        reconstruct_repository_state_validation_result(123)


def test_validate_repository_state_evidence_unchanged_for_invalid_mapping():
    result = validate_repository_state_evidence({"not": "valid"})
    assert result.outcome == "invalid"
    assert result.execution_authorized is False
    assert result.side_effects_performed is False
    payload = serialize_repository_state_validation_result(result)
    assert reconstruct_repository_state_validation_result(payload) == result
