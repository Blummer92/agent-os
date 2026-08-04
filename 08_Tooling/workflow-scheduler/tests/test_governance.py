"""Tests for governance stop conditions."""

from typing import object

import pytest

from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import ApprovalDecision, ApprovalRequest, Task, TaskMode
from workflow_scheduler.repository import SQLiteRepository


class TestStopConditions:
    """Tests for stop condition enforcement."""

    def test_approval_engine_deferred_production_ready(self):
        """Test that production_ready tasks are blocked with approval_engine_deferred."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="write:database",
            idempotency_key="key-1",
            production_ready=True,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_approval_engine_deferred_production_mode(self):
        """Test that Production-mode tasks are blocked with approval_engine_deferred."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="write:database",
            idempotency_key="key-1",
            mode=TaskMode.PRODUCTION,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_approval_engine_deferred_approval_required(self):
        """Test that approval_required tasks are blocked."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="approve:workflow",
            idempotency_key="key-1",
            approval_required=True,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "approval_engine_deferred" in result.blockers

    def test_ambiguous_target_empty_action(self):
        """Test that tasks with empty action are blocked."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="",
            idempotency_key="key-1",
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "ambiguous_target" in result.blockers

    def test_valid_task_no_blocks(self):
        """Test that valid tasks pass all checks."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="execute:test",
            idempotency_key="key-1",
            production_ready=False,
            approval_required=False,
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is False
        assert len(result.blockers) == 0

    def test_missing_authorization_check(self):
        """Test missing authorization stop condition."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="user-1",
            action="write:restricted_system",
            idempotency_key="key-1",
        )

        ownership_registry = {
            "user-1": {"owned_systems": ["write:own_system", "read:restricted_system"]},
        }

        result = StopConditionChecker.check_all_stop_conditions(task, ownership_registry=ownership_registry)

        assert result.is_blocked is True
        assert "missing_authorization" in result.blockers

    def test_read_operations_not_blocked_by_authorization(self):
        """Test that read operations don't trigger authorization block."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="user-1",
            action="read:any_system",
            idempotency_key="key-1",
        )

        ownership_registry = {"user-1": {"owned_systems": []}}

        result = StopConditionChecker.check_all_stop_conditions(task, ownership_registry=ownership_registry)

        # Should not be blocked by authorization (read operations allowed)
        assert "missing_authorization" not in result.blockers

    def test_check_approval_required_helper(self):
        """Test approval_required helper method."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            approval_required=True,
        )

        result = StopConditionChecker.check_approval_required(task)
        assert result.is_blocked is True

        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
            approval_required=False,
        )

        result2 = StopConditionChecker.check_approval_required(task2)
        assert result2.is_blocked is False

    def test_check_production_mode_helper(self):
        """Test production_ready helper method."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-1",
            production_ready=True,
        )

        result = StopConditionChecker.check_production_mode(task)
        assert result.is_blocked is True

        task2 = Task(
            id="task-2",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="test",
            idempotency_key="key-2",
            production_ready=False,
        )

        result2 = StopConditionChecker.check_production_mode(task2)
        assert result2.is_blocked is False

    def test_governed_field_risk_blocks(self):
        """Test that governed field risk blocks execution."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="write:audit_log",
            idempotency_key="key-1",
            payload={"governed_field_risk": True},
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "governed_field_risk" in result.blockers

    def test_governed_field_risk_via_writes_governed_field(self):
        """Test governed field risk check via writes_governed_field flag."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="update:record",
            idempotency_key="key-1",
            payload={"writes_governed_field": True},
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "governed_field_risk" in result.blockers

    def test_multiple_blockers(self):
        """Test that multiple blockers are collected."""
        task = Task(
            id="task-1",
            workflow_id="workflow-1",
            type="test",
            owner="system",
            action="",  # Empty action = ambiguous
            idempotency_key="key-1",
            production_ready=True,  # Production = deferred
        )

        result = StopConditionChecker.check_all_stop_conditions(task)

        assert result.is_blocked is True
        assert "ambiguous_target" in result.blockers
        assert "approval_engine_deferred" in result.blockers
        assert len(result.blockers) >= 2


class TestApprovalAwareHelpers:
    """Tests for the approval-engine-aware individual stop condition helpers."""

    @staticmethod
    def _task(task_id: str = "task-1", **overrides: object) -> Task:
        defaults = {
            "id": task_id,
            "workflow_id": "workflow-1",
            "type": "test",
            "owner": "system",
            "action": "write:governed_system",
            "idempotency_key": f"key-{task_id}",
        }
        defaults.update(overrides)
        return Task(**defaults)

    @staticmethod
    def _repo_with_decision(task: Task, decision: ApprovalDecision) -> SQLiteRepository:
        """Persist an approval request for a task at the given decision state."""
        repository = SQLiteRepository(":memory:")
        repository.create_approval_request(
            ApprovalRequest(
                id=f"approval-{task.id}",
                task_id=task.id,
                requested_by=task.owner,
                decision=ApprovalDecision.PENDING,
            )
        )
        if decision != ApprovalDecision.PENDING:
            repository.update_approval_decision(
                task_id=task.id, decision=decision, approver="approver-1"
            )
        return repository

    def test_approval_required_blocks_without_an_approval_store(self):
        """No source_of_truth_db means no approval on record, so the task stays blocked."""
        task = self._task(approval_required=True)

        result = StopConditionChecker.check_approval_required(task)

        assert result.is_blocked is True
        assert result.blockers == [StopConditionChecker.APPROVAL_ENGINE_DEFERRED]

    def test_approval_required_cleared_by_approved_decision(self):
        """An APPROVED record is the only thing that clears the block."""
        task = self._task(approval_required=True)
        repository = self._repo_with_decision(task, ApprovalDecision.APPROVED)

        result = StopConditionChecker.check_approval_required(task, source_of_truth_db=repository)

        assert result.is_blocked is False

    @pytest.mark.parametrize(
        "decision", [ApprovalDecision.PENDING, ApprovalDecision.REJECTED]
    )
    def test_approval_required_still_blocked_when_not_approved(
        self, decision: ApprovalDecision
    ):
        """A pending or rejected decision does not clear the block."""
        task = self._task(approval_required=True)
        repository = self._repo_with_decision(task, decision)

        result = StopConditionChecker.check_approval_required(task, source_of_truth_db=repository)

        assert result.is_blocked is True
        assert result.blockers == [StopConditionChecker.APPROVAL_ENGINE_DEFERRED]

    def test_production_mode_helper_blocks_production_task_mode(self):
        """TaskMode.PRODUCTION blocks even when the production_ready flag is unset."""
        task = self._task(mode=TaskMode.PRODUCTION)

        result = StopConditionChecker.check_production_mode(task)

        assert result.is_blocked is True
        assert result.blockers == [StopConditionChecker.APPROVAL_ENGINE_DEFERRED]

    def test_production_mode_cleared_by_approved_decision(self):
        """An APPROVED record clears the production block."""
        task = self._task(production_ready=True)
        repository = self._repo_with_decision(task, ApprovalDecision.APPROVED)

        result = StopConditionChecker.check_production_mode(task, source_of_truth_db=repository)

        assert result.is_blocked is False

    def test_helpers_tolerate_db_without_approval_lookup(self):
        """A source_of_truth_db predating the approval engine is treated as no approval."""

        class LegacyDB:
            def has_conflict(self, _task_id: str) -> bool:
                return False

        task = self._task(approval_required=True)

        result = StopConditionChecker.check_approval_required(task, source_of_truth_db=LegacyDB())

        assert result.is_blocked is True

    def test_ungoverned_task_is_not_blocked(self):
        """A task that needs no approval passes both helpers untouched."""
        task = self._task()

        assert StopConditionChecker.check_approval_required(task).is_blocked is False
        assert StopConditionChecker.check_production_mode(task).is_blocked is False
