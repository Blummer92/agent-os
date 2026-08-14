"""Workflow Scheduler execution package with lazy executable exports.

Keeping the package initializer free of eager executor/retry imports allows pure
submodules such as ``runtime_configuration`` to be imported without making
execution-capable machinery reachable. Existing package-level imports remain
available through lazy compatibility exports.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "Executor",
    "ExecutionResult",
    "HOST_LOCAL_LEASE_SCHEMA_VERSION",
    "HostLocalLeaseAdapter",
    "HostLocalLeaseObservation",
    "HostLocalLeasePolicy",
    "RetryManager",
    "build_execution_request_from_task",
    "is_execution_request",
]

_LAZY_EXPORTS = {
    "ExecutionResult": (
        "workflow_scheduler.execution.executor",
        "ExecutionResult",
    ),
    "build_execution_request_from_task": (
        "workflow_scheduler.execution.request_compat",
        "build_execution_request_from_task",
    ),
    "is_execution_request": (
        "workflow_scheduler.execution.request_compat",
        "is_execution_request",
    ),
    "Executor": (
        "workflow_scheduler.execution.request_dispatch",
        "Executor",
    ),
    "RetryManager": (
        "workflow_scheduler.execution.retry_manager",
        "RetryManager",
    ),
    "HOST_LOCAL_LEASE_SCHEMA_VERSION": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "HOST_LOCAL_LEASE_SCHEMA_VERSION",
    ),
    "HostLocalLeaseAdapter": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "HostLocalLeaseAdapter",
    ),
    "HostLocalLeaseObservation": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "HostLocalLeaseObservation",
    ),
    "HostLocalLeasePolicy": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "HostLocalLeasePolicy",
    ),
}


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
