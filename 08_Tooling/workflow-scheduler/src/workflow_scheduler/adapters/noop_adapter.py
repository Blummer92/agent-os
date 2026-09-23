"""No-op adapter for local tests."""

from typing import Any, Dict

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import ExecutionRequest, Task


class NoopAdapter(TaskAdapter):
    """No-op adapter that accepts both migration-phase input shapes."""

    accepts_execution_request = True

    def __init__(self, log_output: bool = True):
        self.log_output = log_output
        self.execution_log: list[Dict[str, Any]] = []

    def execute(self, value: Task | ExecutionRequest) -> Dict[str, Any]:
        if isinstance(value, ExecutionRequest):
            task_id = value.task_id
            workflow_id = value.workflow_id
            owner = value.owner
            action = None
            idempotency_key = value.idempotency_key
            timestamp = value.created_at.isoformat()
        else:
            task_id = value.id
            workflow_id = value.workflow_id
            owner = value.owner
            action = value.action
            idempotency_key = value.idempotency_key
            timestamp = value.updated_at.isoformat()

        output = {
            "task_id": task_id,
            "workflow_id": workflow_id,
            "owner": owner,
            "idempotency_key": idempotency_key,
            "message": f"No-op execution of task {task_id}",
        }
        if action is not None:
            output["action"] = action

        result = {"success": True, "error": None, "output": output}
        if self.log_output:
            self.execution_log.append(
                {"task_id": task_id, "timestamp": timestamp, "result": result}
            )
        return result

    def get_execution_log(self) -> list[Dict[str, Any]]:
        return self.execution_log
