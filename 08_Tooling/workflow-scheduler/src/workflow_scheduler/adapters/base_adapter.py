"""Base adapter interface for task execution."""

from abc import ABC, abstractmethod
from typing import Any, Dict

from workflow_scheduler.models import Task


class TaskAdapter(ABC):
    """Abstract base class for task adapters.

    The base signature remains legacy-compatible until Phase 4G. Individual
    adapters may explicitly opt into immutable request input through the class
    capability below.
    """

    accepts_execution_request = False

    @abstractmethod
    def execute(self, task: Task) -> Dict[str, Any]:
        """Execute one task and return a supported adapter result."""
        raise NotImplementedError
