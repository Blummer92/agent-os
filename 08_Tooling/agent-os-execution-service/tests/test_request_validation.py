from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_execution_capabilities import RepositoryIdentity
from agent_os_execution_service import (
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceReason,
    ExecutionServiceRequest,
    ExecutionServiceResult,
    ExecutionServiceStatus,
    PrivateEvidence,
    project_public_result,
    validate_execution_service_request,
)

A = "a" * 40
B = "b" * 40


def identity() -> RepositoryIdentity:
    return RepositoryIdentity(
        host="github.com",
        owner="blummer92",
        repository="agent-os",
        repository_id=123,
        default_branch="main",
    )


def request(**overrides: object) -> ExecutionServiceRequest:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "wsc6b1-001",
        "request_revision": 1,
        "created_at": "2026-07-27T03:00:00Z",
        "expires_at": "2026-07-27T04:00:00Z",
        "repository_identity": identity(),
        "issue_or_handoff_identity": "issue:634",
        "canonical_owner": "integration-manager",
        "requesting_actor": "github-service-agent",
        "capability": ExecutionServiceCapability.INSPECT_REPOSITORY,
        "base_branch": "main",
        "base_sha": A,
        "requested_ref": "agent/634-wsc6b1-read-only-execution-service",
        "expected_sha": B,
        "allowed_paths": ("08_Tooling/agent-os-execution-service",),
        "forbidden_paths": ("secrets",),
        "inspected_file_count_limit": 8,
        "inspected_byte_limit": 100_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": tuple(
            sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
        ),
    }
    values.update(overrides)
    return ExecutionServiceRequest(**values)  # type: ignore[arg-type]


def result(**overrides: object) -> ExecutionServiceResult:
    req = request()
    values: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": req.request_id,
        "request_revision": 1,
        "request_fingerprint": req.request_fingerprint,
        "evaluated_at": "2026-07-27T03:30:00Z",
        "service_version": "0.1.0",
        "status": ExecutionServiceStatus.ACCEPTED,
        "reasons": (ExecutionServiceReason.ACCEPTED,),
        "repository_identity": req.repository_identity,
        "requested_ref": req.requested_ref,
        "expected_sha": req.expected_sha,
        "observed_ref": req.requested_ref,
        "observed_sha": req.expected_sha,
        "inspected_file_count": 1,
        "inspected_byte_count": 10,
        "public_summary": "status=accepted",
    }
    values.update(overrides)
    return ExecutionServiceResult(**values)  # type: ignore[arg-type]


def test_deterministic_immutable_fingerprints() -> None:
    assert request().request_fingerprint == request().request_fingerprint
    assert result().result_fingerprint == result().result_fingerprint
    with pytest.raises(FrozenInstanceError):
        request().request_id = "changed"  # type: ignore[misc]


def test_bool_and_hostile_tuple_are_rejected_without_iteration() -> None:
    with pytest.raises(TypeError):
        request(request_revision=True)
    touched = False

    class EvilTuple(tuple):
        def __iter__(self):
            nonlocal touched
            touched = True
            raise AssertionError("must not iterate")

    with pytest.raises(TypeError):
        request(allowed_paths=EvilTuple(("x",)))
    assert touched is False


@pytest.mark.parametrize(
    "path",
    ("/x", "../x", "a/../b", "a//b", "a\\b", "a/./b", "a\x00b"),
)
def test_noncanonical_paths(path: str) -> None:
    with pytest.raises(ValueError):
        request(allowed_paths=(path,))


def test_overlap_and_copied_fingerprint_are_rejected() -> None:
    with pytest.raises(ValueError):
        request(
            allowed_paths=("08_Tooling",),
            forbidden_paths=("08_Tooling/private",),
        )
    req = request()
    with pytest.raises(ValueError):
        replace(req, expected_sha=A, request_fingerprint=req.request_fingerprint)


def test_time_and_schema_reasons_are_bounded_and_sorted() -> None:
    assert validate_execution_service_request(
        request(), evaluated_at="2026-07-27T03:00:00Z"
    ) == ()
    assert validate_execution_service_request(
        request(), evaluated_at="2026-07-27T04:00:00Z"
    ) == (ExecutionServiceReason.EXPIRED_REQUEST,)
    reasons = validate_execution_service_request(
        request(schema_version="2.0"), evaluated_at="2026-07-27T05:00:00Z"
    )
    assert reasons == tuple(sorted(reasons, key=lambda item: item.value))
    assert set(reasons) == {
        ExecutionServiceReason.EXPIRED_REQUEST,
        ExecutionServiceReason.UNSUPPORTED_SCHEMA,
    }


@pytest.mark.parametrize(
    "timestamp",
    (
        "2026-07-27T03:00:00",
        "2026-07-27T03:00:00+00:00",
        "2026-07-27 03:00:00Z",
        "2026-07-27T03:00:00.000Z",
    ),
)
def test_noncanonical_times(timestamp: str) -> None:
    with pytest.raises(ValueError):
        request(created_at=timestamp)


def test_result_reason_invariants() -> None:
    with pytest.raises(ValueError):
        result(
            status=ExecutionServiceStatus.ACCEPTED,
            reasons=(ExecutionServiceReason.EVIDENCE_UNAVAILABLE,),
        )
    with pytest.raises(ValueError):
        result(
            status=ExecutionServiceStatus.REJECTED,
            reasons=(ExecutionServiceReason.ACCEPTED,),
        )


def test_private_evidence_never_projects() -> None:
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    value = result(
        private_evidence=(PrivateEvidence(label="diagnostic", value=secret),)
    )
    assert secret not in repr(value)
    public = project_public_result(value)
    assert "private_evidence" not in public
    assert secret not in str(public)
    assert public["side_effects_performed"] is False
