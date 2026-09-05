"""Focused schema-compatibility coverage for Issue #1935."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_os_execution_service.authorization import ExecutionAuthorizationEvidence  # noqa: E402
from agent_os_execution_service.authorized_validation import (  # noqa: E402
    AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    AUTHORIZED_VALIDATION_SCHEMA_VERSION,
    AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
    AuthorizedValidationLifecyclePolicy,
    build_authorized_validation_lifecycle_request,
    pilot_reconstruction_evidence,
    reconstruct_authorized_validation_lifecycle_request,
    serialize_authorized_validation_lifecycle_request,
)
from scripts.agent_os_candidate_packet.compiler import compile_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.models import CandidatePacket  # noqa: E402
from tests.agent_os_candidate_packet.test_compiler import (  # noqa: E402
    valid_execution_candidate_input,
)
from tests.agent_os_remote_validation.test_evidence_bundle import _build  # noqa: E402

_AUTHORIZED_AT = "2026-08-11T12:05:00Z"
_EXPIRES_AT = "2026-08-11T13:05:00Z"


def _request(tmp_path, *, schema_version=AUTHORIZED_VALIDATION_SCHEMA_VERSION, bundle=None, events=()):
    compiler_input = valid_execution_candidate_input(tmp_path)
    packet = compile_candidate_packet(
        compiler_input,
        evaluated_at="2026-08-11T12:05:00Z",
    )
    assert type(packet) is CandidatePacket
    approval = compiler_input.approval_stage_result
    execution = compiler_input.execution_packet_stage_result
    assert approval is not None
    assert execution is not None
    assert execution.request_fingerprint is not None
    assert execution.command_plan_id is not None
    authorization = ExecutionAuthorizationEvidence(
        authorization_id="execution-authorization:1935-fixture",
        request_fingerprint=execution.request_fingerprint,
        command_plan_id=execution.command_plan_id,
        repository=packet.repository,
        expected_sha=packet.candidate_sha,
        authorized_at=_AUTHORIZED_AT,
        expires_at=_EXPIRES_AT,
        execution_authorized=True,
    )
    return build_authorized_validation_lifecycle_request(
        candidate_packet=packet,
        approval_stage=approval,
        execution_packet_stage=execution,
        execution_authorization=authorization,
        authorizer_id="repository-owner:Blummer92",
        authorized_candidate_packet_id=packet.packet_id,
        authorized_invocation_id=packet.invocation_id,
        authorized_operation=AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
        lifecycle_policy=AuthorizedValidationLifecyclePolicy(
            expected_changed_paths=packet.expected_changed_paths,
        ),
        schema_version=schema_version,
        validation_evidence_bundle=bundle,
        invalidation_events=events,
    )


def _vnext(tmp_path, *, bundle=None, events=("approval-record-superseded",)):
    return _request(
        tmp_path,
        schema_version=AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
        bundle=bundle or _build(),
        events=events,
    )


def test_v1_0_round_trip_keeps_original_exact_field_set(tmp_path) -> None:
    request = _request(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)

    assert request.schema_version == AUTHORIZED_VALIDATION_SCHEMA_VERSION
    assert "validation_evidence_bundle" not in payload
    assert "invalidation_events" not in payload
    assert reconstruct_authorized_validation_lifecycle_request(payload) == request


def test_v1_1_round_trip_is_exact_and_deterministic(tmp_path) -> None:
    first = _vnext(tmp_path)
    second = _vnext(tmp_path)

    payload = serialize_authorized_validation_lifecycle_request(first)
    assert reconstruct_authorized_validation_lifecycle_request(payload) == first
    assert first.request_id == second.request_id
    assert first.execution_authorized is False
    assert first.merge_authorized is False
    assert first.automatic_retry is False
    assert first.side_effects_performed is False


def test_v1_1_request_identity_covers_bundle_and_invalidation_events(tmp_path) -> None:
    first = _vnext(tmp_path)
    changed_bundle = _vnext(
        tmp_path,
        bundle=_build(started_at="2026-07-24T13:59:00Z"),
    )
    changed_events = _vnext(tmp_path, events=("proposal-revised",))

    assert first.request_id != changed_bundle.request_id
    assert first.request_id != changed_events.request_id


def test_v1_1_reconstruction_rejects_bundle_tamper_and_malformed_bundle(tmp_path) -> None:
    payload = serialize_authorized_validation_lifecycle_request(_vnext(tmp_path))

    tampered = json.loads(json.dumps(payload))
    tampered["validation_evidence_bundle"]["bundle_id"] = (
        "validation-evidence-bundle:" + "0" * 64
    )
    with pytest.raises(ValueError, match="bundle ID mismatch"):
        reconstruct_authorized_validation_lifecycle_request(tampered)

    malformed = json.loads(json.dumps(payload))
    malformed["validation_evidence_bundle"]["surprise"] = "nope"
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(malformed)


def test_v1_1_invalidation_events_are_bounded_unique_and_canonical(tmp_path) -> None:
    with pytest.raises(ValueError, match="unique"):
        _vnext(tmp_path, events=("proposal-revised", "proposal-revised"))
    with pytest.raises(ValueError, match="canonically sorted"):
        _vnext(tmp_path, events=("z-event", "a-event"))
    with pytest.raises(ValueError, match="non-empty canonical text"):
        _vnext(tmp_path, events=("",))

    payload = serialize_authorized_validation_lifecycle_request(_vnext(tmp_path))
    payload["invalidation_events"] = "not-a-list"
    with pytest.raises(ValueError, match="must be a list"):
        reconstruct_authorized_validation_lifecycle_request(payload)


def test_v1_1_unknown_versions_fields_and_downgrade_attempts_fail_closed(tmp_path) -> None:
    payload = serialize_authorized_validation_lifecycle_request(_vnext(tmp_path))

    unknown_schema = json.loads(json.dumps(payload))
    unknown_schema["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="unsupported"):
        reconstruct_authorized_validation_lifecycle_request(unknown_schema)

    unknown_field = json.loads(json.dumps(payload))
    unknown_field["surprise"] = "nope"
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(unknown_field)

    missing_vnext_field = json.loads(json.dumps(payload))
    del missing_vnext_field["validation_evidence_bundle"]
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(missing_vnext_field)

    downgrade = json.loads(json.dumps(payload))
    downgrade["schema_version"] = AUTHORIZED_VALIDATION_SCHEMA_VERSION
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(downgrade)


def test_pilot_reconstruction_evidence_fails_closed_on_runtime_bundle_mismatch(tmp_path) -> None:
    request = _vnext(tmp_path)
    with pytest.raises(ValueError, match="does not match runtime configuration"):
        pilot_reconstruction_evidence(request)


def test_vnext_module_never_serializes_single_issue_pilot_input() -> None:
    source = (
        EXEC_SERVICE_SRC / "agent_os_execution_service" / "authorized_validation.py"
    ).read_text(encoding="utf-8")
    assert "SingleIssuePilotInput" not in source
