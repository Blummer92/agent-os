"""Smoke tests for the Agent OS project execution dry-run MVP."""

from pathlib import Path

import pytest

from workflow_scheduler.project_execution import (
    FixtureIssueQueueLoader,
    FixtureValidationError,
    JobStatus,
    ProjectExecutionMVP,
    ProjectJob,
    ProjectManager,
    ProjectManagerBoundary,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "project_jobs.json"


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


def test_project_manager_boundary_names_responsibilities_and_forbidden_actions():
    boundary = ProjectManagerBoundary()

    assert "select_ready_jobs" in boundary.responsibilities
    assert "job_queue" in boundary.inputs
    assert "selected_jobs" in boundary.outputs
    assert "selection_history" in boundary.owned_state
    assert "merge_pull_request" in boundary.forbidden_actions


def test_project_manager_selects_only_ready_jobs():
    system = ProjectExecutionMVP([
        make_job("ready", priority=2),
        make_job("waiting", dependencies=["done"]),
    ])
    system.jobs["done"] = make_job("done")
    system.mark_completed("done")
    manager = ProjectManager(system)

    selected = manager.select_ready_jobs(limit=1)

    assert [job.id for job in selected] == ["ready"]
    assert manager.selection_history == ["ready"]
    assert "project_manager_selected" in event_types(system)


def test_project_manager_does_not_select_blocked_jobs():
    system = ProjectExecutionMVP([make_job("open"), make_job("blocked")])
    system.block_job("blocked", "approval boundary unclear", governance=True)
    manager = ProjectManager(system)

    selected = manager.select_ready_jobs()
    blocked = manager.blocked_jobs()

    assert [job.id for job in selected] == ["open"]
    assert [job.id for job in blocked] == ["blocked"]


def test_project_manager_assigns_ready_job_through_lease_path():
    system = ProjectExecutionMVP([make_job("a")])
    manager = ProjectManager(system)

    assigned = manager.assign_next("worker-a")

    assert assigned is not None
    assert assigned.id == "a"
    assert assigned.lease_owner == "worker-a"
    assert assigned.status == JobStatus.RUNNING
    assert "project_manager_assigned" in event_types(system)


def test_project_manager_performs_no_external_writes():
    system = ProjectExecutionMVP([make_job("a")])
    manager = ProjectManager(system)

    manager.select_ready_jobs()

    assert manager.external_write_count == 0
    assert system.external_write_count == 0


def test_project_manager_rejects_forbidden_actions():
    manager = ProjectManager(ProjectExecutionMVP([make_job("a")]))

    with pytest.raises(ValueError, match="Project Manager cannot perform forbidden action"):
        manager.perform_forbidden_action("merge_pull_request")


def test_fixture_loader_loads_two_independent_jobs_as_ready():
    loader = FixtureIssueQueueLoader()
    system = loader.load_execution_from_file(FIXTURE_PATH)

    ready = system.ready_jobs()

    assert [job.id for job in ready] == ["issue-101", "issue-102"]


def test_fixture_loader_blocks_dependent_job_until_predecessor_completion():
    loader = FixtureIssueQueueLoader()
    system = loader.load_execution({
        "jobs": [
            {"id": "base", "issue_number": 1, "title": "Base"},
            {
                "id": "dependent",
                "issue_number": 2,
                "title": "Dependent",
                "dependencies": ["base"],
            },
        ]
    })

    assert [job.id for job in system.ready_jobs()] == ["base"]

    system.mark_completed("base")

    assert [job.id for job in system.ready_jobs()] == ["dependent"]


def test_fixture_loader_creates_blocked_job():
    loader = FixtureIssueQueueLoader()
    system = loader.load_execution({
        "jobs": [
            {
                "id": "blocked",
                "issue_number": 3,
                "title": "Blocked",
                "blocked": True,
                "blocked_reason": "waiting for approval",
            }
        ]
    })

    assert system.jobs["blocked"].status == JobStatus.BLOCKED
    assert system.jobs["blocked"].blocked_reason == "waiting for approval"


def test_fixture_loader_invalid_data_raises_clear_error():
    loader = FixtureIssueQueueLoader()

    with pytest.raises(FixtureValidationError, match="issue_number"):
        loader.load_jobs({"jobs": [{"id": "bad", "title": "Missing issue number"}]})


def test_fixture_loader_performs_no_external_writes():
    loader = FixtureIssueQueueLoader()

    loader.load_jobs_from_file(FIXTURE_PATH)

    assert loader.external_write_count == 0


def test_fixture_loaded_jobs_can_be_selected_by_project_manager():
    loader = FixtureIssueQueueLoader()
    system = loader.load_execution_from_file(FIXTURE_PATH)
    manager = ProjectManager(system)

    selected = manager.select_ready_jobs()

    assert [job.id for job in selected] == ["issue-101", "issue-102"]


def test_fixture_loaded_jobs_can_be_assigned_through_lease_path():
    loader = FixtureIssueQueueLoader()
    system = loader.load_execution_from_file(FIXTURE_PATH)
    manager = ProjectManager(system)

    assigned = manager.assign_next("worker-a")

    assert assigned is not None
    assert assigned.id == "issue-101"
    assert assigned.lease_owner == "worker-a"
    assert assigned.status == JobStatus.RUNNING


def test_dependency_graph_three_job_graph_returns_dependency_free_jobs_first():
    system = ProjectExecutionMVP([
        make_job("foundation", priority=2),
        make_job("peer", priority=1),
        make_job("dependent", dependencies=["foundation"], priority=3),
    ])

    batch = system.safe_parallel_batch()

    assert [job.id for job in batch] == ["foundation", "peer"]
    assert system.dependency_blocking_reasons("dependent") == [
        "waiting for dependency foundation (ready)"
    ]
    assert "dependency_blocked" in event_types(system)


def test_dependency_graph_completion_unblocks_dependent_job():
    system = ProjectExecutionMVP([
        make_job("base"),
        make_job("dependent", dependencies=["base"]),
    ])

    assert [job.id for job in system.safe_parallel_batch()] == ["base"]

    system.mark_completed("base")

    assert [job.id for job in system.safe_parallel_batch()] == ["dependent"]
    assert system.jobs["dependent"].dependency_blocking_reasons == []


def test_dependency_graph_parallel_batch_includes_independent_jobs():
    system = ProjectExecutionMVP([
        make_job("a", priority=1),
        make_job("b", priority=2),
        make_job("c", dependencies=["a"]),
    ])

    assert [job.id for job in system.safe_parallel_batch()] == ["b", "a"]


def test_dependency_cycle_prevents_scheduling_and_blocks_jobs():
    system = ProjectExecutionMVP([
        make_job("a", dependencies=["b"]),
        make_job("b", dependencies=["a"]),
    ])

    assert system.safe_parallel_batch() == []
    assert system.jobs["a"].status == JobStatus.BLOCKED
    assert system.jobs["b"].status == JobStatus.BLOCKED
    assert "dependency cycle detected" in system.jobs["a"].blocked_reason
    assert "dependency_cycle_detected" in event_types(system)


def test_dependency_cycle_is_visible_in_dependency_status():
    system = ProjectExecutionMVP([
        make_job("a", dependencies=["b"]),
        make_job("b", dependencies=["a"]),
    ])

    status = system.dependency_status()

    assert "dependency cycle detected" in status["a"][0]
    assert any("waiting for dependency" in reason for reason in status["a"])


def test_dependency_blocking_performs_no_external_writes():
    system = ProjectExecutionMVP([
        make_job("base"),
        make_job("dependent", dependencies=["base"]),
    ])

    system.safe_parallel_batch()

    assert system.external_write_count == 0
    assert "dependency_blocked" in event_types(system)


def test_fixture_loaded_jobs_participate_in_dependency_graph_behavior():
    loader = FixtureIssueQueueLoader()
    system = loader.load_execution_from_file(FIXTURE_PATH)

    assert [job.id for job in system.safe_parallel_batch()] == ["issue-101", "issue-102"]

    system.mark_completed("issue-101")

    assert [job.id for job in system.safe_parallel_batch()] == ["issue-102", "issue-103"]


def test_project_manager_selection_respects_dependency_blocking():
    system = ProjectExecutionMVP([
        make_job("base"),
        make_job("dependent", dependencies=["base"], priority=5),
    ])
    manager = ProjectManager(system)

    assert [job.id for job in manager.select_ready_jobs()] == ["base"]
    assert [job.id for job in manager.blocked_jobs()] == ["dependent"]
