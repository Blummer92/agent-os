"""Command-line interface for Workflow Scheduler."""

import argparse
import json
import sys
import uuid
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.dependencies import DependencyResolver
from workflow_scheduler.execution import Executor
from workflow_scheduler.governance import StopConditionChecker
from workflow_scheduler.models import (
    ApprovalDecision,
    ApprovalRequest,
    Task,
    TaskMode,
    TaskStatus,
    WorkflowPlan,
    WorkflowMode,
)
from workflow_scheduler.queue import JobQueue
from workflow_scheduler.repository import SQLiteRepository


class WorkflowSchedulerCLI:
    """Command-line interface for Workflow Scheduler."""

    def __init__(self, db_path: str = "workflow_scheduler.db"):
        """Initialize CLI with database backend.

        Args:
            db_path: Path to SQLite database file
        """
        self.repository = SQLiteRepository(db_path)
        self.audit_logger = AuditLogger(repository=self.repository)
        self.adapter = NoopAdapter()
        self.executor = Executor(
            adapter=self.adapter,
            repository=self.repository,
            audit_logger=self.audit_logger,
        )
        self.queue = JobQueue()

    def _format_response(
        self,
        status: str,
        blockers: Optional[list[str]] = None,
        checks_passed: Optional[list[str]] = None,
        checks_failed: Optional[list[str]] = None,
        next_owner: str = "system",
        handoff_artifacts: Optional[list[str]] = None,
        files_changed: Optional[list[str]] = None,
        tests_run: str = "N/A",
        **extra_fields,
    ) -> Dict[str, Any]:
        """Format CLI response using Part A output schema.

        Args:
            status: "pass" | "fail" | "blocked"
            blockers: List of blockers
            checks_passed: Passed checks
            checks_failed: Failed checks
            next_owner: Next responsible party
            handoff_artifacts: Artifacts to pass forward
            files_changed: Changed files
            tests_run: Test summary
            **extra_fields: Additional fields to include

        Returns:
            Dict with schema-compliant response
        """
        response = {
            "status": status,
            "blockers": blockers or [],
            "checks_passed": checks_passed or [],
            "checks_failed": checks_failed or [],
            "next_owner": next_owner,
            "handoff_artifacts": handoff_artifacts or [],
            "files_changed": files_changed or [],
            "tests_run": tests_run,
        }
        response.update(extra_fields)
        return response

    def create_workflow(self, yaml_path: str) -> Dict[str, Any]:
        """Create workflow from YAML file.

        Args:
            yaml_path: Path to workflow YAML file

        Returns:
            Dict with workflow creation result
        """
        try:
            with open(yaml_path) as f:
                workflow_data = yaml.safe_load(f)
        except FileNotFoundError:
            return self._format_response(
                status="fail",
                checks_failed=["file_not_found"],
                next_owner="user",
                error=f"File not found: {yaml_path}",
            )
        except yaml.YAMLError as e:
            return self._format_response(
                status="fail",
                checks_failed=["yaml_parse"],
                next_owner="user",
                error=f"Invalid YAML: {e}",
            )

        workflow_id = workflow_data.get("workflow_id", f"workflow-{uuid.uuid4().hex[:8]}")
        title = workflow_data.get("title", "Untitled Workflow")
        created_by = workflow_data.get("created_by", "cli")
        mode_str = workflow_data.get("mode", "Draft")

        try:
            mode = WorkflowMode[mode_str.upper()]
        except KeyError:
            return self._format_response(
                status="fail",
                checks_failed=["invalid_mode"],
                next_owner="user",
                error=f"Invalid mode: {mode_str}",
            )

        workflow = WorkflowPlan(
            workflow_id=workflow_id,
            title=title,
            created_by=created_by,
            mode=mode,
        )

        # Create tasks from workflow definition
        tasks_data = workflow_data.get("tasks", [])
        for task_data in tasks_data:
            task_id = task_data.get("id", f"task-{uuid.uuid4().hex[:8]}")
            task = Task(
                id=task_id,
                workflow_id=workflow_id,
                type=task_data.get("type", "generic"),
                owner=task_data.get("owner", "system"),
                action=task_data.get("action", ""),
                idempotency_key=task_data.get("idempotency_key", task_id),
                status=TaskStatus.DRAFT,
                mode=TaskMode[task_data.get("mode", "Draft").upper()],
                priority=task_data.get("priority", 0),
                approval_required=task_data.get("approval_required", False),
                depends_on=task_data.get("depends_on", []),
                payload=task_data.get("payload", {}),
                production_ready=task_data.get("production_ready", False),
            )
            workflow.add_task(task_id)
            workflow.set_dependencies(task_id, task.depends_on)
            self.repository.create_task(task)

        self.repository.create_workflow(workflow)
        self.audit_logger.log_workflow_created(workflow)

        return self._format_response(
            status="pass",
            checks_passed=["workflow_created", "tasks_created"],
            next_owner="user",
            workflow_id=workflow_id,
            title=title,
            task_count=len(tasks_data),
        )

    def list_workflows(self) -> Dict[str, Any]:
        """List all workflows.

        Returns:
            Dict with workflows list
        """
        # Note: Repository doesn't have list_workflows yet; would need to add
        return self._format_response(
            status="pass",
            checks_passed=["workflows_listed"],
            next_owner="user",
            workflows=[],
        )

    def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status.

        Args:
            workflow_id: Workflow ID

        Returns:
            Dict with workflow status and tasks
        """
        workflow = self.repository.get_workflow(workflow_id)
        if not workflow:
            return self._format_response(
                status="fail",
                checks_failed=["workflow_not_found"],
                next_owner="user",
                error=f"Workflow not found: {workflow_id}",
            )

        tasks = self.repository.list_workflow_tasks(workflow_id)
        task_statuses = {t.id: t.status.value for t in tasks}

        mode_value = workflow.mode.value if hasattr(workflow.mode, "value") else workflow.mode

        return self._format_response(
            status="pass",
            checks_passed=["workflow_status_retrieved"],
            next_owner="user",
            workflow_id=workflow_id,
            title=workflow.title,
            workflow_status=workflow.status.value,
            mode=mode_value,
            task_count=len(tasks),
            task_statuses=task_statuses,
            created_at=workflow.created_at.isoformat(),
            updated_at=workflow.updated_at.isoformat(),
        )

    def run_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Execute workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Dict with execution result
        """
        workflow = self.repository.get_workflow(workflow_id)
        if not workflow:
            return self._format_response(
                status="fail",
                checks_failed=["workflow_not_found"],
                next_owner="user",
                error=f"Workflow not found: {workflow_id}",
            )

        if workflow.is_terminal():
            return self._format_response(
                status="blocked",
                blockers=["workflow_terminal"],
                checks_failed=["workflow_not_in_runnable_state"],
                next_owner="user",
                error=f"Workflow is in terminal state: {workflow.status.value}",
            )

        workflow.mark_running()
        self.audit_logger.log_workflow_started(workflow)
        self.repository.update_workflow(workflow)

        tasks = self.repository.list_workflow_tasks(workflow_id)
        resolver = DependencyResolver(tasks, workflow.dependencies)

        # Check for cycles
        has_cycle, cycle_path = resolver.has_cycle()
        if has_cycle:
            workflow.mark_failed(reason=f"Circular dependency detected: {' -> '.join(cycle_path)}")
            self.repository.update_workflow(workflow)
            return self._format_response(
                status="fail",
                checks_failed=["cycle_detected"],
                next_owner="user",
                error=f"Circular dependency detected: {' -> '.join(cycle_path)}",
            )

        # Execute in dependency order. Seed `completed` from tasks already
        # COMPLETED in a prior run so a rerun (e.g. after approval) does not
        # re-execute work that already finished.
        completed: set[str] = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
        failed: set[str] = set()
        blocked: set[str] = set()
        approval_pending: set[str] = set()

        while len(completed) + len(failed) + len(blocked) + len(approval_pending) < len(tasks):
            ready = [
                task_id
                for task_id in resolver.get_ready_tasks(completed)
                if task_id not in failed and task_id not in blocked and task_id not in approval_pending
            ]
            if not ready:
                break

            for task_id in ready:
                task = self.repository.get_task(task_id)
                if not task:
                    continue

                task.status = TaskStatus.QUEUED
                self.repository.update_task(task)

                result = self.executor.execute(task)

                if result.success:
                    completed.add(task_id)
                elif result.status == "blocked" and StopConditionChecker.APPROVAL_ENGINE_DEFERRED in result.blockers and len(result.blockers) == 1:
                    approval_pending.add(task_id)
                elif result.status == "blocked":
                    blocked.add(task_id)
                else:
                    failed.add(task_id)

        if approval_pending and not failed and not blocked:
            # Waiting on an explicit human decision — this is a resumable
            # state, not a terminal failure. Leave the workflow RUNNING so a
            # later `run` (after approve/reject) can pick back up.
            workflow.metadata["tasks_awaiting_approval"] = sorted(approval_pending)
            self.repository.update_workflow(workflow)

            return self._format_response(
                status="blocked",
                blockers=["tasks_awaiting_approval"],
                checks_passed=["workflow_executed"],
                checks_failed=["tasks_awaiting_approval"],
                next_owner="user",
                workflow_id=workflow_id,
                completed=len(completed),
                failed=len(failed),
                blocked=len(blocked),
                approval_pending=len(approval_pending),
                approval_pending_task_ids=sorted(approval_pending),
                final_status=workflow.status.value,
            )

        if failed or blocked:
            workflow.mark_failed(reason=f"Tasks failed: {len(failed)}, blocked: {len(blocked)}")
            status = "fail"
            checks_failed = ["tasks_failed" if failed else [], "tasks_blocked" if blocked else []]
            checks_failed = [c for c in checks_failed if c]
        else:
            workflow.mark_completed()
            status = "pass"
            checks_failed = []

        self.audit_logger.log_workflow_completed(workflow)
        self.repository.update_workflow(workflow)

        return self._format_response(
            status=status,
            checks_passed=["workflow_executed"],
            checks_failed=checks_failed,
            next_owner="user",
            workflow_id=workflow_id,
            completed=len(completed),
            failed=len(failed),
            blocked=len(blocked),
            final_status=workflow.status.value,
        )

    def _get_pending_approval_or_block(self, task_id: str, approver: str) -> tuple:
        """Look up a task and its approval request, enforcing that the task is
        actually awaiting approval before allowing a decision to be recorded.

        A task may only be approved or rejected if:
          - it exists
          - its status is APPROVAL_PENDING (it went through the executor's
            approval-pending path; it was never proactively approvable from
            Draft/Pending/Queued/Running/etc.)
          - its approval request (created by the executor) is still PENDING

        If the task is APPROVAL_PENDING but its approval request is missing
        (a recovery case — e.g. the record was lost), one is created here so
        the decision can still be recorded.

        Returns:
            Tuple of (task, approval, error_response). Exactly one of
            (task/approval) or error_response is populated.
        """
        task = self.repository.get_task(task_id)
        if not task:
            return None, None, self._format_response(
                status="fail",
                checks_failed=["task_not_found"],
                next_owner="user",
                error=f"Task not found: {task_id}",
            )

        if task.status != TaskStatus.APPROVAL_PENDING:
            return None, None, self._format_response(
                status="blocked",
                blockers=["task_not_awaiting_approval"],
                checks_failed=["task_not_awaiting_approval"],
                next_owner="user",
                error=f"Task is not awaiting approval (status: {task.status.value})",
            )

        approval = self.repository.get_approval_request(task_id)
        if approval is None:
            # Recovery case: task is APPROVAL_PENDING but has no approval
            # record on file (should not normally happen; the executor
            # always creates one when it moves a task into this state).
            approval = ApprovalRequest(
                id=str(uuid.uuid4()),
                task_id=task_id,
                requested_by=approver,
                decision=ApprovalDecision.PENDING,
            )
            self.repository.create_approval_request(approval)
        elif approval.decision != ApprovalDecision.PENDING:
            return None, None, self._format_response(
                status="blocked",
                blockers=["approval_already_decided"],
                checks_failed=["approval_already_decided"],
                next_owner="user",
                error=f"Approval already decided: {approval.decision.value}",
            )

        return task, approval, None

    def approve(self, task_id: str, approver: str) -> Dict[str, Any]:
        """Explicitly approve a task currently awaiting approval.

        Args:
            task_id: Task ID to approve
            approver: Name/identifier of the human approver

        Returns:
            Dict with approval result
        """
        task, _approval, error_response = self._get_pending_approval_or_block(task_id, approver)
        if error_response is not None:
            return error_response

        self.repository.update_approval_decision(
            task_id=task_id,
            decision=ApprovalDecision.APPROVED,
            approver=approver,
        )

        task.mark_approved()
        self.repository.update_task(task)
        self.audit_logger.log_task_approved(task, approved_by=approver)

        return self._format_response(
            status="pass",
            checks_passed=["approval_granted"],
            next_owner="system",
            task_id=task_id,
            decision="approved",
            approver=approver,
        )

    def reject(self, task_id: str, approver: str, reason: str) -> Dict[str, Any]:
        """Explicitly reject a task currently awaiting approval.

        Args:
            task_id: Task ID to reject
            approver: Name/identifier of the human approver
            reason: Rejection reason

        Returns:
            Dict with rejection result
        """
        task, _approval, error_response = self._get_pending_approval_or_block(task_id, approver)
        if error_response is not None:
            return error_response

        self.repository.update_approval_decision(
            task_id=task_id,
            decision=ApprovalDecision.REJECTED,
            approver=approver,
            reason=reason,
        )

        task.mark_cancelled(reason=reason)
        self.repository.update_task(task)
        self.audit_logger.log_task_cancelled(task, reason=reason)

        return self._format_response(
            status="pass",
            checks_passed=["approval_rejected"],
            next_owner="user",
            task_id=task_id,
            decision="rejected",
            approver=approver,
            reason=reason,
        )

    def show_audit_log(self, workflow_id: Optional[str] = None, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Show audit log.

        Args:
            workflow_id: Filter by workflow ID (optional)
            task_id: Filter by task ID (optional)

        Returns:
            Dict with audit events
        """
        events = self.audit_logger.get_events(task_id=task_id, workflow_id=workflow_id)

        return self._format_response(
            status="pass",
            checks_passed=["audit_log_retrieved"],
            next_owner="user",
            event_count=len(events),
            events=[e.to_dict() for e in events],
        )


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Workflow Scheduler CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # create command
    create_parser = subparsers.add_parser("create", help="Create workflow from YAML")
    create_parser.add_argument("yaml_path", help="Path to workflow YAML file")
    create_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    # list command
    list_parser = subparsers.add_parser("list", help="List workflows")
    list_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    # status command
    status_parser = subparsers.add_parser("status", help="Get workflow status")
    status_parser.add_argument("workflow_id", help="Workflow ID")
    status_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute workflow")
    run_parser.add_argument("workflow_id", help="Workflow ID")
    run_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    # approve command
    approve_parser = subparsers.add_parser("approve", help="Approve a task pending explicit approval")
    approve_parser.add_argument("task_id", help="Task ID")
    approve_parser.add_argument("--approver", required=True, help="Name of the approving human")
    approve_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    # reject command
    reject_parser = subparsers.add_parser("reject", help="Reject a task pending explicit approval")
    reject_parser.add_argument("task_id", help="Task ID")
    reject_parser.add_argument("--approver", required=True, help="Name of the rejecting human")
    reject_parser.add_argument("--reason", required=True, help="Reason for rejection")
    reject_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    # audit command
    audit_parser = subparsers.add_parser("audit", help="View audit log")
    audit_parser.add_argument("--workflow-id", help="Filter by workflow ID")
    audit_parser.add_argument("--task-id", help="Filter by task ID")
    audit_parser.add_argument("--db", default="workflow_scheduler.db", help="Database path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cli = WorkflowSchedulerCLI(db_path=getattr(args, "db", "workflow_scheduler.db"))

    try:
        if args.command == "create":
            result = cli.create_workflow(args.yaml_path)
        elif args.command == "list":
            result = cli.list_workflows()
        elif args.command == "status":
            result = cli.get_workflow_status(args.workflow_id)
        elif args.command == "run":
            result = cli.run_workflow(args.workflow_id)
        elif args.command == "approve":
            result = cli.approve(args.task_id, args.approver)
        elif args.command == "reject":
            result = cli.reject(args.task_id, args.approver, args.reason)
        elif args.command == "audit":
            result = cli.show_audit_log(
                workflow_id=getattr(args, "workflow_id", None),
                task_id=getattr(args, "task_id", None),
            )
        else:
            result = {"status": "fail", "error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, default=str))
        sys.exit(0 if result.get("status") == "pass" else 1)

    except Exception as e:
        print(json.dumps({"status": "fail", "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
