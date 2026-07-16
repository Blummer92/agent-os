"""Smoke tests for the Agent OS project execution dry-run MVP."""

import pytest

from workflow_scheduler.project_execution import JobStatus, ProjectExecutionMVP, ProjectJob


def make_job(job_id, issue_number=1, dependencies=None, priority=0):
    return ProjectJob(
        id=job_id,
        issue_number=issue_number,
        title=f"Issue {issue_number}",
        dependencies=dependencies or [],
        priority=priority,
    )


def event_types(system):
    return [event.event_type for event in system.audit_events]


def test_two_independent_jobs_become_ready():
    system = ProjectExecutionMVP([make_job("a"), make_job("b", issue_number=2)])

    ready = system.ready_jobs()

    assert {job.id for job in ready} == {"a", "b"}
    assert system.jobs["a"].status == JobStatus.READY
    assert system.jobs["b"].status == JobStatus.READY


def test_dependent_job_waits_until_dependency_is_complete():
    system = ProjectExecutionMVP([make_job("a"), make_job("b", dependencies=["a"])])

    assert [job.id for job in system.ready_jobs()] == ["a"]

    system.mark_completed("a")

    assert [job.id for job in system.ready_jobs()] == ["b"]


def test_leased_job_cannot_be_claimed_twice():
    system = ProjectExecutionMVP([make_job("a")])

    first_claim = system.claim_job("a", "worker-a")
    second_claim = system.claim_job("a", "worker-b")

    assert first_claim is not None
    assert first_claim.lease_owner == "worker-a"
    assert second_claim is None


def test_blocked_job_is_not_assigned_to_worker():
    system = ProjectExecutionMVP([make_job("a")])
    system.block_job("a", "governance boundary unclear", governance=True)

    assert system.claim_next("worker-a") is None
    assert system.jobs["a"].status == JobStatus.GOVERNANCE_BLOCKED


def test_validation_failure_prevents_review_ready():
    system = ProjectExecutionMVP([make_job("a")])
    system.claim_job("a", "worker-a")

    system.record_validation("a", passed=False)

    assert system.mark_review_ready("a") is False
    assert system.jobs["a"].status == JobStatus.VALIDATION_FAILED


def test_validation_pass_allows_review_ready():
    system = ProjectExecutionMVP([make_job("a")])
    system.claim_job("a", "worker-a")

    system.record_validation("a", passed=True)

    assert system.mark_review_ready("a") is True
    assert system.jobs["a"].status == JobStatus.REVIEW_READY


def test_workers_cannot_mark_jobs_merged():
    system = ProjectExecutionMVP([make_job("a")])

    with pytest.raises(ValueError, match="Workers cannot mark jobs merged"):
        system.transition_job("a", "merged", actor="worker-a")


def test_dry_run_performs_no_external_writes():
    system = ProjectExecutionMVP([make_job("a")])

    system.claim_job("a", "worker-a")
    system.record_validation("a", passed=True)
    system.mark_review_ready("a")

    assert system.external_write_count == 0


def test_audit_history_records_core_events():
    system = ProjectExecutionMVP([make_job("a")])
    system.block_job("a", "initial review", governance=False)
    system.jobs["a"].status = JobStatus.QUEUED
    system.jobs["a"].blocked_reason = None

    system.claim_job("a", "worker-a")
    system.record_validation("a", passed=True)
    system.mark_review_ready("a")

    assert "job_queued" in event_types(system)
    assert "job_blocked" in event_types(system)
    assert "job_ready" in event_types(system)
    assert "job_claimed" in event_types(system)
    assert "validation_pending" in event_types(system)
    assert "validation_passed" in event_types(system)
    assert "review_ready" in event_types(system)
