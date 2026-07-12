"""Adapters for task execution."""

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.adapters.noop_adapter import NoopAdapter

__all__ = ["TaskAdapter", "NoopAdapter"]
