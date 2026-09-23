"""Focused AOS-AUTO1F candidate-packet compiler tests (#755)."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from scripts.agent_os_candidate_packet.approval_stage import (  # noqa: E402
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.compiler import _first_duplicate, compile_candidate_packet
from scripts.agent_os_candidate_packet.execution_packet_stage import prepare_execution_packet
from scripts.agent_os_candidate_packet.models import (
    COMPILER_SCHEMA_NAME,
    COMPILER_SCHEMA_VERSION,
    CandidatePacket,
    CandidatePacketCompilationFailure,
    CandidatePacketCompilerInput,
    CandidatePacketPhase,
)
from scripts.agent_os_candidate_packet.validation_stage import CandidateRuntimeInputs
from scripts.agent_os_issue_acceptance import ApprovalState
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    ApprovedExecutionProjectionResult,
)
from tests.agent_os_candidate_packet.test_approval_stage import _context, _decision
from tests.agent_os_candidate_packet.test_natural_pipeline import _run
from tests.agent_os_candidate_packet.test_readiness_stage import (
    _FakeIssueReader,
    _FakeRepositoryReader,
    _request,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
)

_ANCHOR_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_EVALUATOR_SHA = "a" * 40
_BRANCH = "agent/750-candidate-packet"
_COMMAND = "python -m pytest 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
_ALLOWED_PATH = "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"


def _pipeline():
    return _run()


def _common_kwargs(readiness, planning, proposal, **overrides):
    issueplan = readiness.issueplan_current_state_evidence
    snapshot = readiness.snapshot
    values = dict(
        compiler_schema_name=COMPILER_SCHEMA_NAME,
        compiler_schema_version=COMPILER_SCHEMA_VERSION,
        repository="blummer92/agent-os",
        issue_number=750,
        invocation_id="candidate-packet-755",
        candidate_ref=_BRANCH,
        base_branch="main",
        base_sha=_ANCHOR_SHA,
        candidate_sha=_ANCHOR_SHA,
        source_sha=_ANCHOR_SHA,
        tested_sha=_ANCHOR_SHA,
        evaluator_sha=_EVALUATOR_SHA,
        external_build_sha=None,
        expected_source_revision=snapshot.source_revision,
        expected_source_snapshot_fingerprint=issueplan.source_snapshot_fingerprint,
        expected_scanner_result_fingerprint=issueplan.scanner_result_fingerprint,
        expected_candidate_set_fingerprint=issueplan.source_snapshot.candidate_set_fingerprint,
        expected_implementation_contract_fingerprint=issueplan.implementation_contract_fingerprint,
        freshness_boundary=issueplan.freshness_boundary,
        readiness_stage_result=readiness,
        planning_stage_result=planning,
        proposal_stage_result=proposal,
    )
    values.update(overrides)
    return values


def _pending_approval(proposal):
    return prepare_approval_projection(
        proposal,
        candidate_context=_context(),
        evaluated_at="2026-08-06T04:15:00Z",
        projected_at="2026-08-06T04:15:00Z",
    )


def _approved_projection(proposal):
    approved = prepare_approval_projection(
        proposal,
        candidate_context=_context(),
        approval_decision=_decision(ApprovalState.APPROVED),
        evaluated_at="2026-08-06T04:15:00Z",
        projected_at="2026-08-06T04:15:00Z",
    )
    assert approved.status is ApprovalProjectionStageStatus.COMPLETE
    projection = replace(
        approved.projection,
        repository="Blummer92/agent-os",
        allowed_files=(_ALLOWED_PATH,),
        forbidden_paths=(".github/workflows",),
        required_tests=(_COMMAND,),
        projection_id="",
    )
    projection_result = ApprovedExecutionProjectionResult("complete", projection, (), ())
    return replace(approved, projection_result=projection_result, projection=projection)


def _build_execution_packet(approved, proposal, tmp_path, *, candidate_sha="d" * 40, **overrides):
    repository_root = tmp_path / "repo"
    workspace_parent = tmp_path / "worktrees"
    repository_root.mkdir(exist_ok=True)
    workspace_parent.mkdir(exist_ok=True)
    values = dict(
        repository_identity=proposal.repository_state_evidence.repository_identity,
        repository_state_evidence=proposal.repository_state_evidence,
        issue_number=750,
        invocation_id="candidate-packet-755",
        candidate_branch=_BRANCH,
        candidate_sha=candidate_sha,
        tested_sha=approved.projection.tested_repository_sha,
        evaluator_sha=approved.projection.evaluator_commit_sha,
        expected_changed_paths=(_ALLOWED_PATH,),
        required_tests=approved.projection.required_tests,
        created_at="2026-08-11T12:00:00Z",
        expires_at="2026-08-11T13:00:00Z",
        evaluated_at="2026-08-11T12:01:00Z",
        repository_root=str(repository_root.resolve()),
        workspace_parent=str(workspace_parent.resolve()),
        validation_bundle_id="validation-bundle:prior-evidence",
        advisory_result_id="advisory-result:prior-evidence",
        advisory_render_id="advisory-render:prior-evidence",
        execution_authorization_present=True,
    )
    values.update(overrides)
    return prepare_execution_packet(approved, CandidateRuntimeInputs(**values))


def valid_approval_ready_input(**overrides):
    readiness, planning, proposal = _pipeline()
    approval = _pending_approval(proposal)
    kwargs = _common_kwargs(readiness, planning, proposal)
    kwargs["requested_phase"] = CandidatePacketPhase.APPROVAL_READY
    kwargs["approval_stage_result"] = approval
    kwargs.update(overrides)
    return CandidatePacketCompilerInput(**kwargs)


def valid_execution_candidate_input(tmp_path, *, candidate_sha="d" * 40, **overrides):
    readiness, planning, proposal = _pipeline()
    approved = _approved_projection(proposal)
    execution_packet = _build_execution_packet(approved, proposal, tmp_path, candidate_sha=candidate_sha)
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
    kwargs.update(overrides)
    return CandidatePacketCompilerInput(**kwargs)


# --------------------------------------------------------------------------
# Successful compilation.
# --------------------------------------------------------------------------


def test_approval_ready_compiles_to_a_verified_packet() -> None:
    result = compile_candidate_packet(valid_approval_ready_input(), evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacket)
    assert result.phase is CandidatePacketPhase.APPROVAL_READY
    assert result.command_identities == ()
    assert result.argv_bindings == ()
    assert result.per_command_timeout_seconds is None
    assert result.approval_boundary_summary == "pending-candidate-only:no-human-decision-claimed"
    assert result.execution_authorization_boundary_summary == "not-applicable:approval-ready-phase"
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False


def test_execution_candidate_compiles_with_command_and_runtime_evidence(tmp_path) -> None:
    result = compile_candidate_packet(
        valid_execution_candidate_input(tmp_path), evaluated_at="2026-08-11T12:05:00Z"
    )

    assert isinstance(result, CandidatePacket)
    assert result.phase is CandidatePacketPhase.EXECUTION_CANDIDATE
    assert result.command_identities == (_COMMAND,)
    assert result.argv_bindings[0][0] == _COMMAND
    assert result.argv_bindings[0][1] == ("python", "-m", "pytest", _ALLOWED_PATH)
    assert result.per_command_timeout_seconds == 30
    assert result.total_timeout_seconds == 300
    assert result.max_output_bytes == 65_536
    assert "decision-applied:approved" in result.approval_boundary_summary
    assert "execution-authorization-present=True" in result.execution_authorization_boundary_summary
    assert result.execution_authorized is False


def test_repeated_identical_inputs_produce_identical_packet_ids() -> None:
    first = compile_candidate_packet(valid_approval_ready_input(), evaluated_at="2026-08-06T05:00:00Z")
    second = compile_candidate_packet(valid_approval_ready_input(), evaluated_at="2026-09-01T00:00:00Z")

    assert isinstance(first, CandidatePacket)
    assert isinstance(second, CandidatePacket)
    assert first.packet_id == second.packet_id
    assert first.evaluated_at != second.evaluated_at


def test_execution_candidate_packet_ids_differ_by_candidate_sha(tmp_path) -> None:
    first = compile_candidate_packet(
        valid_execution_candidate_input(tmp_path, candidate_sha="d" * 40),
        evaluated_at="2026-08-11T12:05:00Z",
    )
    second = compile_candidate_packet(
        valid_execution_candidate_input(tmp_path, candidate_sha="e" * 40),
        evaluated_at="2026-08-11T12:05:00Z",
    )

    assert isinstance(first, CandidatePacket)
    assert isinstance(second, CandidatePacket)
    assert first.packet_id != second.packet_id


def test_successful_packet_serializes_and_reconstructs_exactly() -> None:
    from scripts.agent_os_candidate_packet.models import deserialize_candidate_packet, serialize_candidate_packet

    result = compile_candidate_packet(valid_approval_ready_input(), evaluated_at="2026-08-06T05:00:00Z")
    payload = serialize_candidate_packet(result)
    rebuilt = deserialize_candidate_packet(payload)

    assert rebuilt == result
    assert serialize_candidate_packet(rebuilt) == payload


# --------------------------------------------------------------------------
# Type, schema, and phase failures.
# --------------------------------------------------------------------------


def test_wrong_compiler_input_type_fails_closed() -> None:
    result = compile_candidate_packet(object(), evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "compiler-input.wrong-type"
    assert result.requested_phase is CandidatePacketPhase.APPROVAL_READY
    assert result.packet_constructed is False


def test_unsupported_compiler_schema_version_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(compiler_schema_version="9.9")

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "compiler-input.unsupported-schema-version"


def test_empty_evaluated_at_is_a_caller_programming_error() -> None:
    with pytest.raises(TypeError):
        compile_candidate_packet(valid_approval_ready_input(), evaluated_at="")


def test_authority_field_tamper_fails_closed() -> None:
    compiler_input = valid_approval_ready_input()
    object.__setattr__(compiler_input, "side_effects_performed", True)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "compiler-input.authority-field-set-true"


def test_execution_packet_carried_during_approval_ready_is_rejected(tmp_path) -> None:
    readiness, planning, proposal = _pipeline()
    approval = _pending_approval(proposal)
    approved = _approved_projection(proposal)
    execution_packet = _build_execution_packet(approved, proposal, tmp_path)
    kwargs = _common_kwargs(readiness, planning, proposal)
    kwargs["requested_phase"] = CandidatePacketPhase.APPROVAL_READY
    kwargs["approval_stage_result"] = approval
    kwargs["execution_packet_stage_result"] = execution_packet
    compiler_input = CandidatePacketCompilerInput(**kwargs)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "compiler-input.phase-scope-violation"


# --------------------------------------------------------------------------
# Freshness and binding failures.
# --------------------------------------------------------------------------


def test_source_revision_drift_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(expected_source_revision="github-issue-v1:" + "0" * 64)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "source-stage.source-revision-mismatch"


def test_implementation_contract_fingerprint_drift_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(
        expected_implementation_contract_fingerprint="1" * 64
    )

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "issueplan.fingerprint-mismatch"


def test_evaluator_sha_drift_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(evaluator_sha="f" * 40)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.evaluator-sha-mismatch"


def test_base_sha_drift_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(base_sha="c" * 40)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.base-sha-mismatch"


def test_repository_mismatch_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(repository="someone-else/other-repo")

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.repository-mismatch"


def test_issue_number_mismatch_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(issue_number=999)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.issue-mismatch"


def test_execution_candidate_tested_sha_drift_fails_closed(tmp_path) -> None:
    compiler_input = valid_execution_candidate_input(tmp_path, tested_sha="9" * 40)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-11T12:05:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.tested-sha-mismatch"


def test_execution_candidate_invocation_mismatch_fails_closed(tmp_path) -> None:
    compiler_input = valid_execution_candidate_input(tmp_path, invocation_id="some-other-invocation")

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-11T12:05:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.invocation-mismatch"


def test_execution_candidate_candidate_ref_mismatch_fails_closed(tmp_path) -> None:
    compiler_input = valid_execution_candidate_input(tmp_path, candidate_ref="agent/other-branch")

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-11T12:05:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "cross-binding.candidate-ref-mismatch"


# --------------------------------------------------------------------------
# Missing-evidence, blocked, and needs-decision propagation.
# --------------------------------------------------------------------------


def test_blocked_readiness_propagates_as_a_blocked_source_failure() -> None:
    dependency = DependencyEvidence(
        EvidenceStatus.RESOLVED_BLOCKED, reason_codes=("dependency.explicitly-blocked",)
    )
    blocked_readiness = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(dependency=dependency)
    )
    readiness, planning, proposal = _pipeline()
    kwargs = _common_kwargs(readiness, planning, proposal, readiness_stage_result=blocked_readiness)
    kwargs["requested_phase"] = CandidatePacketPhase.APPROVAL_READY
    kwargs["approval_stage_result"] = _pending_approval(proposal)
    compiler_input = CandidatePacketCompilerInput(**kwargs)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "source-stage.blocked"
    assert result.failure_class.value == "contract-conflict"


def test_missing_approval_stage_result_fails_closed() -> None:
    compiler_input = valid_approval_ready_input(approval_stage_result=None)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "approval-stage.missing"
    assert result.remediation_owner == "integration-manager"


def test_execution_candidate_with_needs_decision_approval_fails_closed() -> None:
    readiness, planning, proposal = _pipeline()
    approval = _pending_approval(proposal)
    kwargs = _common_kwargs(readiness, planning, proposal)
    kwargs["requested_phase"] = CandidatePacketPhase.EXECUTION_CANDIDATE
    kwargs["approval_stage_result"] = approval
    compiler_input = CandidatePacketCompilerInput(**kwargs)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "approval-stage.decision-missing"
    assert result.human_judgment_required is False
    assert result.external_authorization_required is True


def test_execution_candidate_missing_execution_packet_fails_closed() -> None:
    readiness, planning, proposal = _pipeline()
    approved = _approved_projection(proposal)
    kwargs = _common_kwargs(
        readiness,
        planning,
        proposal,
        candidate_sha="d" * 40,
        source_sha="d" * 40,
        tested_sha=approved.projection.tested_repository_sha,
        evaluator_sha=approved.projection.evaluator_commit_sha,
    )
    kwargs["requested_phase"] = CandidatePacketPhase.EXECUTION_CANDIDATE
    kwargs["approval_stage_result"] = approved
    compiler_input = CandidatePacketCompilerInput(**kwargs)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-11T12:05:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "execution-packet.missing"


def test_execution_candidate_with_incomplete_execution_packet_fails_closed(tmp_path) -> None:
    readiness, planning, proposal = _pipeline()
    approved = _approved_projection(proposal)
    incomplete_packet = _build_execution_packet(
        approved, proposal, tmp_path, tested_sha="1" * 40
    )
    assert incomplete_packet.packet_complete is False
    kwargs = _common_kwargs(
        readiness,
        planning,
        proposal,
        candidate_sha="d" * 40,
        source_sha="d" * 40,
        tested_sha=approved.projection.tested_repository_sha,
        evaluator_sha=approved.projection.evaluator_commit_sha,
    )
    kwargs["requested_phase"] = CandidatePacketPhase.EXECUTION_CANDIDATE
    kwargs["approval_stage_result"] = approved
    kwargs["execution_packet_stage_result"] = incomplete_packet
    compiler_input = CandidatePacketCompilerInput(**kwargs)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-11T12:05:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "execution-packet.not-complete"


# --------------------------------------------------------------------------
# Authority and partial-result invariants.
# --------------------------------------------------------------------------


def test_no_partial_packet_is_ever_returned_on_failure() -> None:
    result = compile_candidate_packet(
        valid_approval_ready_input(approval_stage_result=None), evaluated_at="2026-08-06T05:00:00Z"
    )

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.packet_constructed is False
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.automatic_retry is False
    assert result.side_effects_performed is False


def test_stable_first_failure_validation_order() -> None:
    """A source failure is reported even when a later object is also invalid."""
    dependency = DependencyEvidence(
        EvidenceStatus.RESOLVED_BLOCKED, reason_codes=("dependency.explicitly-blocked",)
    )
    blocked_readiness = prepare_issue_readiness(
        _request(), _FakeIssueReader(), _FakeRepositoryReader(dependency=dependency)
    )
    readiness, planning, proposal = _pipeline()
    kwargs = _common_kwargs(
        readiness,
        planning,
        proposal,
        readiness_stage_result=blocked_readiness,
        repository="also-wrong/repo",
    )
    kwargs["requested_phase"] = CandidatePacketPhase.APPROVAL_READY
    kwargs["approval_stage_result"] = None
    compiler_input = CandidatePacketCompilerInput(**kwargs)

    result = compile_candidate_packet(compiler_input, evaluated_at="2026-08-06T05:00:00Z")

    assert isinstance(result, CandidatePacketCompilationFailure)
    assert result.reason_code == "source-stage.blocked"


# --------------------------------------------------------------------------
# Duplicate/bounds helper.
# --------------------------------------------------------------------------


def test_first_duplicate_helper_detects_the_first_repeat() -> None:
    assert _first_duplicate(["a", "b", "c"]) is None
    assert _first_duplicate(["a", "b", "a"]) == "a"
