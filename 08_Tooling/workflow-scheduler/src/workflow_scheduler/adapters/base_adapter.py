"""Base adapter interface for task execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from workflow_scheduler.models import ExecutionRequest, Task

AdapterInput = Task | ExecutionRequest


class TaskAdapter(ABC):
    """Abstract base class for task adapters.

    Adapters receive legacy ``Task`` input unless they explicitly opt into the
    immutable request contract by setting ``accepts_execution_request``.
    """

    accepts_execution_request = False

    @abstractmethod
    def execute(self, task: AdapterInput) -> Dict[str, Any]:
        """Execute one adapter request.

        Args:
            task: Legacy ``Task`` input or an opted-in ``ExecutionRequest``.

        Returns:
            Dict with execution result: {"success": bool, "output": dict,
            "error": str}. On failure, adapters may also set
            "is_transient": bool (default False) to signal whether the
            failure is retryable. Only transient failures are eligible for the
            executor's retry path.
        """
        raise NotImplementedError
