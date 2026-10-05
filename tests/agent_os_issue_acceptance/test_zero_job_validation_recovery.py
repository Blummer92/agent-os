"""Regression coverage for #2731: action_required runs with zero jobs.

Reproduces the 2026-09-21 incident on PR #2724 where the Validation Gate run
35482678766 and the Issue Acceptance run 35482678780 both concluded
``action_required`` with zero jobs, and proves the live zero-job classifier
(``classify_workflow_run_evidence``) routes each run shape to its governed
disposition. The bounded recovery behavior itself is owned by the live
failed-repair admission path (see
``test_failed_repair_zero_job_admission.py``); the retired BM2 batch
coordinator's recovery-path tests were removed with #3085 (Wave 4).
"""
from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    WorkflowRunConclusionEvidence,
    ZeroJobRunDisposition,
    classify_workflow_run_evidence,
)


def stale_run(run_id):
    return WorkflowRunConclusionEvidence(run_id, "action_required", 0)


def test_incident_runs_classify_as_stale_non_executed():
    runs = (stale_run(35482678766), stale_run(35482678780))
    assert classify_workflow_run_evidence(runs) is ZeroJobRunDisposition.STALE_NON_EXECUTED


def test_executed_failure_dominates_stale_evidence():
    runs = (
        WorkflowRunConclusionEvidence(1, "failure", 3),
        stale_run(35482678780),
    )
    assert classify_workflow_run_evidence(runs) is ZeroJobRunDisposition.REAL_FAILURE


def test_in_flight_and_queued_runs_classify_as_pending():
    assert classify_workflow_run_evidence(
        (WorkflowRunConclusionEvidence(1, None, 2),)
    ) is ZeroJobRunDisposition.PENDING
    # #3277: a zero-job run with no conclusion is not a genuinely pending
    # validation; it requires a currentness cross-check against the exact head.
    assert classify_workflow_run_evidence(
        (WorkflowRunConclusionEvidence(1, None, 0),)
    ) is ZeroJobRunDisposition.CURRENTNESS_CROSS_CHECK_REQUIRED


def test_action_required_with_jobs_is_pending_not_stale():
    runs = (WorkflowRunConclusionEvidence(1, "action_required", 4),)
    assert classify_workflow_run_evidence(runs) is ZeroJobRunDisposition.PENDING


def test_empty_run_evidence_is_indeterminate_and_preserves_behavior():
    assert classify_workflow_run_evidence(()) is ZeroJobRunDisposition.INDETERMINATE
