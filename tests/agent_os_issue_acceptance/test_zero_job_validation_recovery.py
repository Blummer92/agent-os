"""Regression coverage for #2731: action_required runs with zero jobs.

Reproduces the 2026-09-21 incident on PR #2724 where the Validation Gate run
35482678766 and the Issue Acceptance run 35482678780 both concluded
``action_required`` with zero jobs, and proves the batch now recovers through
a bounded governed re-invocation of the existing exact-head validation
authority instead of stalling.
"""
from scripts.agent_os_issue_acceptance.batch_merge_execution import (
    BatchItemDisposition,
    BatchMergeAction,
    CurrentPrEvidence,
    ItemAdmissionEvidence,
    apply_current_state,
    apply_merge_authorization,
    apply_validation,
    expected_zero_job_recovery,
    record_zero_job_recovery,
    start_batch_execution,
)
from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import (
    PrBatchItemEvidence,
    build_pr_batch_merge_plan,
)
from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
    MAX_ZERO_JOB_RECOVERY_ATTEMPTS,
    WorkflowRunConclusionEvidence,
    ZeroJobRunDisposition,
    classify_workflow_run_evidence,
)

HEAD = "6b2024d39874d08dfa59c846a629c37735393528"
MAIN = "a" * 40


def stale_run(run_id):
    return WorkflowRunConclusionEvidence(run_id, "action_required", 0)


def plan(*prs):
    return build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision=MAIN,
        requested_pull_requests=prs,
        evidence=[
            PrBatchItemEvidence(p, f"h{p}", "main", "open", "applicable") for p in prs
        ],
    )


def current(pr, head):
    return CurrentPrEvidence(pr, MAIN, head, "open", "current")


def admit(pr, head, validation="failed", runs=()):
    return ItemAdmissionEvidence(pr, MAIN, head, validation, "authorized",
                                 workflow_runs=runs)


def at_validate(pr, head):
    c = start_batch_execution(plan(pr))
    return apply_current_state(c, current(pr, head))


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


def test_zero_job_stall_enters_bounded_recovery_not_failure():
    runs = (stale_run(35482678766), stale_run(35482678780))
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, runs=runs))
    assert c.action is BatchMergeAction.RECOVER_STALE_VALIDATION
    assert c.zero_job_recovery_attempts == 1


def test_recovery_reinvokes_governed_validation_without_tree_change():
    runs = (stale_run(35482678766), stale_run(35482678780))
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, runs=runs))
    projection = expected_zero_job_recovery(c)
    assert projection.pull_request_number == 2724
    assert projection.expected_head_sha == HEAD
    assert projection.expected_main_sha == MAIN
    assert projection.recovery_operation == "reinvoke-governed-exact-head-validation"
    assert projection.attempt == 1
    assert projection.max_attempts == MAX_ZERO_JOB_RECOVERY_ATTEMPTS
    assert projection.tree_change_permitted is False


def test_batch_continues_after_fresh_exact_head_evidence():
    runs = (stale_run(35482678766), stale_run(35482678780))
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, runs=runs))
    c = record_zero_job_recovery(
        c, pull_request_number=2724, expected_head_sha=HEAD, accepted=True
    )
    assert c.action is BatchMergeAction.VALIDATE
    c = apply_validation(c, admit(2724, HEAD, validation="passed"))
    assert c.action is BatchMergeAction.AUTHORIZE
    c = apply_merge_authorization(c, admit(2724, HEAD, validation="passed"))
    assert c.action is BatchMergeAction.MERGE


def test_recovery_is_bounded_then_item_local_skip_continues_batch():
    runs = (stale_run(35482678766), stale_run(35482678780))
    c = start_batch_execution(plan(2724, 2725))
    c = apply_current_state(c, current(2724, HEAD))
    for _ in range(MAX_ZERO_JOB_RECOVERY_ATTEMPTS):
        c = apply_validation(c, admit(2724, HEAD, runs=runs))
        assert c.action is BatchMergeAction.RECOVER_STALE_VALIDATION
        c = record_zero_job_recovery(
            c, pull_request_number=2724, expected_head_sha=HEAD, accepted=True
        )
        assert c.action is BatchMergeAction.VALIDATE
    c = apply_validation(c, admit(2724, HEAD, runs=runs))
    assert c.results[-1].disposition is BatchItemDisposition.SKIPPED_ITEM_LOCAL
    assert c.results[-1].reason_codes == ("zero-job-recovery-exhausted",)
    assert c.current_pull_request == 2725
    assert c.action is BatchMergeAction.REACQUIRE


def test_recovery_fails_closed_when_head_moves():
    runs = (stale_run(35482678766),)
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, runs=runs))
    moved = "5972c848be8effa4e304b1f82b860beea8742012"
    c = record_zero_job_recovery(
        c, pull_request_number=2724, expected_head_sha=moved, accepted=True
    )
    assert c.action is BatchMergeAction.REACQUIRE
    assert c.zero_job_recovery_attempts == 0


def test_rejected_recovery_skips_item_local():
    runs = (stale_run(35482678766),)
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, runs=runs))
    c = record_zero_job_recovery(
        c, pull_request_number=2724, expected_head_sha=HEAD, accepted=False
    )
    assert c.results[-1].disposition is BatchItemDisposition.SKIPPED_ITEM_LOCAL
    assert c.results[-1].reason_codes == ("zero-job-recovery-rejected",)


def test_real_executed_failure_never_enters_recovery():
    runs = (WorkflowRunConclusionEvidence(9, "failure", 5),)
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, runs=runs))
    assert c.results[-1].disposition is BatchItemDisposition.SKIPPED_ITEM_LOCAL
    assert c.results[-1].reason_codes == ("validation-failed",)


def test_absent_run_evidence_preserves_existing_pending_behavior():
    c = apply_validation(at_validate(2724, HEAD), admit(2724, HEAD, validation="pending"))
    assert c.results[-1].disposition is BatchItemDisposition.SKIPPED_ITEM_LOCAL
    assert c.results[-1].reason_codes == ("validation-pending",)
