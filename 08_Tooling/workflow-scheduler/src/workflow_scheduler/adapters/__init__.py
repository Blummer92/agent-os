"""Adapters for task execution."""

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.adapters.fake_adapters import (
    FakeFailureAdapter,
    FakeMalformedReturnAdapter,
    FakeNeverCalledAdapter,
    FakeRaisingAdapter,
    FakeRetryableAdapter,
    FakeSlowAdapter,
    FakeSuccessAdapter,
)
from workflow_scheduler.adapters.noop_adapter import NoopAdapter
from workflow_scheduler.adapters.registry import available_adapters, resolve_adapter

__all__ = [
    "TaskAdapter",
    "NoopAdapter",
    "FakeSuccessAdapter",
    "FakeFailureAdapter",
    "FakeRetryableAdapter",
    "FakeNeverCalledAdapter",
    "FakeSlowAdapter",
    "FakeMalformedReturnAdapter",
    "FakeRaisingAdapter",
    "resolve_adapter",
    "available_adapters",
]
