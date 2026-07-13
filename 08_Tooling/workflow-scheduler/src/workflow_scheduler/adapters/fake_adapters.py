"""Local-only fake adapters for testing the scheduler's execution paths.

These are test doubles, not real integrations -- no external system is
contacted by anything in this module. See the adapter registry
(registry.py) for how they're named/resolved, and
docs/ADAPTER_CONTRACT_FUTURE.md for the (not yet enforced) contract these
are expected to keep conforming to as it's formalized.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task


class FakeSuccessAdapter(TaskAdapter):
    """Always succeeds."""

    def execute(self, task: Task) -> Dict[str, Any]:
        return {
            "success": True,
            "error": None,
            "output": {"task_id": task.id, "message": "fake success"},
        }


class FakeFailureAdapter(TaskAdapter):
    """Always fails with a permanent (non-retryable) error."""

    def execute(self, task: Task) -> Dict[str, Any]:
        return {
            "success": False,
            "error": "fake permanent failure",
            "is_transient": False,
        }


class FakeRetryableAdapter(TaskAdapter):
    """Always fails with a transient (retryable) error."""

    def execute(self, task: Task) -> Dict[str, Any]:
        return {
            "success": False,
            "error": "fake transient failure",
            "is_transient": True,
        }


class FakeNeverCalledAdapter(TaskAdapter):
    """Fails the test if execute() is ever called.

    Approval-required and governance-blocked tasks are intercepted by
    StopConditionChecker before the executor ever reaches the adapter --
    there is no adapter-level "approval required" or "blocked" return
    value to simulate. This adapter proves that interception actually
    happens: pair it with a task configured to trigger the stop condition
    under test (approval_required=True, production_ready=True, or an
    empty action for ambiguous_target).
    """

    def execute(self, task: Task) -> Dict[str, Any]:
        raise AssertionError(
            f"FakeNeverCalledAdapter.execute() was called for task {task.id!r} -- "
            "a governance/approval stop condition should have intercepted this "
            "task before the adapter was ever reached."
        )


class FakeSlowAdapter(TaskAdapter):
    """Succeeds after a short delay; records concurrent in-flight count.

    Used to prove Executor.execute_many() actually overlaps executions
    when max_workers > 1, not just that it accepts the parameter.
    """

    def __init__(self, hold_seconds: float = 0.05):
        self.hold_seconds = hold_seconds
        self._state_lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self.executed_task_ids: List[str] = []

    def execute(self, task: Task) -> Dict[str, Any]:
        with self._state_lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self.hold_seconds)
            with self._state_lock:
                self.executed_task_ids.append(task.id)
            return {"success": True, "error": None, "output": {"task_id": task.id}}
        finally:
            with self._state_lock:
                self._in_flight -= 1


class FakeMalformedReturnAdapter(TaskAdapter):
    """Returns something that is not a valid adapter result, per what the
    caller configures. Used to test the executor's adapter-result
    validation without needing a real broken adapter."""

    def __init__(self, malformed_value: Any = "not-a-dict"):
        self.malformed_value = malformed_value

    def execute(self, task: Task) -> Any:
        return self.malformed_value


class FakeRaisingAdapter(TaskAdapter):
    """Raises instead of returning, to test that an adapter exception is
    treated as a contract violation (controlled failure) rather than
    propagating and crashing the scheduler loop."""

    def __init__(self, exception: Optional[Exception] = None):
        self.exception = exception or RuntimeError("fake adapter blew up")

    def execute(self, task: Task) -> Dict[str, Any]:
        raise self.exception


class FakeContractAdapter(TaskAdapter):
    """Reference example of an adapter opting into the Phase 3D
    five-state result contract (status/message, from
    docs/ADAPTER_CONTRACT_FUTURE.md) instead of the original success/
    error/is_transient shape every other adapter in this file uses.
    Not registered in the adapter registry -- this class exists purely
    to document and test the shape, not as a selectable local adapter.

    Configure `status` to one of success/failure/retryable/blocked/
    approval-required; the conditional field each status requires
    (retry_after/blocked_reason/approval_reason) defaults to a fake
    value but can be overridden.
    """

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
