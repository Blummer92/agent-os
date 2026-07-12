"""No-op adapter for testing task execution."""

from typing import Any, Dict

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task


class NoopAdapter(TaskAdapter):
    """No-op adapter that always succeeds and logs task execution."""

    def __init__(self, log_output: bool = True):
        """Initialize no-op adapter.

        Args:
            log_output: Whether to log execution details
        """
        self.log_output = log_output
        self.execution_log: list[Dict[str, Any]] = []

    def execute(self, task: Task) -> Dict[str, Any]:
        """Execute a task (no-op: always succeeds).

        Args:
            task: Task to execute

        Returns:
            Dict with success=True and echo of task details
        """
        result = {
            "success": True,
            "error": None,
            "output": {
                "task_id": task.id,
                "action": task.action,
                "message": f"No-op execution of {task.type} task {task.id}",
                "idempotency_key": task.idempotency_key,
            },
        }

        if self.log_output:
            self.execution_log.append(
                {
                    "task_id": task.id,
                    "action": task.action,
                    "timestamp": task.updated_at.isoformat(),
                    "result": result,
                }
            )

        return result

    def get_execution_log(self) -> list[Dict[str, Any]]:
        """Get log of all executions."""
        return self.execution_log
