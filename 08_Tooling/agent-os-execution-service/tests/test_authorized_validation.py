"""Focused tests for the pure #757 authorized-validation admission boundary."""
from __future__ import annotations

import ast
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
    AuthorizedValidationAdmissionStatus,
    AuthorizedValidationLifecyclePolicy,
    build_authorized_validation_lifecycle_request,
    reconstruct_authorized_validation_lifecycle_request,
    serialize_authorized_validation_lifecycle_request,
    verify_authorized_validation_admission,
)
from scripts.agent_os_candidate_packet.compiler import compile_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.models import CandidatePacket  # noqa: E402
from tests.agent_os_candidate_packet.test_compiler import (  # noqa: E402
    valid_execution_candidate_input,
)

_EVALUATED_AT = "2026-08-11T12:10:00Z"
_AUTHORIZED_AT = "2026-08-11T12:05:00Z"
_EXPIRES_AT = "2026-08-11T13:05:00Z"


def _request(tmp_path, **overrides):
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
        authorization_id="execution-authorization:757-fixture",
        request_fingerprint=execution.request_fingerprint,
        command_plan_id=execution.command_plan_id,
        repository=packet.repository,
        expected_sha=packet.candidate_sha,
        authorized_at=_AUTHORIZED_AT,
        expires_at=_EXPIRES_AT,
        execution_authorized=True,
    )
    values = {
        "candidate_packet": packet,
        "approval_stage": approval,
        "execution_packet_stage": execution,
        "execution_authorization": authorization,
        "authorizer_id": "repository-owner:Blummer92",
        "authorized_candidate_packet_id": packet.packet_id,
        "authorized_invocation_id": packet.invocation_id,
        "authorized_operation": AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
        "lifecycle_policy": AuthorizedValidationLifecyclePolicy(
            expected_changed_paths=packet.expected_changed_paths,
        ),
    }
    values.update(overrides)
    return build_authorized_validation_lifecycle_request(**values)


def test_valid_request_is_deterministic_and_admission_is_non_authorizing(tmp_path) -> None:
    first = _request(tmp_path)
    second = _request(tmp_path)

    assert first.request_id == second.request_id
    result = verify_authorized_validation_admission(first, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.ACCEPTED
    assert result.accepted is True
    assert result.reason_codes == ("accepted",)
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False


def test_request_round_trip_is_exact_and_closed_schema(tmp_path) -> None:
    request = _request(tmp_path)
    payload = serialize_authorized_validation_lifecycle_request(request)
    assert reconstruct_authorized_validation_lifecycle_request(payload) == request

    unknown = dict(payload)
    unknown["surprise"] = "nope"
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_authorized_validation_lifecycle_request(unknown)

    authority = dict(payload)
    authority["execution_authorized"] = True
    with pytest.raises(ValueError, match="must be false"):
        reconstruct_authorized_validation_lifecycle_request(authority)


def test_authorization_replay_against_another_invocation_is_stale(tmp_path) -> None:
    request = _request(tmp_path, authorized_invocation_id="another-invocation")
    result = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.STALE
    assert result.reason_codes == ("authorization.invocation-drift",)


def test_authorization_replay_against_another_candidate_packet_is_stale(tmp_path) -> None:
    request = _request(
        tmp_path,
        authorized_candidate_packet_id="candidate-packet:" + "0" * 64,
    )
    result = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.STALE
    assert result.reason_codes == ("authorization.candidate-packet-drift",)


def test_authorization_replay_against_another_operation_is_blocked(tmp_path) -> None:
    request = _request(tmp_path, authorized_operation="coding")
    result = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.BLOCKED
    assert result.reason_codes == ("authorization.operation-not-permitted",)


def test_false_missing_or_expired_execution_authority_never_admits(tmp_path) -> None:
    request = _request(tmp_path)
    denied = replace(
        request.execution_authorization,
        execution_authorized=False,
    )
    denied_request = replace(request, execution_authorization=denied, request_id="")
    denied_result = verify_authorized_validation_admission(
        denied_request,
        evaluated_at=_EVALUATED_AT,
    )
    assert denied_result.status is AuthorizedValidationAdmissionStatus.BLOCKED
    assert denied_result.reason_codes == ("authorization.not-authorized",)

    expired_result = verify_authorized_validation_admission(
        request,
        evaluated_at=_EXPIRES_AT,
    )
    assert expired_result.status is AuthorizedValidationAdmissionStatus.STALE
    assert expired_result.reason_codes == ("authorization.expired",)


def test_not_yet_active_authorization_is_blocked(tmp_path) -> None:
    request = _request(tmp_path)
    result = verify_authorized_validation_admission(
        request,
        evaluated_at="2026-08-11T12:04:59Z",
    )
    assert result.status is AuthorizedValidationAdmissionStatus.BLOCKED
    assert result.reason_codes == ("authorization.not-yet-active",)


def test_authorization_plan_or_sha_drift_is_stale(tmp_path) -> None:
    request = _request(tmp_path)
    plan_drift = replace(
        request.execution_authorization,
        command_plan_id="command-plan:wrong",
    )
    plan_request = replace(request, execution_authorization=plan_drift, request_id="")
    assert verify_authorized_validation_admission(
        plan_request,
        evaluated_at=_EVALUATED_AT,
    ).reason_codes == ("authorization.plan-drift",)

    sha_drift = replace(
        request.execution_authorization,
        expected_sha="0" * 40,
    )
    sha_request = replace(request, execution_authorization=sha_drift, request_id="")
    assert verify_authorized_validation_admission(
        sha_request,
        evaluated_at=_EVALUATED_AT,
    ).reason_codes == ("authorization.sha-drift",)


def test_policy_rejects_concurrency_retry_type_confusion_and_path_duplicates() -> None:
    with pytest.raises(ValueError, match="exactly 1"):
        AuthorizedValidationLifecyclePolicy(requested_concurrency=2)
    with pytest.raises(TypeError, match="exact integer"):
        AuthorizedValidationLifecyclePolicy(requested_concurrency=True)
    with pytest.raises(ValueError, match="duplicate"):
        AuthorizedValidationLifecyclePolicy(expected_changed_paths=("a.txt", "a.txt"))


def test_tampered_request_identity_is_invalid(tmp_path) -> None:
    request = _request(tmp_path)
    object.__setattr__(request, "request_id", "authorized-validation-request:" + "0" * 64)
    result = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.INVALID
    assert result.reason_codes == ("request.identity-mismatch",)


def test_production_module_has_no_runtime_or_external_capability_imports() -> None:
    source_path = (
        EXEC_SERVICE_SRC
        / "agent_os_execution_service"
        / "authorized_validation.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    forbidden_fragments = (
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "github",
        "concrete_runtime_adapters",
        "execution_composition",
        "single_issue_runtime",
    )
    assert not any(
        fragment in imported
        for imported in imports
        for fragment in forbidden_fragments
    )
