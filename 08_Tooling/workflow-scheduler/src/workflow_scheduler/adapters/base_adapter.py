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
            Dict with execution result (success, output, error)
        """
        pass
