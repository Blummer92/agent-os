"""Focused tests for AOS-AUTO1E validation packet preparation (#754)."""

from dataclasses import replace

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.validation_stage import (
    CandidateRuntimeInputs,
    ValidationStageDisposition,
    prepare_validation_stage,
)
from scripts.agent_os_issue_acceptance import ApprovalState
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    ApprovedExecutionProjectionResult,
)
from scripts.agent_os_remote_validation import (
    deserialize_pre_pr_validation_subject,
    serialize_pre_pr_validation_subject,
)
from tests.agent_os_candidate_packet.test_approval_stage import _context, _decision
from tests.agent_os_candidate_packet.test_proposal_stage import _prepare

_COMMAND = "python -m pytest 08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
_CANDIDATE_SHA = "d" * 40
_CREATED = "2026-08-11T12:00:00Z"
_EVALUATED = "2026-08-11T12:01:00Z"
_EXPIRES = "2026-08-11T13:00:00Z"


def _approved():
    repository_proposal = _prepare()
    result = prepare_approval_projection(
        repository_proposal,
        candidate_context=_context(),
        approval_decision=_decision(ApprovalState.APPROVED),
        evaluated_at="2026-08-06T04:15:00Z",
        projected_at="2026-08-06T04:15:00Z",
    )
    assert result.status is ApprovalProjectionStageStatus.COMPLETE
    projection = replace(
        result.projection,
        repository="Blummer92/agent-os",
        allowed_files=("08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",),
        forbidden_paths=(".github/workflows",),
        required_tests=(_COMMAND,),
        projection_id="",
    )
    projection_result = ApprovedExecutionProjectionResult("complete", projection, (), ())
    return replace(
        result,
        projection_result=projection_result,
        projection=projection,
    ), repository_proposal.repository_state_evidence


def _inputs(tmp_path, projection, repository_evidence, **overrides):
    repository_root = tmp_path / "repo"
    workspace_parent = tmp_path / "worktrees"
    repository_root.mkdir(exist_ok=True)
    workspace_parent.mkdir(exist_ok=True)
    values = dict(
        repository_identity=repository_evidence.repository_identity,
        repository_state_evidence=repository_evidence,
        issue_number=754,
        invocation_id="candidate-packet-754",
        candidate_branch="agent/754-validation-execution-packet",
        candidate_sha=_CANDIDATE_SHA,
        tested_sha=projection.tested_repository_sha,
        evaluator_sha=projection.evaluator_commit_sha,
        expected_changed_paths=("08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py",),
        required_tests=projection.required_tests,
        created_at=_CREATED,
        expires_at=_EXPIRES,
        evaluated_at=_EVALUATED,
        repository_root=str(repository_root.resolve()),
        workspace_parent=str(workspace_parent.resolve()),
        validation_bundle_id="validation-bundle:prior-evidence",
        advisory_result_id="advisory-result:prior-evidence",
        advisory_render_id="advisory-render:prior-evidence",
    )
    values.update(overrides)
    return CandidateRuntimeInputs(**values)


def test_complete_projection_produces_candidate_bound_validation_plan(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)

    first = prepare_validation_stage(approved, inputs)
    second = prepare_validation_stage(approved, inputs)

    assert first.disposition is ValidationStageDisposition.GO
    assert first.subject.candidate_bound is True
    assert first.subject.expected_source_sha == _CANDIDATE_SHA
    assert first.subject.tested_sha == approved.projection.tested_repository_sha
    assert first.subject.expected_changed_paths == inputs.expected_changed_paths
    assert first.validation_plan.commands == (_COMMAND,)
    assert first.subject_id == second.subject_id
    assert first.validation_plan_id == second.validation_plan_id
    payload = serialize_pre_pr_validation_subject(first.subject)
    assert payload["expected_changed_paths"] == list(inputs.expected_changed_paths)
    assert deserialize_pre_pr_validation_subject(payload) == first.subject
    assert first.execution_authorized is False
    assert first.merge_authorized is False
    assert first.automatic_retry is False
    assert first.side_effects_performed is False


def test_in_scope_expected_path_drift_changes_subject_and_plan_identity(tmp_path) -> None:
    approved, repository_evidence = _approved()
    with_expected_path = _inputs(tmp_path, approved.projection, repository_evidence)
    without_expected_path = replace(with_expected_path, expected_changed_paths=())

    first = prepare_validation_stage(approved, with_expected_path)
    second = prepare_validation_stage(approved, without_expected_path)

    assert first.disposition is ValidationStageDisposition.GO
    assert second.disposition is ValidationStageDisposition.GO
    assert first.subject.expected_changed_paths != second.subject.expected_changed_paths
    assert first.subject_id != second.subject_id
    assert first.validation_plan_id != second.validation_plan_id
    assert "expected_changed_paths" not in serialize_pre_pr_validation_subject(second.subject)


def test_required_test_drift_fails_closed(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        required_tests=("python -m pytest",),
    )

    result = prepare_validation_stage(approved, inputs)

    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("required-tests-mismatch",)


def test_path_scope_drift_fails_closed(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        expected_changed_paths=("outside/scope.py",),
    )

    result = prepare_validation_stage(approved, inputs)

    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("expected-changed-paths-outside-allowlist",)


def test_runtime_bounds_fail_before_packet_construction(tmp_path) -> None:
    approved, repository_evidence = _approved()
    try:
        _inputs(
            tmp_path,
            approved.projection,
            repository_evidence,
            max_output_bytes=65_537,
        )
    except ValueError as exc:
        assert "max_output_bytes" in str(exc)
    else:
        raise AssertionError("oversized output policy must fail closed")