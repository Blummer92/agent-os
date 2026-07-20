"""No-op adapter for local tests."""

from typing import Any, Dict

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import ExecutionRequest


class NoopAdapter(TaskAdapter):
    """No-op adapter that always returns success."""

    accepts_execution_request = True

    def __init__(self, log_output: bool = True):
        self.log_output = log_output
        self.execution_log: list[Dict[str, Any]] = []

    def execute(self, request: ExecutionRequest) -> Dict[str, Any]:
        result = {
            "success": True,
            "error": None,
            "output": {
                "task_id": request.task_id,
                "workflow_id": request.workflow_id,
                "owner": request.owner,
                "message": f"No-op execution of task {request.task_id}",
            },
        }
        if self.log_output:
            self.execution_log.append(
                {
                    "task_id": request.task_id,
                    "timestamp": request.created_at.isoformat(),
                    "result": result,
                }
            )
        return result

    def get_execution_log(self) -> list[Dict[str, Any]]:
        return self.execution_log
