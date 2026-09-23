"""Focused tests for AOS-AUTO1E validation packet preparation (#754)."""

from dataclasses import replace

import pytest

from scripts.agent_os_candidate_packet.approval_stage import (
    ApprovalProjectionStageStatus,
    prepare_approval_projection,
)
from scripts.agent_os_candidate_packet.stage_models import STAGE_SCHEMA_VERSION
from scripts.agent_os_candidate_packet.validation_stage import (
    CandidateRuntimeInputs,
    ValidationStageDisposition,
    ValidationStageResult,
    prepare_validation_stage,
    validation_stage_result_from_dict,
    validation_stage_result_to_dict,
)
from scripts.agent_os_execution_capabilities import RepositoryIdentity
from scripts.agent_os_issue_acceptance import ApprovalState
from scripts.agent_os_issue_acceptance.approved_execution_projection import (
    ApprovedExecutionProjectionResult,
)
from scripts.agent_os_remote_validation import (
    deserialize_pre_pr_validation_subject,
    serialize_pre_pr_validation_subject,
)
from tests.agent_os_candidate_packet.test_approval_stage import _context, _decision
from tests.agent_os_candidate_packet.test_proposal_stage import _observation, _prepare

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


def test_upstream_projection_not_complete_fails_closed(tmp_path) -> None:
    """#754/#1030 candidate-bound admission requires the upstream approval
    projection itself to be complete: matching runtime evidence alone (the
    exact repository, tested SHA, evaluator SHA, and command set a completed
    projection would have carried) must never substitute for a still-pending
    human approval decision. Cross-contract seam: approval_stage -> validation_stage.
    """
    approved, repository_evidence = _approved()
    pending_upstream = _prepare()
    pending = prepare_approval_projection(
        pending_upstream,
        candidate_context=_context(),
        evaluated_at="2026-08-06T04:15:00Z",
        projected_at="2026-08-06T04:15:00Z",
    )
    assert pending.status is not ApprovalProjectionStageStatus.COMPLETE
    assert pending.projection is None

    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    result = prepare_validation_stage(pending, inputs)

    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("upstream-projection-not-complete",)
    assert result.subject is None
    assert result.validation_plan is None


def test_repository_binding_mismatch_fails_closed(tmp_path) -> None:
    """A different candidate's runtime-supplied repository identity must not
    be admitted just because every other field (tested SHA, evaluator SHA,
    required tests) matches the approved projection. One object's identity
    can never satisfy another object's binding requirement.
    """
    approved, repository_evidence = _approved()
    other_identity = RepositoryIdentity(
        host="github.com", owner="other-owner", repository="other-repo"
    )
    other_evidence = replace(
        repository_evidence, repository_identity=other_identity, evidence_id=""
    )
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        repository_identity=other_identity,
        repository_state_evidence=other_evidence,
    )

    result = prepare_validation_stage(approved, inputs)

    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("repository-binding-mismatch",)
    assert result.subject is None


def test_evaluator_sha_mismatch_fails_closed(tmp_path) -> None:
    """The evaluator commit SHA is candidate-owned evidence from the approved
    projection; a runtime-supplied evaluator SHA that drifts from it must
    fail closed rather than being silently accepted.
    """
    approved, repository_evidence = _approved()
    drifted_evaluator_sha = "9" * 40
    assert drifted_evaluator_sha != approved.projection.evaluator_commit_sha
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        evaluator_sha=drifted_evaluator_sha,
    )

    result = prepare_validation_stage(approved, inputs)

    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("evaluator-sha-mismatch",)
    assert result.subject is None


def test_repository_evidence_tested_sha_mismatch_fails_closed(tmp_path) -> None:
    """Runtime inputs can agree with the approved projection's tested SHA on
    their own ``tested_sha`` field while the attached repository-state
    evidence still carries a different tested SHA; the two independent
    tested-SHA checks must not be satisfiable by only one of them matching.
    """
    approved, repository_evidence = _approved()
    drifted_evidence = replace(repository_evidence, tested_sha="8" * 40, evidence_id="")
    assert drifted_evidence.tested_sha != approved.projection.tested_repository_sha
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        repository_state_evidence=drifted_evidence,
    )
    assert inputs.tested_sha == approved.projection.tested_repository_sha

    result = prepare_validation_stage(approved, inputs)

    assert result.disposition is ValidationStageDisposition.BLOCKED
    assert result.reason_codes == ("repository-evidence-tested-sha-mismatch",)
    assert result.subject is None


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


# --------------------------------------------------------------------------
# ValidationStageResult transport (#1054).
# --------------------------------------------------------------------------


def test_go_result_round_trips_to_an_identical_payload(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    result = prepare_validation_stage(approved, inputs)
    assert result.disposition is ValidationStageDisposition.GO

    payload = validation_stage_result_to_dict(result)
    rebuilt = validation_stage_result_from_dict(payload)

    assert type(rebuilt) is ValidationStageResult
    assert rebuilt == result
    assert rebuilt.subject is rebuilt.validation_plan.subject
    assert validation_stage_result_to_dict(rebuilt) == payload
    assert payload["schema_version"] == STAGE_SCHEMA_VERSION
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["automatic_retry"] is False
    assert payload["side_effects_performed"] is False
    assert "subject" not in payload


def test_blocked_result_round_trips_with_every_object_absent(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(
        tmp_path,
        approved.projection,
        repository_evidence,
        required_tests=("python -m pytest",),
    )
    result = prepare_validation_stage(approved, inputs)
    assert result.disposition is ValidationStageDisposition.BLOCKED

    payload = validation_stage_result_to_dict(result)
    rebuilt = validation_stage_result_from_dict(payload)

    assert rebuilt == result
    for key in ("validation_plan", "subject_id", "validation_plan_id", "evaluator_sha"):
        assert payload[key] is None


def test_unsupported_schema_version_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "schema_version": "9.9"}

    with pytest.raises(ValueError, match="unsupported stage schema_version"):
        validation_stage_result_from_dict(bad)


def test_unknown_field_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "surprise": 1}

    with pytest.raises(ValueError, match="unsupported field"):
        validation_stage_result_from_dict(bad)


def test_missing_field_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = dict(payload)
    del bad["validation_plan"]

    with pytest.raises(ValueError, match="missing field"):
        validation_stage_result_from_dict(bad)


def test_malformed_disposition_enum_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "disposition": "NOT-A-REAL-DISPOSITION"}

    with pytest.raises(ValueError):
        validation_stage_result_from_dict(bad)


def test_wrong_nested_validation_plan_type_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "validation_plan": "not-an-object"}

    with pytest.raises((ValueError, TypeError)):
        validation_stage_result_from_dict(bad)


def test_subject_id_drift_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "subject_id": "pre-pr-validation-subject:" + "0" * 64}

    with pytest.raises(ValueError, match="subject_id does not match"):
        validation_stage_result_from_dict(bad)


def test_validation_plan_id_drift_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "validation_plan_id": "pre-pr-validation-plan:" + "0" * 64}

    with pytest.raises(ValueError, match="validation_plan_id does not match"):
        validation_stage_result_from_dict(bad)


def test_issue_number_bool_for_int_is_rejected(tmp_path) -> None:
    """A boolean smuggled in as the subject's issue_number must fail closed."""
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    tampered_plan = dict(payload["validation_plan"])
    tampered_subject = dict(tampered_plan["subject"])
    tampered_subject["issue_number"] = True
    tampered_plan["subject"] = tampered_subject
    bad = {**payload, "validation_plan": tampered_plan}

    with pytest.raises((ValueError, TypeError)):
        validation_stage_result_from_dict(bad)


def test_execution_authorized_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "execution_authorized": True}

    with pytest.raises(ValueError, match="execution_authorized must be false"):
        validation_stage_result_from_dict(bad)


def test_merge_authorized_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "merge_authorized": True}

    with pytest.raises(ValueError, match="merge_authorized must be false"):
        validation_stage_result_from_dict(bad)


def test_automatic_retry_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "automatic_retry": True}

    with pytest.raises(ValueError, match="automatic_retry must be false"):
        validation_stage_result_from_dict(bad)


def test_side_effects_performed_set_true_is_rejected(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    payload = validation_stage_result_to_dict(prepare_validation_stage(approved, inputs))
    bad = {**payload, "side_effects_performed": True}

    with pytest.raises(ValueError, match="side_effects_performed must be false"):
        validation_stage_result_from_dict(bad)


def test_reason_codes_are_canonicalized(tmp_path) -> None:
    approved, repository_evidence = _approved()
    inputs = _inputs(tmp_path, approved.projection, repository_evidence)
    result = replace(
        prepare_validation_stage(approved, inputs),
        reason_codes=("zeta", "alpha", "alpha"),
    )

    payload = validation_stage_result_to_dict(result)

    assert payload["reason_codes"] == ["alpha", "zeta"]


def test_a_foreign_object_is_rejected_at_serialization() -> None:
    with pytest.raises(TypeError):
        validation_stage_result_to_dict(_observation())