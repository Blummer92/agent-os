"""Base adapter interface for task execution."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from workflow_scheduler.models import Task


class TaskAdapter(ABC):
    """Abstract base class for task adapters."""

    @abstractmethod
    def execute(self, task: Task) -> Dict[str, Any]:
        """Execute a task.

        Args:
            task: Task to execute

        Returns:
            Dict with execution result: {"success": bool, "output": dict,
            "error": str}. On failure, adapters may also set
            "is_transient": bool (default False) to signal whether the
            failure is retryable — e.g. a network timeout is transient,
            a validation error is not. Only transient failures are
            eligible for the executor's retry path.
        """
        pass
