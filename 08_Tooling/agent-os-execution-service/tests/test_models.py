import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.agent_os_execution_capabilities import RepositoryIdentity
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
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "request_id": "transport-1070-001",
        "request_revision": 1,
        "created_at": "2026-08-12T20:00:00Z",
        "expires_at": "2026-08-12T21:00:00Z",
        "repository_identity": identity(),
        "issue_or_handoff_identity": "issue:1070",
        "canonical_owner": "integration-manager",
        "requesting_actor": "github-service-agent",
        "capability": ExecutionServiceCapability.INSPECT_REPOSITORY,
        "base_branch": "main",
        "base_sha": A,
        "requested_ref": "agent/1070-execution-service-request-transport",
        "expected_sha": B,
        "allowed_paths": (
            "08_Tooling/agent-os-execution-service",
        ),
        "forbidden_paths": ("secrets",),
        "inspected_file_count_limit": 8,
        "inspected_byte_limit": 100_000,
        "evidence_visibility_policy": EvidenceVisibilityPolicy.PUBLIC_SUMMARY_ONLY,
        "invalidation_conditions": tuple(
            sorted(ExecutionServiceInvalidationCondition, key=lambda item: item.value)
        ),
    }
    payload.update(overrides)
    return ExecutionServiceRequest(**payload)


def test_round_trip_equality() -> None:
    value = request()
    payload = serialize_execution_service_request(value)
    rebuilt = reconstruct_execution_service_request(payload)
    assert rebuilt == value


def test_serialize_after_reconstruction_is_identical() -> None:
    value = request()
    payload = serialize_execution_service_request(value)
    rebuilt = reconstruct_execution_service_request(payload)
    assert serialize_execution_service_request(rebuilt) == payload


def test_serialization_is_deterministic_across_repeated_calls() -> None:
    value = request()
    first = serialize_execution_service_request(value)
    second = serialize_execution_service_request(value)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_unknown_field_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["unexpected_field"] = "x"
    with pytest.raises(ValueError, match="unknown or missing"):
        reconstruct_execution_service_request(payload)


def test_missing_field_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    del payload["canonical_owner"]
    with pytest.raises(ValueError, match="unknown or missing"):
        reconstruct_execution_service_request(payload)


def test_unsupported_schema_version_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="schema_version"):
        reconstruct_execution_service_request(payload)


def test_malformed_capability_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["capability"] = "not-a-capability"
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_malformed_evidence_visibility_policy_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["evidence_visibility_policy"] = "not-a-policy"
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_malformed_invalidation_condition_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["invalidation_conditions"] = list(payload["invalidation_conditions"]) + [
        "not-a-condition"
    ]
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_repository_identity_reconstruction() -> None:
    payload = serialize_execution_service_request(request())
    rebuilt = reconstruct_execution_service_request(payload)
    assert rebuilt.repository_identity == identity()


def test_malformed_repository_identity_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["repository_identity"] = dict(payload["repository_identity"])
    del payload["repository_identity"]["host"]
    with pytest.raises(ValueError, match="unknown or missing"):
        reconstruct_execution_service_request(payload)


def test_repository_id_boolean_for_integer_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["repository_identity"] = dict(payload["repository_identity"])
    payload["repository_identity"]["repository_id"] = True
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_request_revision_boolean_for_integer_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["request_revision"] = True
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_inspected_file_count_limit_boolean_for_integer_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["inspected_file_count_limit"] = True
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_inspected_byte_limit_boolean_for_integer_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["inspected_byte_limit"] = True
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_malformed_created_at_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["created_at"] = "not-a-timestamp"
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_malformed_expires_at_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["expires_at"] = "not-a-timestamp"
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_malformed_base_branch_and_requested_ref_are_rejected() -> None:
    for field in ("base_branch", "requested_ref"):
        payload = serialize_execution_service_request(request())
        payload[field] = "bad ref with spaces"
        with pytest.raises(ValueError):
            reconstruct_execution_service_request(payload)


def test_malformed_base_sha_and_expected_sha_are_rejected() -> None:
    for field in ("base_sha", "expected_sha"):
        payload = serialize_execution_service_request(request())
        payload[field] = "not-a-sha"
        with pytest.raises(ValueError):
            reconstruct_execution_service_request(payload)


def test_allowed_paths_drift_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["allowed_paths"] = ["different/path"]
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_forbidden_paths_drift_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["forbidden_paths"] = ["different/forbidden"]
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_duplicate_path_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["allowed_paths"] = list(payload["allowed_paths"]) * 2
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_path_ordering_is_rejected() -> None:
    payload = serialize_execution_service_request(
        request(allowed_paths=("a/one", "b/two"))
    )
    payload["allowed_paths"] = ["b/two", "a/one"]
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_allowed_forbidden_overlap_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["forbidden_paths"] = list(payload["allowed_paths"])
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_invalidation_condition_ordering_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["invalidation_conditions"] = list(
        reversed(payload["invalidation_conditions"])
    )
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_invalidation_condition_duplicate_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["invalidation_conditions"] = list(
        payload["invalidation_conditions"]
    ) + [payload["invalidation_conditions"][0]]
    with pytest.raises(ValueError):
        reconstruct_execution_service_request(payload)


def test_request_fingerprint_tampering_is_rejected() -> None:
    payload = serialize_execution_service_request(request())
    payload["request_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="request_fingerprint"):
        reconstruct_execution_service_request(payload)


def test_unchanged_execution_service_request_fingerprint_behavior() -> None:
    value = request()
    assert value.request_fingerprint == execution_service_request_fingerprint(value)
    payload = serialize_execution_service_request(value)
    assert payload["request_fingerprint"] == value.request_fingerprint


def test_allowed_paths_type_must_be_list_not_string() -> None:
    payload = serialize_execution_service_request(request())
    payload["allowed_paths"] = payload["allowed_paths"][0]
    with pytest.raises(TypeError):
        reconstruct_execution_service_request(payload)


def test_input_request_object_is_not_mutated() -> None:
    value = request()
    before = copy.deepcopy(serialize_execution_service_request(value))
    serialize_execution_service_request(value)
    reconstruct_execution_service_request(serialize_execution_service_request(value))
    assert serialize_execution_service_request(value) == before


def test_input_payload_is_not_mutated() -> None:
    payload = serialize_execution_service_request(request())
    before = copy.deepcopy(payload)
    reconstruct_execution_service_request(payload)
    assert payload == before


def test_reconstruction_performs_no_reachable_io() -> None:
    import builtins
    import socket
    import subprocess

    payload = serialize_execution_service_request(request())

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("reconstruction must not perform I/O")

    original_open = builtins.open
    original_popen = subprocess.Popen
    original_socket = socket.socket
    builtins.open = _forbidden  # type: ignore[assignment]
    subprocess.Popen = _forbidden  # type: ignore[assignment]
    socket.socket = _forbidden  # type: ignore[assignment]
    try:
        rebuilt = reconstruct_execution_service_request(payload)
        serialize_execution_service_request(rebuilt)
    finally:
        builtins.open = original_open
        subprocess.Popen = original_popen
        socket.socket = original_socket
