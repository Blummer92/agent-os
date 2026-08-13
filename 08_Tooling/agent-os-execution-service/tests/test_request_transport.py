from __future__ import annotations

from copy import deepcopy

import pytest

from agent_os_execution_service import (
    EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
    EvidenceVisibilityPolicy,
    ExecutionServiceCapability,
    ExecutionServiceInvalidationCondition,
    ExecutionServiceRequest,
    execution_service_request_fingerprint,
    reconstruct_execution_service_request,
    serialize_execution_service_request,
)
from scripts.agent_os_execution_capabilities import RepositoryIdentity


SHA_A = "a" * 40
SHA_B = "b" * 40


def _request() -> ExecutionServiceRequest:
    return ExecutionServiceRequest(
        schema_version=EXECUTION_SERVICE_REQUEST_SCHEMA_VERSION,
        request_id="request-1070",
        request_revision=2,
        created_at="2026-08-13T04:00:00Z",
        expires_at="2026-08-13T05:00:00Z",
        repository_identity=RepositoryIdentity(
            host="github.com",
            owner="blummer92",
            repository="agent-os",
            repository_id=123,
            default_branch="main",
        ),
        issue_or_handoff_identity="issue:1070",
        canonical_owner="integration-manager",
        requesting_actor="github-service-agent",
        capability=ExecutionServiceCapability.INSPECT_REPOSITORY,
        base_branch="main",
        base_sha=SHA_A,
        requested_ref="agent/1070-execution-service-request-transport",
        expected_sha=SHA_B,
        allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github",),
        inspected_file_count_limit=100,
        inspected_byte_limit=100_000,
        evidence_visibility_policy=EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        invalidation_conditions=(
            ExecutionServiceInvalidationCondition.EXPECTED_SHA_CHANGED,
            ExecutionServiceInvalidationCondition.REPOSITORY_IDENTITY_CHANGED,
            ExecutionServiceInvalidationCondition.REQUEST_EXPIRED,
        ),
    )


def _payload() -> dict[str, object]:
    return serialize_execution_service_request(_request())


def test_request_transport_round_trip_is_deterministic_and_non_mutating() -> None:
    request = _request()
    original_fingerprint = execution_service_request_fingerprint(request)
    first = serialize_execution_service_request(request)
    snapshot = deepcopy(first)

    reconstructed = reconstruct_execution_service_request(first)

    assert reconstructed == request
    assert execution_service_request_fingerprint(reconstructed) == original_fingerprint
    assert serialize_execution_service_request(reconstructed) == first
    assert serialize_execution_service_request(request) == first
    assert first == snapshot


@pytest.mark.parametrize("field", ["request_id", "request_fingerprint"])
def test_request_transport_rejects_missing_fields(field: str) -> None:
    payload = _payload()
    payload.pop(field)
    with pytest.raises(ValueError, match="invalid request transport fields"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_unknown_field() -> None:
    payload = _payload()
    payload["extra"] = "nope"
    with pytest.raises(ValueError, match="invalid request transport fields"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_unsupported_schema() -> None:
    payload = _payload()
    payload["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="schema_version is unsupported"):
        reconstruct_execution_service_request(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capability", "unknown", "capability is unsupported"),
        ("evidence_visibility_policy", "unknown", "evidence_visibility_policy is unsupported"),
    ],
)
def test_request_transport_rejects_malformed_enums(
    field: str, value: object, message: str
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValueError, match=message):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_malformed_invalidation_condition() -> None:
    payload = _payload()
    payload["invalidation_conditions"] = ["unknown"]
    with pytest.raises(ValueError, match="unsupported value"):
        reconstruct_execution_service_request(payload)


@pytest.mark.parametrize(
    "field",
    ["request_revision", "inspected_file_count_limit", "inspected_byte_limit"],
)
def test_request_transport_rejects_bool_for_integer(field: str) -> None:
    payload = _payload()
    payload[field] = True
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_repository_id_bool() -> None:
    payload = _payload()
    repository = payload["repository_identity"]
    assert type(repository) is dict
    repository["repository_id"] = True
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_noncanonical_repository_identity() -> None:
    payload = _payload()
    repository = payload["repository_identity"]
    assert type(repository) is dict
    repository["owner"] = "Blummer92"
    with pytest.raises(ValueError, match="not canonical"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_repository_identity_field_drift() -> None:
    payload = _payload()
    repository = payload["repository_identity"]
    assert type(repository) is dict
    repository["extra"] = "nope"
    with pytest.raises(ValueError, match="repository_identity fields"):
        reconstruct_execution_service_request(payload)


@pytest.mark.parametrize("field", ["allowed_paths", "forbidden_paths", "invalidation_conditions"])
def test_request_transport_requires_list_shapes(field: str) -> None:
    payload = _payload()
    value = payload[field]
    assert type(value) is list
    payload[field] = tuple(value)
    with pytest.raises(TypeError, match=f"{field} must be an exact list"):
        reconstruct_execution_service_request(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_at", "2026-08-13"),
        ("expires_at", "2026-08-13T05:00:00+00:00"),
        ("base_branch", "bad ref"),
        ("requested_ref", "bad..ref"),
        ("base_sha", "abc"),
        ("expected_sha", "ABC" * 13 + "A"),
    ],
)
def test_request_transport_rejects_invalid_canonical_fields(field: str, value: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_allowed_path_order_and_duplicates() -> None:
    payload = _payload()
    payload["allowed_paths"] = ["z", "a"]
    with pytest.raises(ValueError, match="sorted and unique"):
        reconstruct_execution_service_request(payload)

    payload = _payload()
    payload["allowed_paths"] = ["a", "a"]
    with pytest.raises(ValueError, match="sorted and unique"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_forbidden_path_order() -> None:
    payload = _payload()
    payload["forbidden_paths"] = ["z", "a"]
    with pytest.raises(ValueError, match="sorted and unique"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_allowed_forbidden_overlap() -> None:
    payload = _payload()
    payload["forbidden_paths"] = ["08_Tooling"]
    with pytest.raises(ValueError, match="must not overlap"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_invalidation_order_and_duplicates() -> None:
    payload = _payload()
    payload["invalidation_conditions"] = [
        "request-expired",
        "expected-sha-changed",
    ]
    with pytest.raises(ValueError, match="sorted and unique"):
        reconstruct_execution_service_request(payload)

    payload = _payload()
    payload["invalidation_conditions"] = [
        "request-expired",
        "request-expired",
    ]
    with pytest.raises(ValueError, match="sorted and unique"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_fingerprint_tampering() -> None:
    payload = _payload()
    payload["request_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="request_fingerprint does not match"):
        reconstruct_execution_service_request(payload)


def test_request_transport_rejects_semantic_drift_with_original_fingerprint() -> None:
    payload = _payload()
    payload["request_id"] = "request-1070-tampered"
    with pytest.raises(ValueError, match="request_fingerprint does not match"):
        reconstruct_execution_service_request(payload)
