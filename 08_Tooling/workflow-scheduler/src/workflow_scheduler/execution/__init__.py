"""Workflow Scheduler execution package with lazy executable exports.

Keeping the package initializer free of eager executor/retry imports allows pure
submodules such as ``runtime_configuration`` to be imported without making
execution-capable machinery reachable. Existing package-level imports remain
available through lazy compatibility exports.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CLAUDE_CODE_ADAPTER_SCHEMA_VERSION",
    "ClaudeCodeAdapterError",
    "ClaudeCodeInvocation",
    "ClaudeCodeResultEvidence",
    "ClaudeCodeTerminalStatus",
    "Executor",
    "ExecutionResult",
    "HOST_LOCAL_LEASE_SCHEMA_VERSION",
    "LEASE_RECOVERY_WORKSPACE_DISPOSITIONS",
    "ContainedTerminationEvidence",
    "HostLocalLeaseAdapter",
    "HostLocalLeaseObservation",
    "HostLocalLeasePolicy",
    "OrphanedLeaseRecoveryObservation",
    "OrphanedLeaseRecoveryRequest",
    "RetryManager",
    "contained_termination_evidence",
    "build_claude_code_invocation",
    "build_execution_request_from_task",
    "is_execution_request",
    "normalize_claude_code_result",
]

_LAZY_EXPORTS = {
    "CLAUDE_CODE_ADAPTER_SCHEMA_VERSION": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "CLAUDE_CODE_ADAPTER_SCHEMA_VERSION",
    ),
    "ClaudeCodeAdapterError": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "ClaudeCodeAdapterError",
    ),
    "ClaudeCodeInvocation": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "ClaudeCodeInvocation",
    ),
    "ClaudeCodeResultEvidence": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "ClaudeCodeResultEvidence",
    ),
    "ClaudeCodeTerminalStatus": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "ClaudeCodeTerminalStatus",
    ),
    "build_claude_code_invocation": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "build_claude_code_invocation",
    ),
    "normalize_claude_code_result": (
        "workflow_scheduler.execution.claude_code_executor_adapter",
        "normalize_claude_code_result",
    ),
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
    "LEASE_RECOVERY_WORKSPACE_DISPOSITIONS": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "LEASE_RECOVERY_WORKSPACE_DISPOSITIONS",
    ),
    "OrphanedLeaseRecoveryRequest": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "OrphanedLeaseRecoveryRequest",
    ),
    "OrphanedLeaseRecoveryObservation": (
        "workflow_scheduler.execution.host_local_lease_adapter",
        "OrphanedLeaseRecoveryObservation",
    ),
    "ContainedTerminationEvidence": (
        "workflow_scheduler.execution.posix_process_adapter",
        "ContainedTerminationEvidence",
    ),
    "contained_termination_evidence": (
        "workflow_scheduler.execution.posix_process_adapter",
        "contained_termination_evidence",
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
