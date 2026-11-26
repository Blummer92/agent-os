"""Focused #1985 tests for the pre-validation candidate-input seam."""

from scripts.agent_os_candidate_packet.pre_validation_stage import (
    PreValidationCandidateInputs,
    prepare_pre_validation_stage,
)
from scripts.agent_os_candidate_packet.validation_stage import (
    ValidationStageDisposition,
    prepare_validation_stage,
)
from tests.agent_os_candidate_packet.test_validation_stage import _approved, _inputs


def _pre_inputs(full_inputs):
    return PreValidationCandidateInputs(
        repository_identity=full_inputs.repository_identity,
        repository_state_evidence=full_inputs.repository_state_evidence,
        issue_number=full_inputs.issue_number,
        invocation_id=full_inputs.invocation_id,
        candidate_branch=full_inputs.candidate_branch,
        candidate_sha=full_inputs.candidate_sha,
        tested_sha=full_inputs.tested_sha,
        evaluator_sha=full_inputs.evaluator_sha,
        expected_changed_paths=full_inputs.expected_changed_paths,
        required_tests=full_inputs.required_tests,
    )


def test_pre_validation_inputs_produce_same_canonical_plan_as_full_inputs(tmp_path) -> None:
    approved, repository_evidence = _approved()
    full_inputs = _inputs(tmp_path, approved.projection, repository_evidence)

    full = prepare_validation_stage(approved, full_inputs)
    pre = prepare_pre_validation_stage(approved, _pre_inputs(full_inputs))

    assert full.disposition is ValidationStageDisposition.GO
    assert pre.disposition is ValidationStageDisposition.GO
    assert pre.subject == full.subject
    assert pre.validation_plan == full.validation_plan
    assert pre.subject_id == full.subject_id
    assert pre.validation_plan_id == full.validation_plan_id
    assert pre.reason_codes == full.reason_codes
    assert pre.execution_authorized is False
    assert pre.merge_authorized is False
    assert pre.side_effects_performed is False


def test_pre_validation_inputs_require_no_post_validation_evidence_ids(tmp_path) -> None:
    approved, repository_evidence = _approved()
    full_inputs = _inputs(tmp_path, approved.projection, repository_evidence)

    pre = _pre_inputs(full_inputs)
    assert not hasattr(pre, "validation_bundle_id")
    assert not hasattr(pre, "advisory_result_id")
    assert not hasattr(pre, "advisory_render_id")

    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.GO


def test_pre_validation_required_test_drift_fails_closed(tmp_path) -> None:
    approved, repository_evidence = _approved()
    full_inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    pre = PreValidationCandidateInputs(
        repository_identity=full_inputs.repository_identity,
        repository_state_evidence=full_inputs.repository_state_evidence,
        issue_number=full_inputs.issue_number,
        invocation_id=full_inputs.invocation_id,
        candidate_branch=full_inputs.candidate_branch,
        candidate_sha=full_inputs.candidate_sha,
        tested_sha=full_inputs.tested_sha,
        evaluator_sha=full_inputs.evaluator_sha,
        expected_changed_paths=full_inputs.expected_changed_paths,
        required_tests=("python -m pytest",),
    )

    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("required-tests-mismatch",)
