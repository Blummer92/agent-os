"""Focused #1985 tests for the pre-validation candidate-input seam."""

from dataclasses import replace

import pytest

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


@pytest.mark.parametrize("field,value,code", [
    ("approval_id", "", "approval-id-missing"),
    ("projection_id", "", "projection-id-missing"),
    ("implementation_contract_fingerprint", "", "implementation-contract-fingerprint-missing"),
    ("approval_revision_number", 0, "approval-revision-invalid"),
    ("proposal_id", "", "proposal-id-missing"),
    ("repository_state_evidence_id", "", "repository-state-evidence-id-missing"),
    ("allowed_files", None, "projection-paths-invalid"),
    ("complete", 1, "upstream-projection-missing"),
])
def test_pre_validation_rejects_malformed_projection_without_losing_trace(tmp_path, field, value, code):
    approved, state = _approved()
    pre = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    object.__setattr__(approved.projection, field, value)
    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == (code,)
    assert (result.issue_number, result.invocation_id) == (pre.issue_number, pre.invocation_id)
    assert result.candidate_sha == pre.candidate_sha
    assert result.subject is result.validation_plan is None
    assert result.execution_authorized is result.merge_authorized is result.side_effects_performed is False


def test_pre_validation_names_forbidden_path_even_when_also_allowed(tmp_path):
    approved, state = _approved()
    pre = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    object.__setattr__(approved.projection, "forbidden_paths", pre.expected_changed_paths)
    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("expected-changed-paths-forbidden",)


@pytest.mark.parametrize("field,code", [
    ("expected_changed_paths", "expected-changed-paths-missing"),
    ("required_tests", "required-tests-missing"),
])
def test_first_run_requires_nonempty_path_and_command_evidence(tmp_path, field, code):
    approved, state = _approved()
    pre = replace(_pre_inputs(_inputs(tmp_path, approved.projection, state)), **{field: ()})
    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == (code,)


def test_first_run_requires_the_approved_repository_observation(tmp_path):
    approved, state = _approved()
    pre = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    other = replace(state, correlation_id="unrelated-observation", evidence_id="")
    result = prepare_pre_validation_stage(approved, replace(pre, repository_state_evidence=other))
    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("repository-state-evidence-id-mismatch",)


def test_supplied_candidate_head_must_not_contradict_observed_branch(tmp_path):
    approved, state = _approved()
    pre = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    observed = replace(state, head_ref=pre.candidate_branch, head_sha="5" * 40,
                       evidence_id="")
    object.__setattr__(approved.projection, "repository_state_evidence_id", observed.evidence_id)
    result = prepare_pre_validation_stage(approved, replace(pre, repository_state_evidence=observed))
    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("candidate-head-sha-mismatch",)


def test_repository_case_binding_preserves_selector_canonical_identity(tmp_path):
    approved, state = _approved()
    pre = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    object.__setattr__(approved.projection, "repository", "blummer92/agent-os")
    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.GO
    assert result.subject.repository == "Blummer92/agent-os"
    assert result.subject.execution_mode == "validation-only" and result.subject.candidate_bound is True


@pytest.mark.parametrize("error,code", [
    (OSError("unavailable"), "validation-rule-map-unavailable"),
    (ValueError("malformed"), "validation-rule-map-invalid"),
])
def test_pre_validation_reports_rule_read_failures(tmp_path, monkeypatch, error, code):
    from scripts.agent_os_candidate_packet import validation_stage

    approved, state = _approved()
    pre = _pre_inputs(_inputs(tmp_path, approved.projection, state))

    def read():
        raise error

    monkeypatch.setattr(validation_stage, "load_rule_map", read)
    result = prepare_pre_validation_stage(approved, pre)
    assert result.reason_codes == (code,)
    assert result.invocation_id == pre.invocation_id
    assert result.subject is None


def test_pre_validation_required_test_set_is_order_independent(tmp_path):
    from scripts.agent_os_remote_validation import load_rule_map

    approved, state = _approved()
    rules = load_rule_map()
    first_path = approved.projection.allowed_files[0]
    second_path = "tests/agent_os_remote_validation/test_selector.py"
    second_command = "python -m pytest tests/agent_os_remote_validation"
    commands = tuple(sorted((*approved.projection.required_tests, second_command)))
    paths = tuple(sorted((first_path, second_path)))
    assert len(commands) == 2 and rules["repository"] == "Blummer92/agent-os"
    pre = replace(_pre_inputs(_inputs(tmp_path, approved.projection, state)),
                  expected_changed_paths=paths, required_tests=commands)
    object.__setattr__(approved.projection, "allowed_files", paths)
    object.__setattr__(approved.projection, "required_tests", tuple(reversed(commands)))
    result = prepare_pre_validation_stage(approved, pre)
    assert result.disposition is ValidationStageDisposition.GO, result.reason_codes
    assert result.validation_plan.commands == commands


@pytest.mark.parametrize("field,value,kind", [
    ("repository_identity", object(), TypeError),
    ("repository_state_evidence", None, TypeError),
    ("issue_number", 0, TypeError),
    ("issue_number", True, TypeError),
    ("invocation_id", "", TypeError),
    ("candidate_sha", "A" * 40, ValueError),
    ("tested_sha", "f" * 39, ValueError),
    ("expected_changed_paths", ["a"], TypeError),
    ("required_tests", ("a", "a"), ValueError),
])
def test_pre_validation_input_exact_bound_facts(tmp_path, field, value, kind):
    approved, state = _approved()
    inputs = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    with pytest.raises(kind, match=field):
        replace(inputs, **{field: value})


def test_pre_validation_rejects_wrong_stage_or_input_type(tmp_path):
    approved, state = _approved()
    inputs = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    with pytest.raises(TypeError, match="approval_projection_stage_result"):
        prepare_pre_validation_stage(None, inputs)
    with pytest.raises(TypeError, match="candidate_inputs"):
        prepare_pre_validation_stage(approved, None)


def test_pre_validation_rejects_observation_from_different_repository(tmp_path):
    approved, state = _approved()
    inputs = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    with pytest.raises(ValueError, match="identity must match"):
        replace(inputs, repository_identity=replace(inputs.repository_identity, owner="other"))


@pytest.mark.parametrize("field,value,kind", [
    ("invocation_id", 1, TypeError),
    ("candidate_sha", 1, ValueError),
    ("expected_changed_paths", ("",), TypeError),
    ("required_tests", (1,), TypeError),
])
def test_pre_validation_input_does_not_coerce_text_items(tmp_path, field, value, kind):
    approved, state = _approved()
    inputs = _pre_inputs(_inputs(tmp_path, approved.projection, state))
    with pytest.raises(kind, match=field):
        replace(inputs, **{field: value})
