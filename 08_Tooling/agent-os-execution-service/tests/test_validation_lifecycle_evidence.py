"""Focused tests for the unified #761 validation-lifecycle evidence bundle."""
from __future__ import annotations

import ast
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agent_os_execution_service.authorization import ExecutionAuthorizationEvidence  # noqa: E402
from agent_os_execution_service.authorized_validation import (  # noqa: E402
    AUTHORIZED_VALIDATION_PERMITTED_OPERATION,
    AuthorizedValidationAdmissionStatus,
    AuthorizedValidationLifecyclePolicy,
    build_authorized_validation_lifecycle_request,
    verify_authorized_validation_admission,
)
from agent_os_execution_service.execution_composition import (  # noqa: E402
    ExecutionCompositionResult,
    ExecutionCompositionStatus,
)
from agent_os_execution_service.validation_lifecycle_evidence import (  # noqa: E402
    POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE,
    EvidenceAvailability,
    ValidationLifecycleEvidenceBundle,
    ValidationLifecycleEvidenceError,
    ValidationLifecycleTerminalStatus,
    _reconstruct_command_run_observation,
    _reconstruct_validation_result,
    build_validation_lifecycle_evidence_bundle,
    project_validation_lifecycle_result,
    reconstruct_validation_lifecycle_evidence_bundle,
    reconstruct_validation_lifecycle_result,
    serialize_validation_lifecycle_evidence_bundle,
    serialize_validation_lifecycle_result,
)
from scripts.agent_os_candidate_packet.compiler import compile_candidate_packet  # noqa: E402
from scripts.agent_os_candidate_packet.models import (  # noqa: E402
    CandidatePacket,
    CandidatePacketCompilerInput,
    CandidatePacketPhase,
)
from tests.agent_os_candidate_packet.test_compiler import (  # noqa: E402
    _approved_projection,
    _build_execution_packet,
    _common_kwargs,
    _pipeline,
    valid_execution_candidate_input,
)
from workflow_scheduler.execution.frozen_test_validation_adapter import (  # noqa: E402
    CommandRunObservation,
    FrozenTestValidationResult,
)
from workflow_scheduler.execution.quarantine_review import (  # noqa: E402
    build_quarantine_evidence_packet,
)
from workflow_scheduler.execution.single_issue_pilot import (  # noqa: E402
    SINGLE_ISSUE_PILOT_SCHEMA_NAME,
    SingleIssuePilotResult,
    _result_payload,
    _semantic_digest,
)
from workflow_scheduler.execution.workspace_state_evidence import (  # noqa: E402
    ChangedPathObservation,
    WorkspaceLifecycleEvidence,
    WorkspaceStateObservation,
    WorktreeListRecord,
)

_EVALUATED_AT = "2026-08-11T12:10:00Z"
_AUTHORIZED_AT = "2026-08-11T12:05:00Z"
_EXPIRES_AT = "2026-08-11T13:05:00Z"


def _zero_expected_paths_compiler_input(tmp_path, *, candidate_sha="d" * 40):
    """A candidate whose validation-only lifecycle expects no changed paths.

    #760's ``satisfies_expected_changed_paths`` (reused, not reimplemented, by
    #761's success gate) requires both the expected and observed changed-path
    sets to be empty for validation-only success. ``valid_execution_candidate_input``
    always ties ``expected_changed_paths`` to a non-empty candidate diff, so a
    reachable ``succeeded`` fixture needs the same pipeline with that one field
    overridden.
    """
    readiness, planning, proposal = _pipeline()
    approved = _approved_projection(proposal)
    execution_packet = _build_execution_packet(
        approved, proposal, tmp_path, candidate_sha=candidate_sha, expected_changed_paths=()
    )
    assert execution_packet.packet_complete is True
    kwargs = _common_kwargs(
        readiness,
        planning,
        proposal,
        candidate_sha=candidate_sha,
        source_sha=candidate_sha,
        tested_sha=approved.projection.tested_repository_sha,
        evaluator_sha=approved.projection.evaluator_commit_sha,
    )
    kwargs["requested_phase"] = CandidatePacketPhase.EXECUTION_CANDIDATE
    kwargs["approval_stage_result"] = approved
    kwargs["execution_packet_stage_result"] = execution_packet
    return CandidatePacketCompilerInput(**kwargs)


def _admission_request(tmp_path, *, zero_expected_paths=False, **overrides):
    compiler_input = (
        _zero_expected_paths_compiler_input(tmp_path)
        if zero_expected_paths
        else valid_execution_candidate_input(tmp_path)
    )
    packet = compile_candidate_packet(compiler_input, evaluated_at="2026-08-11T12:05:00Z")
    assert type(packet) is CandidatePacket
    approval = compiler_input.approval_stage_result
    execution = compiler_input.execution_packet_stage_result
    assert execution is not None and execution.request_fingerprint is not None

    authorization = ExecutionAuthorizationEvidence(
        authorization_id="execution-authorization:761-fixture",
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


def _accepted_admission(tmp_path, *, zero_expected_paths=False, **overrides):
    request = _admission_request(tmp_path, zero_expected_paths=zero_expected_paths, **overrides)
    result = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert result.status is AuthorizedValidationAdmissionStatus.ACCEPTED, result.reason_codes
    return request, result


def _command_outcome(test_id, *, outcome="succeeded", started=True, return_code=0, changed_paths=()):
    return CommandRunObservation(
        test_id=test_id,
        outcome=outcome,
        started=started,
        termination_confirmed=True,
        possible_partial_effects=False,
        return_code=return_code,
        stdout_text="ok",
        stderr_text="",
        changed_paths=changed_paths,
        reason="",
    )


def _validation_result(request, *, passed=True, attempted=True, outcome="succeeded"):
    runtime = request.execution_packet_stage.runtime_configuration
    test_ids = tuple(item.test_id for item in runtime.required_test_commands)
    return FrozenTestValidationResult(
        started=attempted,
        termination_confirmed=True,
        possible_partial_effects=False,
        attempted=attempted,
        passed=passed,
        cancellation_requested=False,
        total_timed_out=False,
        completed_tests=test_ids if attempted else (),
        changed_paths=(),
        command_outcomes=tuple(_command_outcome(t, outcome=outcome) for t in test_ids),
        reason="",
    )


def _execution_composition(
    request, *, validation_result, status, execution_authorized=True, pilot_reason_codes=()
):
    execution = request.execution_packet_stage
    base_reason = (
        "runtime-status:completed"
        if status is ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
        else "runtime-status:failed"
    )
    reason_codes = tuple(sorted(set((base_reason,) + tuple(pilot_reason_codes))))
    return ExecutionCompositionResult(
        request_fingerprint=execution.request_fingerprint,
        command_plan_id=execution.command_plan_id,
        repository=request.execution_authorization.repository,
        expected_sha=request.execution_authorization.expected_sha,
        profile="focused",
        status=status,
        validation_result=validation_result,
        aggregate_pending=True,
        execution_authorized=execution_authorized,
        side_effects_performed=True,
        reason_codes=reason_codes,
        evidence_id="execution-composition:" + "0" * 64,
    )


def _pilot_result(request, *, status="completed", **overrides):
    runtime = request.execution_packet_stage.runtime_configuration
    test_ids = tuple(item.test_id for item in runtime.required_test_commands)
    base = dict(
        schema_name="agent-os-wsc5-single-issue-pilot",
        schema_version="1.0",
        execution_mode="validation-only",
        result_id="single-issue-pilot:" + "1" * 64,
        phase="finalization",
        primary_status=status,
        status=status,
        repository=request.execution_authorization.repository,
        base_branch=runtime.base_branch,
        branch=runtime.branch,
        issue_numbers=(runtime.issue_number,),
        invocation_id=request.authorized_invocation_id,
        base_sha=runtime.base_sha,
        source_head_sha=runtime.source_head_sha,
        tested_sha=request.execution_authorization.expected_sha,
        # placeholder; replaced below with the correct computed identity

        projection_id=runtime.projection_id,
        proposal_id=None,
        approval_id=runtime.approval_id,
        approval_revision=None,
        issueplan_evidence_id=None,
        plan_id=None,
        bundle_id=runtime.validation_bundle_id,
        advisory_result_id=runtime.advisory_result_id,
        advisory_render_id=runtime.advisory_render_id,
        lease_identity="lease:761-fixture",
        lease_holder_identity="holder:761-fixture",
        lease_generation=1,
        lease_acquire_attempts=1,
        lease_acquired=True,
        lease_release_attempts=1,
        lease_released=True,
        workspace_identity="workspace:761-fixture",
        workspace_create_attempts=1,
        workspace_created=True,
        workspace_inspected=True,
        workspace_safe=True,
        workspace_cleanup_attempts=1,
        workspace_filesystem_cleaned=True,
        workspace_metadata_cleaned=True,
        executor_dispatch_attempts=0,
        executor_called=False,
        executor_started=False,
        cancellation_requested=False,
        termination_confirmed=False,
        possible_partial_effects=False,
        validation_attempts=1,
        validation_attempted=True,
        validation_passed=True,
        changed_paths=(),
        required_tests=test_ids,
        completed_tests=test_ids,
        reason_codes=(),
        details=(),
        primary_error=None,
        cleanup_errors=(),
        release_errors=(),
    )
    base.update(overrides)
    provisional = SingleIssuePilotResult(**base)
    payload = _result_payload(provisional)
    expected_id = "single-issue-pilot:" + _semantic_digest(SINGLE_ISSUE_PILOT_SCHEMA_NAME, payload)
    return replace(provisional, result_id=expected_id)


def _workspace_observation(request, *, kind, dirty_categories=None):
    runtime = request.execution_packet_stage.runtime_configuration
    categories = {name: () for name in (
        "staged", "unstaged", "untracked", "ignored", "renamed", "copied", "deleted", "conflict", "submodule"
    )}
    if dirty_categories:
        categories.update(dirty_categories)
    return WorkspaceStateObservation(
        observation_kind=kind,
        repository_owner=runtime.repository_identity.owner,
        repository_name=runtime.repository_identity.repository,
        workspace_path="/tmp/761-fixture-workspace",
        branch=runtime.branch,
        expected_sha=request.execution_authorization.expected_sha,
        observed_sha=request.execution_authorization.expected_sha,
        lock_identity="",
        worktree_record=WorktreeListRecord(
            path="/tmp/761-fixture-workspace",
            head=request.execution_authorization.expected_sha,
            branch=f"refs/heads/{runtime.branch}",
            detached=False,
            bare=False,
            locked=False,
            lock_reason="",
            prunable=False,
            prunable_reason="",
        ),
        observed_at="monotonic:1",
        complete=True,
        reason_codes=(),
        **categories,
    )


def _workspace_lifecycle_evidence(request, *, dirty_final=False):
    dirty = None
    if dirty_final:
        dirty = {"unstaged": (ChangedPathObservation(category="unstaged", path="a.txt", worktree_status="M"),)}
    return WorkspaceLifecycleEvidence(
        initial=_workspace_observation(request, kind="initial"),
        final=_workspace_observation(request, kind="final", dirty_categories=dirty),
        validation_only=True,
    )


def _clean_bundle(tmp_path, evaluated_at=_EVALUATED_AT):
    request, admission = _accepted_admission(tmp_path, zero_expected_paths=True)
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request, validation_result=validation_result, status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request)
    workspace = _workspace_lifecycle_evidence(request)
    return build_validation_lifecycle_evidence_bundle(
        evaluated_at=evaluated_at,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=workspace,
    )


# ---------------------------------------------------------------------------
# One fixture per terminal status
# ---------------------------------------------------------------------------


def test_succeeded_requires_the_complete_conjunction(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.SUCCEEDED
    assert result.execution_authorized is True
    assert result.side_effects_performed is True


def test_validation_failed_with_otherwise_complete_containment(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=False, outcome="failed")
    composition = _execution_composition(
        request,
        validation_result=validation_result,
        status=ExecutionCompositionStatus.FOCUSED_FAIL,
        pilot_reason_codes=("validation.failed",),
    )
    pilot = _pilot_result(request, status="failed", validation_passed=False, reason_codes=("validation.failed",))
    workspace = _workspace_lifecycle_evidence(request)
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=workspace,
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.VALIDATION_FAILED


def test_blocked_admission_has_zero_side_effects(tmp_path) -> None:
    request = _admission_request(tmp_path, authorized_operation="coding")
    admission = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert admission.status is AuthorizedValidationAdmissionStatus.BLOCKED
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT, admission_request=request, admission_result=admission
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.BLOCKED
    assert result.side_effects_performed is False
    assert result.execution_authorized is False


def test_stale_admission_has_zero_side_effects(tmp_path) -> None:
    request = _admission_request(tmp_path, authorized_invocation_id="another-invocation")
    admission = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert admission.status is AuthorizedValidationAdmissionStatus.STALE
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT, admission_request=request, admission_result=admission
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.STALE
    assert result.side_effects_performed is False


def test_blocked_admission_with_contradictory_runtime_evidence_fails_closed(tmp_path) -> None:
    request = _admission_request(tmp_path, authorized_operation="coding")
    admission = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert admission.status is AuthorizedValidationAdmissionStatus.BLOCKED
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request, validation_result=validation_result, status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    with pytest.raises(ValidationLifecycleEvidenceError, match="contradictory"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            execution_composition=composition,
        )


def test_stale_admission_with_contradictory_runtime_evidence_fails_closed(tmp_path) -> None:
    request = _admission_request(tmp_path, authorized_invocation_id="another-invocation")
    admission = verify_authorized_validation_admission(request, evaluated_at=_EVALUATED_AT)
    assert admission.status is AuthorizedValidationAdmissionStatus.STALE
    pilot = _pilot_result(request)
    with pytest.raises(ValidationLifecycleEvidenceError, match="contradictory"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            pilot_result=pilot,
        )


def test_timed_out_distinct_from_cancelled(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=False, attempted=True, outcome="timed-out")
    composition = _execution_composition(
        request,
        validation_result=validation_result,
        status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
        pilot_reason_codes=("cancellation.unconfirmed",),
    )
    timed_out_pilot = _pilot_result(
        request, status="timed-out", validation_passed=False, reason_codes=("cancellation.unconfirmed",)
    )
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=timed_out_pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.TERMINATION_UNCERTAIN

    request2, admission2 = _accepted_admission(tmp_path)
    cancelled_pilot = _pilot_result(
        request2,
        status="cancelled",
        validation_passed=False,
        validation_attempted=False,
        cancellation_requested=True,
    )
    composition2 = _execution_composition(
        request2,
        validation_result=_validation_result(request2, passed=False, attempted=False),
        status=ExecutionCompositionStatus.CANCELLED,
    )
    bundle2 = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request2,
        admission_result=admission2,
        execution_composition=composition2,
        pilot_result=cancelled_pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request2),
    )
    result2 = project_validation_lifecycle_result(bundle2)
    assert result2.status is ValidationLifecycleTerminalStatus.CANCELLED
    assert result2.status is not result.status


def test_quarantined_dominates_validation_pass(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request,
        validation_result=validation_result,
        status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
        pilot_reason_codes=("workspace.filesystem-cleanup-failed",),
    )
    pilot = _pilot_result(
        request,
        status="quarantined",
        validation_passed=True,
        reason_codes=("workspace.filesystem-cleanup-failed",),
        workspace_filesystem_cleaned=False,
    )
    packet = build_quarantine_evidence_packet(pilot)
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
        quarantine_packet=packet,
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.QUARANTINED


def test_termination_uncertain_dominates_validation_pass(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request,
        validation_result=validation_result,
        status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE,
        pilot_reason_codes=("executor.termination-unconfirmed",),
    )
    pilot = _pilot_result(
        request,
        status="failed",
        validation_passed=True,
        reason_codes=("executor.termination-unconfirmed",),
    )
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.TERMINATION_UNCERTAIN


def test_cleanup_failure_dominates_validation_pass(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request, validation_result=validation_result, status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    )
    pilot = _pilot_result(
        request,
        status="failed",
        validation_passed=True,
        workspace_filesystem_cleaned=False,
        cleanup_errors=("filesystem removal failed",),
    )
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.CLEANUP_FAILED


def test_release_failure_dominates_validation_pass(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request, validation_result=validation_result, status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    )
    pilot = _pilot_result(
        request,
        status="failed",
        validation_passed=True,
        lease_released=False,
        release_errors=("lease release failed",),
    )
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.RELEASE_FAILED


def test_evidence_incomplete_withholds_success(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE
    assert any(item.startswith("evidence.missing") for item in result.reason_codes)


# ---------------------------------------------------------------------------
# Precedence table coverage
# ---------------------------------------------------------------------------


def test_precedence_table_matches_the_issue_defined_order() -> None:
    assert POST_ADMISSION_TERMINAL_STATUS_PRECEDENCE == (
        ValidationLifecycleTerminalStatus.QUARANTINED,
        ValidationLifecycleTerminalStatus.TERMINATION_UNCERTAIN,
        ValidationLifecycleTerminalStatus.CLEANUP_FAILED,
        ValidationLifecycleTerminalStatus.RELEASE_FAILED,
        ValidationLifecycleTerminalStatus.TIMED_OUT,
        ValidationLifecycleTerminalStatus.CANCELLED,
        ValidationLifecycleTerminalStatus.EVIDENCE_INCOMPLETE,
        ValidationLifecycleTerminalStatus.VALIDATION_FAILED,
        ValidationLifecycleTerminalStatus.SUCCEEDED,
    )


def test_cleanup_failure_dominates_release_failure(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.INFRASTRUCTURE_FAILURE
    )
    pilot = _pilot_result(
        request,
        status="failed",
        validation_passed=True,
        workspace_filesystem_cleaned=False,
        cleanup_errors=("cleanup broke",),
        lease_released=False,
        release_errors=("release broke",),
    )
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.CLEANUP_FAILED


# ---------------------------------------------------------------------------
# Authorization vs runtime truth
# ---------------------------------------------------------------------------


def test_authorization_false_plus_runtime_success_cannot_succeed(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=True)
    composition = _execution_composition(
        request,
        validation_result=validation_result,
        status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING,
        execution_authorized=False,
    )
    pilot = _pilot_result(request)
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is not ValidationLifecycleTerminalStatus.SUCCEEDED
    assert result.execution_authorized is False


def test_side_effects_performed_is_independent_of_status(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    validation_result = _validation_result(request, passed=False, outcome="failed")
    composition = _execution_composition(
        request,
        validation_result=validation_result,
        status=ExecutionCompositionStatus.FOCUSED_FAIL,
        pilot_reason_codes=("validation.failed",),
    )
    pilot = _pilot_result(request, status="failed", validation_passed=False, reason_codes=("validation.failed",))
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is ValidationLifecycleTerminalStatus.VALIDATION_FAILED
    assert result.side_effects_performed is True


# ---------------------------------------------------------------------------
# Identity substitution / tamper
# ---------------------------------------------------------------------------


def test_repository_identity_substitution_on_pilot_result_rejected(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request, repository="someone-else/other-repo")
    with pytest.raises(ValidationLifecycleEvidenceError, match="repository identity mismatch"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            execution_composition=composition,
            pilot_result=pilot,
            workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
        )


def test_sha_role_substitution_on_pilot_result_rejected(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request, tested_sha="f" * 40)
    with pytest.raises(ValidationLifecycleEvidenceError, match="tested_sha identity mismatch"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            execution_composition=composition,
            pilot_result=pilot,
            workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
        )


def test_invocation_substitution_on_pilot_result_rejected(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request, invocation_id="some-other-invocation")
    with pytest.raises(ValidationLifecycleEvidenceError, match="invocation_id identity mismatch"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            execution_composition=composition,
            pilot_result=pilot,
            workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
        )


def test_execution_composition_request_fingerprint_substitution_rejected(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    tampered = replace(composition, request_fingerprint="0" * 64)
    with pytest.raises(ValidationLifecycleEvidenceError, match="request_fingerprint identity mismatch"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            execution_composition=tampered,
        )


def test_workspace_evidence_changed_paths_replay_rejected(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request, changed_paths=("a.txt",))
    with pytest.raises(ValidationLifecycleEvidenceError, match="does not match #760"):
        build_validation_lifecycle_evidence_bundle(
            evaluated_at=_EVALUATED_AT,
            admission_request=request,
            admission_result=admission,
            execution_composition=composition,
            pilot_result=pilot,
            workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
        )


def test_final_dirty_changed_paths_prevent_success(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request, changed_paths=("a.txt",))
    workspace = _workspace_lifecycle_evidence(request, dirty_final=True)
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=workspace,
    )
    result = project_validation_lifecycle_result(bundle)
    assert result.status is not ValidationLifecycleTerminalStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Serialization / reconstruction / identity
# ---------------------------------------------------------------------------

def test_command_observation_missing_termination_evidence_fails_closed():
    payload = {
        "test_id": "test-command",
        "outcome": "succeeded",
        "started": True,
        "possible_partial_effects": False,
        "return_code": 0,
        "stdout_text": "ok",
        "stderr_text": "",
        "changed_paths": [],
        "reason": "",
    }

    with pytest.raises(ValidationLifecycleEvidenceError):
        _reconstruct_command_run_observation(payload)


def test_validation_result_missing_termination_evidence_fails_closed():
    payload = {
        "attempted": True,
        "passed": True,
        "cancellation_requested": False,
        "total_timed_out": False,
        "termination_confirmed": True,
        "possible_partial_effects": False,
        "completed_tests": [],
        "changed_paths": [],
        "command_outcomes": [],
        "reason": "",
    }

    with pytest.raises(ValidationLifecycleEvidenceError):
        _reconstruct_validation_result(payload)

def test_command_observation_missing_termination_evidence_fails_closed():
    payload = {
        "test_id": "test-command",
        "outcome": "succeeded",
        "started": True,
        "possible_partial_effects": False,
        "return_code": 0,
        "stdout_text": "ok",
        "stderr_text": "",
        "changed_paths": [],
        "reason": "",
    }

    with pytest.raises(ValidationLifecycleEvidenceError):
        _reconstruct_command_run_observation(payload)


def test_validation_result_missing_termination_evidence_fails_closed():
    payload = {
        "attempted": True,
        "passed": True,
        "cancellation_requested": False,
        "total_timed_out": False,
        "termination_confirmed": True,
        "possible_partial_effects": False,
        "completed_tests": [],
        "changed_paths": [],
        "command_outcomes": [],
        "reason": "",
    }

    with pytest.raises(ValidationLifecycleEvidenceError):
        _reconstruct_validation_result(payload)

def test_bundle_serializes_and_reconstructs_exactly(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    payload = serialize_validation_lifecycle_evidence_bundle(bundle)
    rebuilt = reconstruct_validation_lifecycle_evidence_bundle(payload)
    assert rebuilt == bundle
    assert serialize_validation_lifecycle_evidence_bundle(rebuilt) == payload


def test_bundle_reconstruction_rejects_unknown_fields(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    payload = serialize_validation_lifecycle_evidence_bundle(bundle)
    unknown = dict(payload)
    unknown["surprise"] = "nope"
    with pytest.raises(ValidationLifecycleEvidenceError, match="unknown or missing"):
        reconstruct_validation_lifecycle_evidence_bundle(unknown)

    missing = dict(payload)
    del missing["evidence_availability"]
    with pytest.raises(ValidationLifecycleEvidenceError, match="unknown or missing"):
        reconstruct_validation_lifecycle_evidence_bundle(missing)


def test_bundle_reconstruction_rejects_tampered_bundle_id(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    payload = serialize_validation_lifecycle_evidence_bundle(bundle)
    tampered = dict(payload)
    tampered["bundle_id"] = "bundle:" + "f" * 64
    with pytest.raises(ValidationLifecycleEvidenceError, match="bundle_id mismatch"):
        reconstruct_validation_lifecycle_evidence_bundle(tampered)


def test_deterministic_bundle_and_result_id(tmp_path) -> None:
    first = _clean_bundle(tmp_path)
    second = _clean_bundle(tmp_path)
    assert first.bundle_id == second.bundle_id

    result1 = project_validation_lifecycle_result(first)
    result2 = project_validation_lifecycle_result(second)
    assert result1.result_id == result2.result_id


def test_result_serializes_and_reconstructs_exactly(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    result = project_validation_lifecycle_result(bundle)
    payload = serialize_validation_lifecycle_result(result)
    rebuilt = reconstruct_validation_lifecycle_result(payload)
    assert rebuilt == result

    tampered = dict(payload)
    tampered["status"] = ValidationLifecycleTerminalStatus.CANCELLED.value
    with pytest.raises(ValidationLifecycleEvidenceError, match="result_id mismatch"):
        reconstruct_validation_lifecycle_result(tampered)


def test_bundle_evidence_availability_derived_not_caller_supplied(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    names = {item.field_name: item.availability for item in bundle.evidence_availability}
    assert names["execution_composition"] is EvidenceAvailability.PRESENT
    assert names["pilot_result"] is EvidenceAvailability.PRESENT
    assert names["workspace_lifecycle_evidence"] is EvidenceAvailability.PRESENT
    assert names["quarantine_packet"] is EvidenceAvailability.NOT_APPLICABLE


def test_historical_evidence_is_immutable(tmp_path) -> None:
    bundle = _clean_bundle(tmp_path)
    with pytest.raises((AttributeError, TypeError)):
        bundle.pilot_result = None  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        bundle.evidence_availability = ()  # type: ignore[misc]


def test_nested_mutable_input_does_not_mutate_bundle(tmp_path) -> None:
    request, admission = _accepted_admission(tmp_path)
    composition = _execution_composition(
        request, validation_result=_validation_result(request, passed=True), status=ExecutionCompositionStatus.FOCUSED_PASS_AGGREGATE_PENDING
    )
    pilot = _pilot_result(request)
    bundle = build_validation_lifecycle_evidence_bundle(
        evaluated_at=_EVALUATED_AT,
        admission_request=request,
        admission_result=admission,
        execution_composition=composition,
        pilot_result=pilot,
        workspace_lifecycle_evidence=_workspace_lifecycle_evidence(request),
    )
    payload = serialize_validation_lifecycle_evidence_bundle(bundle)
    payload["pilot_result"]["reason_codes"].append("mutated-after-serialize")
    assert bundle.pilot_result.reason_codes == ()


# ---------------------------------------------------------------------------
# Architecture: no execution/I/O authority reachable from this module
# ---------------------------------------------------------------------------


def test_production_module_has_no_execution_or_io_authority_imports() -> None:
    source_path = EXEC_SERVICE_SRC / "agent_os_execution_service" / "validation_lifecycle_evidence.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden_substrings = (
        "subprocess",
        "socket",
        "urllib",
        "http.client",
        "requests",
        "posix_process_adapter",
        "clone3_cgroup_launcher",
        "host_local_lease_adapter",
        "retry_manager",
        "single_issue_runtime",
        "request_dispatch",
        "github",
        "notion",
    )
    for module_name in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in module_name, f"forbidden import reachable: {module_name}"


def test_module_source_never_calls_subprocess_or_open_for_write() -> None:
    source_path = EXEC_SERVICE_SRC / "agent_os_execution_service" / "validation_lifecycle_evidence.py"
    source = source_path.read_text(encoding="utf-8")
    for forbidden in ("subprocess.", "os.system", "os.fork", "os.exec", "socket.socket"):
        assert forbidden not in source
