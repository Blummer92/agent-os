"""Tests for the Phase 2A approval engine."""

import pytest

from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.execution import Executor
from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import ApprovalDecision, ApprovalRequest, Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository


@pytest.fixture
def repository():
    """Create in-memory SQLite repository for testing."""
    return SQLiteRepository(":memory:")


@pytest.fixture
def executor(repository):
    """Create executor wired to a NoopAdapter and the shared repository."""
    audit_logger = AuditLogger(repository=repository)
    return Executor(adapter=NoopAdapter(), repository=repository, audit_logger=audit_logger)


def make_task(task_id: str = "task-1", **overrides) -> Task:
    """Build a task requiring approval."""
    defaults = dict(
        id=task_id,
        workflow_id="workflow-1",
        type="test",
        owner="system",
        action="write:governed_system",
        idempotency_key=f"key-{task_id}",
        approval_required=True,
    )
    defaults.update(overrides)
    return Task(**defaults)


class TestApprovalRequestRepository:
    """Tests for approval_requests persistence."""

    def test_create_and_get_approval_request(self, repository):
        approval = ApprovalRequest(
            id="approval-1",
            task_id="task-1",
            requested_by="system",
            decision=ApprovalDecision.PENDING,
        )
        repository.create_approval_request(approval)

        retrieved = repository.get_approval_request("task-1")

        assert retrieved is not None
        assert retrieved.id == "approval-1"
        assert retrieved.task_id == "task-1"
        assert retrieved.decision == ApprovalDecision.PENDING
        assert retrieved.approver is None
        assert retrieved.decided_at is None

    def test_get_approval_request_not_found(self, repository):
        assert repository.get_approval_request("nonexistent") is None

    def test_update_approval_decision_to_approved(self, repository):
        approval = ApprovalRequest(id="approval-1", task_id="task-1", requested_by="system")
        repository.create_approval_request(approval)

        updated = repository.update_approval_decision(
            task_id="task-1",
            decision=ApprovalDecision.APPROVED,
            approver="alice",
        )

        assert updated.decision == ApprovalDecision.APPROVED
        assert updated.approver == "alice"
        assert updated.decided_at is not None

    def test_update_approval_decision_to_rejected_with_reason(self, repository):
        approval = ApprovalRequest(id="approval-1", task_id="task-1", requested_by="system")
        repository.create_approval_request(approval)

        updated = repository.update_approval_decision(
            task_id="task-1",
            decision=ApprovalDecision.REJECTED,
            approver="bob",
            reason="not ready for production",
        )

        assert updated.decision == ApprovalDecision.REJECTED
        assert updated.approver == "bob"
        assert updated.reason == "not ready for production"

    def test_get_approval_request_returns_most_recent(self, repository):
        first = ApprovalRequest(id="approval-1", task_id="task-1", requested_by="system")
        repository.create_approval_request(first)

        retrieved = repository.get_approval_request("task-1")
        assert retrieved.id == "approval-1"


class TestGovernanceApprovalIntegration:
    """Governance regression coverage: approval state must gate the stop condition."""

    def test_unapproved_task_still_blocks(self, repository):
        """An approval-required task with no decision must still be blocked."""
        task = make_task()

        result = StopConditionChecker.check_all_stop_conditions(task, source_of_truth_db=repository)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_pending_approval_request_still_blocks(self, repository):
        """A task with a PENDING (undecided) approval request must still be blocked."""
        task = make_task()
        repository.create_approval_request(
            ApprovalRequest(id="approval-1", task_id=task.id, requested_by="system")
        )

        result = StopConditionChecker.check_all_stop_conditions(task, source_of_truth_db=repository)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_approved_task_is_not_blocked(self, repository):
        """Once explicitly APPROVED, the approval_engine_deferred stop condition lifts."""
        task = make_task()
        repository.create_approval_request(
            ApprovalRequest(
                id="approval-1",
                task_id=task.id,
                requested_by="system",
                decision=ApprovalDecision.APPROVED,
                approver="alice",
            )
        )

        result = StopConditionChecker.check_all_stop_conditions(task, source_of_truth_db=repository)

        assert result.is_blocked is False

    def test_rejected_task_still_blocks(self, repository):
        """A REJECTED approval must not lift the stop condition."""
        task = make_task()
        repository.create_approval_request(
            ApprovalRequest(
                id="approval-1",
                task_id=task.id,
                requested_by="system",
                decision=ApprovalDecision.REJECTED,
                approver="bob",
            )
        )

        result = StopConditionChecker.check_all_stop_conditions(task, source_of_truth_db=repository)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_other_stop_conditions_unaffected_by_approval(self, repository):
        """Approval alone must not lift unrelated stop conditions (e.g. ambiguous_target)."""
        task = make_task(action="")  # ambiguous target
        repository.create_approval_request(
            ApprovalRequest(
                id="approval-1",
                task_id=task.id,
                requested_by="system",
                decision=ApprovalDecision.APPROVED,
                approver="alice",
            )
        )

        result = StopConditionChecker.check_all_stop_conditions(task, source_of_truth_db=repository)

        assert result.is_blocked is True
        assert "ambiguous_target" in result.blockers
        assert "approval_engine_deferred" not in result.blockers


class TestExecutorApprovalFlow:
    """Tests for how the executor routes approval-required tasks."""

    def test_execute_creates_pending_approval_request(self, repository, executor):
        task = make_task()
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "blocked"
        assert "approval_engine_deferred" in result.blockers

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.APPROVAL_PENDING

        approval = repository.get_approval_request(task.id)
        assert approval is not None
        assert approval.decision == ApprovalDecision.PENDING

    def test_execute_does_not_duplicate_approval_request(self, repository, executor):
        task = make_task()
        repository.create_task(task)

        executor.execute(task)
        first_approval = repository.get_approval_request(task.id)

        task_reloaded = repository.get_task(task.id)
        executor.execute(task_reloaded)
        second_approval = repository.get_approval_request(task.id)

        assert first_approval.id == second_approval.id

    def test_execute_succeeds_after_approval(self, repository, executor):
        task = make_task()
        repository.create_task(task)

        # First pass creates the pending approval request and blocks.
        executor.execute(task)

        # Explicit human decision.
        repository.update_approval_decision(
            task_id=task.id, decision=ApprovalDecision.APPROVED, approver="alice"
        )

        task_reloaded = repository.get_task(task.id)
        task_reloaded.mark_approved()
        repository.update_task(task_reloaded)

        result = executor.execute(task_reloaded)

        assert result.success is True
        assert result.status == "pass"

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.COMPLETED

    def test_execute_stays_blocked_after_rejection(self, repository, executor):
        task = make_task()
        repository.create_task(task)

        executor.execute(task)

        repository.update_approval_decision(
            task_id=task.id, decision=ApprovalDecision.REJECTED, approver="bob", reason="no"
        )

        task_reloaded = repository.get_task(task.id)
        result = executor.execute(task_reloaded)

        assert result.success is False
        assert result.status == "blocked"

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.GOVERNANCE_BLOCKED

    def test_execute_still_hard_blocks_other_stop_conditions(self, repository, executor):
        """A task with an unrelated blocker (ambiguous_target) is never routed to approval-pending."""
        task = make_task(action="")
        repository.create_task(task)

        result = executor.execute(task)

        assert result.success is False
        assert result.status == "blocked"
        assert "ambiguous_target" in result.blockers

        stored_task = repository.get_task(task.id)
        assert stored_task.status == TaskStatus.GOVERNANCE_BLOCKED
        assert repository.get_approval_request(task.id) is None


class TestCLIApproveReject:
    """Tests for the CLI approve/reject commands."""

    def test_approve_task_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.approve("nonexistent", approver="alice")

        assert result["status"] == "fail"
        assert "not found" in result["error"]

    def test_reject_task_not_found(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        result = cli.reject("nonexistent", approver="alice", reason="no")

        assert result["status"] == "fail"
        assert "not found" in result["error"]

    def test_approve_pending_task(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        # Task must first be blocked into APPROVAL_PENDING via execution.
        cli.executor.execute(task)

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "pass"
        assert result["decision"] == "approved"
        assert result["approver"] == "alice"

        stored_task = cli.repository.get_task(task.id)
        assert stored_task.status == TaskStatus.APPROVED

        approval = cli.repository.get_approval_request(task.id)
        assert approval.decision == ApprovalDecision.APPROVED
        assert approval.approver == "alice"

    def test_reject_pending_task(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.executor.execute(task)

        result = cli.reject(task.id, approver="bob", reason="not ready")

        assert result["status"] == "pass"
        assert result["decision"] == "rejected"
        assert result["reason"] == "not ready"

        stored_task = cli.repository.get_task(task.id)
        assert stored_task.status == TaskStatus.CANCELLED

        approval = cli.repository.get_approval_request(task.id)
        assert approval.decision == ApprovalDecision.REJECTED
        assert approval.reason == "not ready"

    def test_approve_creates_request_if_missing(self, tmp_path):
        """Proactive approval before the task has ever been executed."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "pass"
        approval = cli.repository.get_approval_request(task.id)
        assert approval is not None
        assert approval.decision == ApprovalDecision.APPROVED

    def test_approve_already_decided_is_blocked(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.approve(task.id, approver="alice")
        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "approval_already_decided" in result["blockers"]

    def test_reject_already_decided_is_blocked(self, tmp_path):
        """Rejecting terminalizes the task to CANCELLED, so a second reject is
        caught by the terminal-state guard (a stronger, correct block)."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.reject(task.id, approver="bob", reason="no")
        result = cli.reject(task.id, approver="bob", reason="still no")

        assert result["status"] == "blocked"
        assert "task_terminal" in result["blockers"]

    def test_approve_already_approved_task_is_blocked_by_terminal_state(self, tmp_path):
        """The approval_already_decided guard fires directly when the underlying
        task is not yet terminal but the approval decision itself is locked."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.repository.create_approval_request(
            ApprovalRequest(
                id="approval-manual",
                task_id=task.id,
                requested_by="system",
                decision=ApprovalDecision.APPROVED,
                approver="alice",
            )
        )

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "approval_already_decided" in result["blockers"]

    def test_approve_terminal_task_is_blocked(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        task.mark_completed()
        cli.repository.create_task(task)

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "task_terminal" in result["blockers"]

    def test_approve_end_to_end_unblocks_execution(self, tmp_path):
        """Full loop: block -> approve -> re-execute -> success."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        first = cli.executor.execute(task)
        assert first.status == "blocked"

        cli.approve(task.id, approver="alice")

        approved_task = cli.repository.get_task(task.id)
        second = cli.executor.execute(approved_task)

        assert second.success is True
        assert cli.repository.get_task(task.id).status == TaskStatus.COMPLETED

    def test_reject_end_to_end_stays_blocked(self, tmp_path):
        """Full loop: block -> reject -> re-execute -> still blocked, never completes."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.executor.execute(task)
        cli.reject(task.id, approver="bob", reason="denied")

        rejected_task = cli.repository.get_task(task.id)
        assert rejected_task.status == TaskStatus.CANCELLED

        result = cli.executor.execute(rejected_task)
        assert result.success is False
        assert cli.repository.get_task(task.id).status != TaskStatus.COMPLETED
