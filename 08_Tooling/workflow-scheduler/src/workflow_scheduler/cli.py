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
from workflow_scheduler.models import Task, TaskMode, TaskStatus, WorkflowPlan, WorkflowMode
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
            return {"success": False, "error": f"File not found: {yaml_path}"}
        except yaml.YAMLError as e:
            return {"success": False, "error": f"Invalid YAML: {e}"}

        workflow_id = workflow_data.get("workflow_id", f"workflow-{uuid.uuid4().hex[:8]}")
        title = workflow_data.get("title", "Untitled Workflow")
        created_by = workflow_data.get("created_by", "cli")
        mode_str = workflow_data.get("mode", "Draft")

        try:
            mode = WorkflowMode[mode_str.upper()]
        except KeyError:
            return {"success": False, "error": f"Invalid mode: {mode_str}"}

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

        return {
            "success": True,
            "workflow_id": workflow_id,
            "title": title,
            "task_count": len(tasks_data),
        }

    def list_workflows(self) -> Dict[str, Any]:
        """List all workflows.

        Returns:
            Dict with workflows list
        """
        # Note: Repository doesn't have list_workflows yet; would need to add
        return {"success": True, "workflows": []}

    def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status.

        Args:
            workflow_id: Workflow ID

        Returns:
            Dict with workflow status and tasks
        """
        workflow = self.repository.get_workflow(workflow_id)
        if not workflow:
            return {"success": False, "error": f"Workflow not found: {workflow_id}"}

        tasks = self.repository.list_workflow_tasks(workflow_id)
        task_statuses = {t.id: t.status.value for t in tasks}

        mode_value = workflow.mode.value if hasattr(workflow.mode, "value") else workflow.mode

        return {
            "success": True,
            "workflow_id": workflow_id,
            "title": workflow.title,
            "status": workflow.status.value,
            "mode": mode_value,
            "task_count": len(tasks),
            "task_statuses": task_statuses,
            "created_at": workflow.created_at.isoformat(),
            "updated_at": workflow.updated_at.isoformat(),
        }

    def run_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Execute workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Dict with execution result
        """
        workflow = self.repository.get_workflow(workflow_id)
        if not workflow:
            return {"success": False, "error": f"Workflow not found: {workflow_id}"}

        if workflow.is_terminal():
            return {"success": False, "error": f"Workflow is in terminal state: {workflow.status.value}"}

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
            return {
                "success": False,
                "error": f"Circular dependency detected: {' -> '.join(cycle_path)}",
            }

        # Execute in dependency order
        completed: set[str] = set()
        failed: set[str] = set()
        blocked: set[str] = set()

        while len(completed) + len(failed) + len(blocked) < len(tasks):
            ready = resolver.get_ready_tasks(completed)
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
                elif result.status == "blocked":
                    blocked.add(task_id)
                else:
                    failed.add(task_id)

        if failed or blocked:
            workflow.mark_failed(reason=f"Tasks failed: {len(failed)}, blocked: {len(blocked)}")
        else:
            workflow.mark_completed()

        self.audit_logger.log_workflow_completed(workflow)
        self.repository.update_workflow(workflow)

        return {
            "success": len(failed) == 0 and len(blocked) == 0,
            "workflow_id": workflow_id,
            "completed": len(completed),
            "failed": len(failed),
            "blocked": len(blocked),
            "final_status": workflow.status.value,
        }

    def show_audit_log(self, workflow_id: Optional[str] = None, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Show audit log.

        Args:
            workflow_id: Filter by workflow ID (optional)
            task_id: Filter by task ID (optional)

        Returns:
            Dict with audit events
        """
        events = self.audit_logger.get_events(task_id=task_id, workflow_id=workflow_id)

        return {
            "success": True,
            "event_count": len(events),
            "events": [e.to_dict() for e in events],
        }


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
        elif args.command == "audit":
            result = cli.show_audit_log(
                workflow_id=getattr(args, "workflow_id", None),
                task_id=getattr(args, "task_id", None),
            )
        else:
            result = {"success": False, "error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2, default=str))
        sys.exit(0 if result.get("success", False) else 1)

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
