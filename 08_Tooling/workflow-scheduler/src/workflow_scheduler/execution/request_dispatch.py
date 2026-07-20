"""Compatibility dispatch for adapters that opt into ExecutionRequest."""

from __future__ import annotations

import uuid
from typing import Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.audit import AuditLogger
from workflow_scheduler.execution.executor import Executor as LifecycleExecutor
from workflow_scheduler.execution.request_compat import build_execution_request_from_task
from workflow_scheduler.models import Task
from workflow_scheduler.repository import SQLiteRepository


class _ExecutionRequestBridge(TaskAdapter):
    """Translate legacy lifecycle input through the approved pure helper."""

    def __init__(self, adapter: TaskAdapter, run_id: str):
        self._adapter = adapter
        self._run_id = run_id

    def execute(self, task: Task):
        request = build_execution_request_from_task(
            task,
            execution_id=str(uuid.uuid4()),
            run_id=self._run_id,
        )
        return self._adapter.execute(request)

    def __getattr__(self, name: str):
        return getattr(self._adapter, name)


class Executor(LifecycleExecutor):
    """Lifecycle executor with explicit request-contract opt-in dispatch."""

    def __init__(
        self,
        adapter: TaskAdapter,
        repository: SQLiteRepository,
        audit_logger: AuditLogger,
        lease_timeout_seconds: int = 300,
        max_workers: int = 1,
        run_id: Optional[str] = None,
    ):
        self.run_id = run_id or str(uuid.uuid4())
        self.source_adapter = adapter
        selected_adapter = (
            _ExecutionRequestBridge(adapter, self.run_id)
            if adapter.accepts_execution_request
            else adapter
        )
        super().__init__(
            adapter=selected_adapter,
            repository=repository,
            audit_logger=audit_logger,
            lease_timeout_seconds=lease_timeout_seconds,
            max_workers=max_workers,
        )
