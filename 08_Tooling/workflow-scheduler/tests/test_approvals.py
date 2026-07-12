"""Tests for the Phase 2A approval engine."""

import sys
import tempfile

import pytest
import yaml

from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.cli import WorkflowSchedulerCLI, main
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

    def test_approve_draft_task_is_blocked(self, tmp_path):
        """A task that never entered APPROVAL_PENDING (still Draft) cannot be approved."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]
        assert cli.repository.get_task(task.id).status == TaskStatus.DRAFT
        assert cli.repository.get_approval_request(task.id) is None

    def test_reject_draft_task_is_blocked(self, tmp_path):
        """A task that never entered APPROVAL_PENDING (still Draft) cannot be rejected."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        result = cli.reject(task.id, approver="bob", reason="no")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]
        assert cli.repository.get_task(task.id).status == TaskStatus.DRAFT

    def test_approve_pending_status_task_is_blocked(self, tmp_path):
        """A task sitting in PENDING (not APPROVAL_PENDING) cannot be approved directly."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.PENDING)
        cli.repository.create_task(task)

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]

    def test_approve_running_task_is_blocked(self, tmp_path):
        """A task actively RUNNING cannot be approved out from under itself."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.RUNNING)
        cli.repository.create_task(task)

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]

    def test_reject_running_task_is_blocked(self, tmp_path):
        """A task actively RUNNING cannot be rejected out from under itself."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task(status=TaskStatus.RUNNING)
        cli.repository.create_task(task)

        result = cli.reject(task.id, approver="bob", reason="no")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]

    def test_approve_already_decided_is_blocked(self, tmp_path):
        """A second approve on an already-APPROVED task is blocked by the
        approval_already_decided guard (the task is still APPROVED, not yet
        terminal, so this exercises the decision-lock check specifically)."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.executor.execute(task)  # -> APPROVAL_PENDING
        cli.approve(task.id, approver="alice")  # -> APPROVED

        result = cli.approve(task.id, approver="alice")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]

    def test_reject_already_decided_is_blocked(self, tmp_path):
        """Rejecting terminalizes the task to CANCELLED; a second reject is
        caught by the task-not-awaiting-approval guard."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.executor.execute(task)  # -> APPROVAL_PENDING
        cli.reject(task.id, approver="bob", reason="no")
        result = cli.reject(task.id, approver="bob", reason="still no")

        assert result["status"] == "blocked"
        assert "task_not_awaiting_approval" in result["blockers"]

    def test_approve_already_decided_guard_fires_while_still_pending_status(self, tmp_path):
        """If a task is APPROVAL_PENDING but its approval record was already
        decided (an inconsistent recovery scenario), the decision-lock guard
        fires instead of silently re-deciding it."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        task = make_task()
        cli.repository.create_task(task)

        cli.executor.execute(task)  # -> APPROVAL_PENDING, creates PENDING request
        cli.repository.update_approval_decision(
            task_id=task.id, decision=ApprovalDecision.APPROVED, approver="alice"
        )
        # Task status manually left at APPROVAL_PENDING to simulate the
        # inconsistency (normally cli.approve() would also advance the task).

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
        assert "task_not_awaiting_approval" in result["blockers"]

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


class TestWorkflowRerunAfterApproval:
    """End-to-end: a workflow blocked on approval must be resumable, not terminal."""

    def _write_workflow_yaml(self, tmp_path, approval_required=True, second_task=False):
        tasks = [
            {
                "id": "task-1",
                "type": "test",
                "owner": "system",
                "action": "write:governed_system",
                "idempotency_key": "key-1",
                "approval_required": approval_required,
                "priority": 1,
            }
        ]
        if second_task:
            tasks.append(
                {
                    "id": "task-2",
                    "type": "test",
                    "owner": "system",
                    "action": "test_action",
                    "idempotency_key": "key-2",
                    "depends_on": ["task-1"],
                    "priority": 0,
                }
            )

        workflow_data = {
            "workflow_id": "approval-workflow",
            "title": "Approval Workflow",
            "created_by": "test",
            "mode": "Draft",
            "tasks": tasks,
        }

        yaml_path = tmp_path / "workflow.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(workflow_data, f)
        return str(yaml_path)

    def test_run_blocks_then_approve_then_rerun_completes(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        # First run blocks on approval; workflow must not become terminal.
        first_run = cli.run_workflow("approval-workflow")
        assert first_run["status"] == "blocked"
        assert "tasks_awaiting_approval" in first_run["blockers"]

        workflow_after_first_run = cli.repository.get_workflow("approval-workflow")
        assert not workflow_after_first_run.is_terminal()

        task = cli.repository.get_task("task-1")
        assert task.status == TaskStatus.APPROVAL_PENDING

        # Approve.
        approve_result = cli.approve("task-1", approver="alice")
        assert approve_result["status"] == "pass"

        # Second run must not be refused as "workflow_terminal".
        second_run = cli.run_workflow("approval-workflow")
        assert second_run["status"] == "pass"
        assert second_run["completed"] == 1

        final_task = cli.repository.get_task("task-1")
        assert final_task.status == TaskStatus.COMPLETED

        final_workflow = cli.repository.get_workflow("approval-workflow")
        assert final_workflow.status.value == "completed"

    def test_run_blocks_then_approve_then_rerun_does_not_redo_completed_tasks(self, tmp_path):
        """A downstream task's dependency should not be re-executed on rerun."""
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        yaml_path = self._write_workflow_yaml(tmp_path, second_task=True)
        cli.create_workflow(yaml_path)

        cli.run_workflow("approval-workflow")
        cli.approve("task-1", approver="alice")

        second_run = cli.run_workflow("approval-workflow")

        assert second_run["status"] == "pass"
        assert second_run["completed"] == 2
        assert cli.repository.get_task("task-1").status == TaskStatus.COMPLETED
        assert cli.repository.get_task("task-2").status == TaskStatus.COMPLETED

    def test_run_blocks_then_reject_then_rerun_stays_blocked(self, tmp_path):
        cli = WorkflowSchedulerCLI(db_path=str(tmp_path / "test.db"))
        yaml_path = self._write_workflow_yaml(tmp_path)
        cli.create_workflow(yaml_path)

        cli.run_workflow("approval-workflow")
        cli.reject("task-1", approver="bob", reason="denied")

        second_run = cli.run_workflow("approval-workflow")

        assert second_run["status"] != "pass"
        assert cli.repository.get_task("task-1").status == TaskStatus.GOVERNANCE_BLOCKED


class TestCLIExitCodes:
    """Tests that main() exits 0 on pass and nonzero on fail/blocked."""

    def _run_main(self, monkeypatch, argv):
        monkeypatch.setattr(sys, "argv", ["workflow-scheduler"] + argv)
        with pytest.raises(SystemExit) as exc_info:
            main()
        return exc_info.value.code

    def test_exit_code_zero_on_approve_success(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        cli = WorkflowSchedulerCLI(db_path=db_path)
        task = make_task()
        cli.repository.create_task(task)
        cli.executor.execute(task)  # -> APPROVAL_PENDING

        code = self._run_main(
            monkeypatch, ["approve", task.id, "--approver", "alice", "--db", db_path]
        )

        assert code == 0

    def test_exit_code_nonzero_on_approve_blocked(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        cli = WorkflowSchedulerCLI(db_path=db_path)
        task = make_task()
        cli.repository.create_task(task)  # still Draft, never entered APPROVAL_PENDING

        code = self._run_main(
            monkeypatch, ["approve", task.id, "--approver", "alice", "--db", db_path]
        )

        assert code != 0

    def test_exit_code_nonzero_on_approve_task_not_found(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")

        code = self._run_main(
            monkeypatch, ["approve", "nonexistent", "--approver", "alice", "--db", db_path]
        )

        assert code != 0

    def test_exit_code_zero_on_reject_success(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        cli = WorkflowSchedulerCLI(db_path=db_path)
        task = make_task()
        cli.repository.create_task(task)
        cli.executor.execute(task)  # -> APPROVAL_PENDING

        code = self._run_main(
            monkeypatch,
            ["reject", task.id, "--approver", "bob", "--reason", "no", "--db", db_path],
        )

        assert code == 0

    def test_exit_code_nonzero_on_reject_blocked(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        cli = WorkflowSchedulerCLI(db_path=db_path)
        task = make_task()
        cli.repository.create_task(task)  # still Draft

        code = self._run_main(
            monkeypatch,
            ["reject", task.id, "--approver", "bob", "--reason", "no", "--db", db_path],
        )

        assert code != 0
