"""Focused compatibility and vNext tests for Issue #1935."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
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
    AuthorizedValidationAdmissionStatus,
    AuthorizedValidationLifecyclePolicy,
    build_authorized_validation_lifecycle_request,
    pilot_reconstruction_evidence,
    reconstruct_authorized_validation_lifecycle_request,
    serialize_authorized_validation_lifecycle_request,
    verify_authorized_validation_admission,
)
from scripts.agent_os_candidate_packet.compiler import compile_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.models import (  # noqa: E402
    CandidatePacket,
    CandidatePacketCompilerInput,
    CandidatePacketPhase,
)
from scripts.agent_os_remote_validation.evidence_bundle import (  # noqa: E402
    ValidationEvidenceBundle,
    build_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
)
from scripts.agent_os_remote_validation.selector import validation_plan_id  # noqa: E402
from tests.agent_os_candidate_packet.test_compiler import (  # noqa: E402
    _approved_projection,
    _build_execution_packet,
    _common_kwargs,
    _pipeline,
)

_EVALUATED_AT = "2026-08-11T12:10:00Z"
_AUTHORIZED_AT = "2026-08-11T12:05:00Z"
_EXPIRES_AT = "2026-08-11T13:05:00Z"
_CANDIDATE_SHA = "d" * 40


def _bundle_for_execution(approved, proposal, execution, *, runner_id="vnext-fixture"):
    plan = execution.validation_stage.validation_plan
    assert plan is not None
    repository_state = proposal.repository_state_evidence
    return build_validation_evidence_bundle(
        object(),
        plan,
        (),
        expected_repository=repository_state.repository_identity,
        expected_pull_request=plan.pull_request,
        expected_base_branch=approved.projection.base_branch,
        expected_base_sha=plan.base_sha,
        expected_source_head_sha=plan.head_sha,
        expected_tested_sha=approved.projection.tested_repository_sha,
        expected_repository_evidence_type=repository_state.evidence_type,
        expected_projection_id=approved.projection.projection_id,
        expected_proposal_id=approved.projection.proposal_id,
        expected_approval_id=approved.projection.approval_id,
        expected_repository_state_evidence_id=repository_state.evidence_id,
        expected_implementation_contract_fingerprint=(
            approved.projection.implementation_contract_fingerprint
        ),
        expected_selector_version=plan.selector_version,
        expected_profile=plan.profile,
        expected_command_set_digest=plan.command_set_digest,
        expected_plan_id=validation_plan_id(plan),
        runner_id=runner_id,
        invocation_id="candidate-packet-755",
        started_at="2026-08-11T12:00:00Z",
        completed_at="2026-08-11T12:04:00Z",
    )


def _vnext_request(tmp_path, *, invalidation_events=("candidate.changed",)):
    readiness, planning, proposal = _pipeline()
    approved = _approved_projection(proposal)
    preliminary = _build_execution_packet(
        approved,
        proposal,
        tmp_path,
        candidate_sha=_CANDIDATE_SHA,
    )
    bundle = _bundle_for_execution(approved, proposal, preliminary)
    execution = _build_execution_packet(
        approved,
        proposal,
        tmp_path,
        candidate_sha=_CANDIDATE_SHA,
        validation_bundle_id=bundle.bundle_id,
    )
    kwargs = _common_kwargs(
        readiness,
        planning,
        proposal,
        candidate_sha=_CANDIDATE_SHA,
        source_sha=_CANDIDATE_SHA,
        tested_sha=approved.projection.tested_repository_sha,
        evaluator_sha=approved.projection.evaluator_commit_sha,
    )
    kwargs["requested_phase"] = CandidatePacketPhase.EXECUTION_CANDIDATE
    kwargs["approval_stage_result"] = approved
    kwargs["execution_packet_stage_result"] = execution
    compiler_input = CandidatePacketCompilerInput(**kwargs)
    packet = compile_candidate_packet(
        compiler_input,
        evaluated_at="2026-08-11T12:05:00Z",
    )
    assert type(packet) is CandidatePacket
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
    request = build_authorized_validation_lifecycle_request(
        candidate_packet=packet,
        approval_stage=approved,
        execution_packet_stage=execution,
        execution_authorization=authorization,
        authorizer_id="repository-owner:Blummer92",
        authorized_candidate_packet_id=packet.packet_id,
        authorized_invocation_id=packet.invocation_id,
        authorized_operation=AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
        lifecycle_policy=AuthorizedValidationLifecyclePolicy(
            expected_changed_paths=packet.expected_changed_paths,
        ),
        schema_version=AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION,
        validation_evidence_bundle=bundle,
        invalidation_events=invalidation_events,
    )
    return request, approved, proposal, preliminary


def test_v1_round_trip_and_field_set_remain_legacy_compatible(tmp_path) -> None:
    request, _, _, _ = _vnext_request(tmp_path)
    legacy = replace(
        request,
        schema_version=AUTHORIZED_VALIDATION_SCHEMA_VERSION,
        validation_evidence_bundle=None,
        invalidation_events=(),
        request_id="",
    )
    payload = serialize_authorized_validation_lifecycle_request(legacy)
    assert "validation_evidence_bundle" not in payload
    assert "invalidation_events" not in payload
    assert reconstruct_authorized_validation_lifecycle_request(payload) == legacy
    assert verify_authorized_validation_admission(
        legacy, evaluated_at=_EVALUATED_AT
    ).status is AuthorizedValidationAdmissionStatus.ACCEPTED


def test_vnext_round_trip_identity_and_inert_evidence_are_deterministic(tmp_path) -> None:
    first, _, _, _ = _vnext_request(tmp_path)
    second, _, _, _ = _vnext_request(tmp_path)
    assert first.request_id == second.request_id
    payload = serialize_authorized_validation_lifecycle_request(first)
    rebuilt = reconstruct_authorized_validation_lifecycle_request(payload)
    assert rebuilt == first
    bundle, events = pilot_reconstruction_evidence(rebuilt)
    assert bundle == first.validation_evidence_bundle
    assert events == ("candidate.changed",)
    result = verify_authorized_validation_admission(rebuilt, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.ACCEPTED
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False


def test_vnext_bundle_and_invalidation_drift_change_request_identity(tmp_path) -> None:
    request, approved, proposal, preliminary = _vnext_request(tmp_path)
    changed_bundle = _bundle_for_execution(
        approved,
        proposal,
        preliminary,
        runner_id="vnext-fixture-drift",
    )
    bundle_drift = replace(
        request,
        validation_evidence_bundle=changed_bundle,
        request_id="",
    )
    event_drift = replace(
        request,
        invalidation_events=("candidate.changed", "source.revision-changed"),
        request_id="",
    )
    assert bundle_drift.request_id != request.request_id
    assert event_drift.request_id != request.request_id
    assert verify_authorized_validation_admission(
        bundle_drift, evaluated_at=_EVALUATED_AT
    ).status is AuthorizedValidationAdmissionStatus.INVALID


def test_vnext_tampered_or_malformed_bundle_fails_closed(tmp_path) -> None:
    request, _, _, _ = _vnext_request(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)

    tampered = json.loads(json.dumps(payload))
    tampered["validation_evidence_bundle"]["bundle_id"] = (
        "validation-evidence-bundle:" + "0" * 64
    )
    with pytest.raises(ValueError, match="bundle ID mismatch"):
        reconstruct_authorized_validation_lifecycle_request(tampered)

    malformed = json.loads(json.dumps(payload))
    malformed["validation_evidence_bundle"]["surprise"] = True
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(malformed)

    authority = json.loads(json.dumps(payload))
    authority["validation_evidence_bundle"]["execution_authorized"] = True
    with pytest.raises(ValueError, match="must remain false"):
        reconstruct_authorized_validation_lifecycle_request(authority)


def test_vnext_invalidation_events_are_bounded_unique_and_canonical(tmp_path) -> None:
    request, _, _, _ = _vnext_request(tmp_path)
    with pytest.raises(ValueError, match="unique"):
        replace(
            request,
            invalidation_events=("candidate.changed", "candidate.changed"),
            request_id="",
        )
    with pytest.raises(ValueError, match="canonically sorted"):
        replace(
            request,
            invalidation_events=("source.revision-changed", "candidate.changed"),
            request_id="",
        )
    with pytest.raises(ValueError, match="non-empty canonical text"):
        replace(request, invalidation_events=("",), request_id="")


def test_version_and_field_drift_cannot_downgrade_vnext(tmp_path) -> None:
    request, _, _, _ = _vnext_request(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)

    future = dict(payload)
    future["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="unsupported"):
        reconstruct_authorized_validation_lifecycle_request(future)

    unknown = dict(payload)
    unknown["surprise"] = "nope"
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(unknown)

    downgrade = dict(payload)
    downgrade["schema_version"] = AUTHORIZED_VALIDATION_SCHEMA_VERSION
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(downgrade)

    missing = dict(payload)
    missing.pop("validation_evidence_bundle")
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(missing)


def test_serialized_vnext_never_contains_pilot_input_or_new_authority(tmp_path) -> None:
    request, _, _, _ = _vnext_request(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)
    rendered = json.dumps(payload, sort_keys=True)
    assert "SingleIssuePilotInput" not in rendered
    assert "pilot_input" not in payload
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["automatic_retry"] is False
    assert payload["side_effects_performed"] is False
    assert isinstance(request.validation_evidence_bundle, ValidationEvidenceBundle)
    assert serialize_validation_evidence_bundle(request.validation_evidence_bundle)[
        "bundle_id"
    ] == request.validation_evidence_bundle.bundle_id
