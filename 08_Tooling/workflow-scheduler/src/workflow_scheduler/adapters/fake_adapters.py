"""Local-only fake adapters for testing scheduler execution paths."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import ExecutionRequest, Task

AdapterInput = Task | ExecutionRequest


def _task_id(value: AdapterInput) -> str:
    return value.task_id if isinstance(value, ExecutionRequest) else value.id


class FakeSuccessAdapter(TaskAdapter):
    """Always succeeds."""

    accepts_execution_request = True

    def execute(self, value: AdapterInput) -> Dict[str, Any]:
        return {
            "success": True,
            "error": None,
            "output": {"task_id": _task_id(value), "message": "fake success"},
        }


class FakeFailureAdapter(TaskAdapter):
    """Always fails with a permanent error."""

    accepts_execution_request = True

    def execute(self, value: AdapterInput) -> Dict[str, Any]:
        return {
            "success": False,
            "error": "fake permanent failure",
            "is_transient": False,
        }


class FakeRetryableAdapter(TaskAdapter):
    """Always fails with a transient error."""

    accepts_execution_request = True

    def execute(self, value: AdapterInput) -> Dict[str, Any]:
        return {
            "success": False,
            "error": "fake transient failure",
            "is_transient": True,
        }


class FakeNeverCalledAdapter(TaskAdapter):
    """Fails the test if reached after a scheduler stop condition."""

    accepts_execution_request = True

    def execute(self, value: AdapterInput) -> Dict[str, Any]:
        raise AssertionError(
            f"FakeNeverCalledAdapter.execute() was called for task {_task_id(value)!r}"
        )


class FakeSlowAdapter(TaskAdapter):
    """Succeeds after a short delay and records concurrent calls."""

    accepts_execution_request = True

    def __init__(self, hold_seconds: float = 0.05):
        self.hold_seconds = hold_seconds
        self._state_lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self.executed_task_ids: List[str] = []

    def execute(self, value: AdapterInput) -> Dict[str, Any]:
        task_id = _task_id(value)
        with self._state_lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self.hold_seconds)
            with self._state_lock:
                self.executed_task_ids.append(task_id)
            return {"success": True, "error": None, "output": {"task_id": task_id}}
        finally:
            with self._state_lock:
                self._in_flight -= 1


class FakeMalformedReturnAdapter(TaskAdapter):
    """Returns a caller-configured malformed value."""

    accepts_execution_request = True

    def __init__(self, malformed_value: Any = "not-a-dict"):
        self.malformed_value = malformed_value

    def execute(self, value: AdapterInput) -> Any:
        return self.malformed_value


class FakeRaisingAdapter(TaskAdapter):
    """Raises a caller-configured exception."""

    accepts_execution_request = True

    def __init__(self, exception: Optional[Exception] = None):
        self.exception = exception or RuntimeError("fake adapter blew up")

    def execute(self, value: AdapterInput) -> Dict[str, Any]:
        raise self.exception


class FakeContractAdapter(TaskAdapter):
    """Legacy-input reference adapter for the five-state result contract."""

    def __init__(
        self,
        status: str = "success",
        message: str = "fake contract result",
        output: Optional[Dict[str, Any]] = None,
        retry_after: float = 5.0,
        blocked_reason: str = "fake adapter-originated block",
        approval_reason: str = "fake adapter-originated approval requirement",
    ):
        self.status = status
        self.message = message
        self.output = output
        self.retry_after = retry_after
        self.blocked_reason = blocked_reason
        self.approval_reason = approval_reason

    def execute(self, task: Task) -> Dict[str, Any]:
        result: Dict[str, Any] = {"status": self.status, "message": self.message}
        if self.status == "success":
            result["output"] = self.output or {"task_id": task.id}
        elif self.status == "retryable":
            result["retry_after"] = self.retry_after
        elif self.status == "blocked":
            result["blocked_reason"] = self.blocked_reason
        elif self.status == "approval-required":
            result["approval_reason"] = self.approval_reason
        return result
