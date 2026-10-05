"""Surface-neutral zero-job classification and live admission projection (#3277).

Extends the #2731 classifier (without replacing it) so zero-job workflow runs
are never read as a code-test failure, a pending run, or a pass:

- ``action_required`` + 0 jobs  -> stale / non-executed evidence;
- completed ``failure`` + 0 jobs -> pre-job / workflow-definition failure;
- no conclusion + 0 jobs         -> currentness cross-check required;
- an executed failure dominates every non-executed shape.
"""
import pytest

from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    MAX_ZERO_JOB_RECOVERY_ATTEMPTS,
    WorkflowRunConclusionEvidence as Run,
    ZeroJobAdmissionEvidence,
    ZeroJobRunDisposition,
    classify_workflow_run_evidence,
    project_zero_job_admission,
)

HEAD = "b" * 40
MOVED = "c" * 40
MAIN = "a" * 40


def evidence(*runs, **overrides):
    values = dict(
        workflow_runs=tuple(runs),
        pull_request_number=3277,
        expected_head_sha=HEAD,
        current_head_sha=HEAD,
    )
    values.update(overrides)
    return ZeroJobAdmissionEvidence(**values)


def test_action_required_zero_jobs_is_stale_non_executed():
    assert (
        classify_workflow_run_evidence((Run(1, "action_required", 0),))
        is ZeroJobRunDisposition.STALE_NON_EXECUTED
    )


def test_completed_failure_zero_jobs_is_pre_job_failure_not_indeterminate():
    assert (
        classify_workflow_run_evidence((Run(1, "failure", 0),))
        is ZeroJobRunDisposition.PRE_JOB_FAILURE
    )


def test_null_conclusion_zero_jobs_requires_currentness_cross_check_not_pending():
    assert (
        classify_workflow_run_evidence((Run(1, None, 0),))
        is ZeroJobRunDisposition.CURRENTNESS_CROSS_CHECK_REQUIRED
    )


@pytest.mark.parametrize(
    "non_executed",
    [
        Run(2, "action_required", 0),
        Run(2, "failure", 0),
        Run(2, None, 0),
    ],
)
def test_executed_failure_dominates_every_non_executed_shape(non_executed):
    executed_failure = Run(3, "failure", 4)
    assert (
        classify_workflow_run_evidence((non_executed, executed_failure))
        is ZeroJobRunDisposition.REAL_FAILURE
    )


def test_executed_in_flight_run_is_still_pending():
    assert (
        classify_workflow_run_evidence((Run(1, None, 3), Run(2, "action_required", 0)))
        is ZeroJobRunDisposition.PENDING
    )


def test_executed_success_with_jobs_is_not_classified_as_non_executed():
    assert (
        classify_workflow_run_evidence((Run(1, "success", 5),))
        is ZeroJobRunDisposition.INDETERMINATE
    )


def test_stale_non_executed_projects_bounded_exact_head_redispatch():
    projection = project_zero_job_admission(
        evidence(Run(1, "action_required", 0), expected_main_sha=MAIN)
    )
    assert projection.gates_code_repair is True
    assert projection.bounded_continuation is True
    assert projection.next_action == "reinvoke-governed-exact-head-validation"
    recovery = projection.recovery
    assert recovery is not None
    assert recovery.expected_head_sha == HEAD
    assert recovery.expected_main_sha == MAIN
    assert recovery.attempt == 1
    assert recovery.max_attempts == MAX_ZERO_JOB_RECOVERY_ATTEMPTS == 2
    assert recovery.tree_change_permitted is False
    assert recovery.side_effects_performed is False


def test_recovery_attempt_counts_up_to_the_two_attempt_maximum():
    second = project_zero_job_admission(
        evidence(Run(1, "action_required", 0), recovery_attempts_used=1)
    )
    assert second.recovery is not None and second.recovery.attempt == 2


def test_third_recovery_attempt_is_refused_with_explicit_exhaustion():
    projection = project_zero_job_admission(
        evidence(Run(1, "action_required", 0), recovery_attempts_used=2)
    )
    assert projection.recovery is None
    assert projection.bounded_continuation is False
    assert projection.gates_code_repair is True
    assert "zero-job-recovery.attempts-exhausted" in projection.reason_codes
    assert projection.next_action == "route-zero-job-recovery-exhaustion-to-canonical-owner"


@pytest.mark.parametrize(
    "run",
    [Run(1, "action_required", 0), Run(1, "failure", 0), Run(1, None, 0)],
)
def test_head_move_fails_closed_for_every_non_executed_shape(run):
    projection = project_zero_job_admission(evidence(run, current_head_sha=MOVED))
    assert projection.recovery is None
    assert projection.bounded_continuation is False
    assert projection.gates_code_repair is True
    assert projection.reason_codes == ("zero-job-evidence.head-moved",)
    assert projection.next_action == "reacquire-current-head-and-exact-head-validation-evidence"


def test_pre_job_failure_is_not_redispatched():
    projection = project_zero_job_admission(evidence(Run(1, "failure", 0)))
    assert projection.recovery is None
    assert projection.bounded_continuation is False
    assert projection.next_action == "diagnose-pre-job-workflow-definition-failure"


def test_currentness_shape_is_not_redispatched():
    projection = project_zero_job_admission(evidence(Run(1, None, 0)))
    assert projection.recovery is None
    assert projection.bounded_continuation is False
    assert projection.next_action == "cross-check-run-currentness-against-exact-head"


def test_executed_failure_adds_no_gating():
    projection = project_zero_job_admission(evidence(Run(1, "failure", 6)))
    assert projection.disposition is ZeroJobRunDisposition.REAL_FAILURE
    assert projection.gates_code_repair is False
    assert projection.next_action is None
    assert projection.reason_codes == ()


def test_evidence_validation_rejects_malformed_inputs():
    with pytest.raises(TypeError):
        ZeroJobAdmissionEvidence(  # type: ignore[arg-type]
            workflow_runs=[Run(1, None, 0)],
            pull_request_number=1,
            expected_head_sha=HEAD,
            current_head_sha=HEAD,
        )
    with pytest.raises(ValueError):
        evidence(Run(1, None, 0), recovery_attempts_used=-1)
    with pytest.raises(ValueError):
        evidence(Run(1, None, 0), pull_request_number=0)
    with pytest.raises(ValueError):
        evidence(Run(1, None, 0), expected_head_sha="")
