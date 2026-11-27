"""Standalone deterministic fixtures and crash probe for S8 deferral tests."""

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.repository import SQLiteRepository

DEFER = {"status": "approval-required", "message": "review",
         "approval_reason": "human approval required"}
SUCCESS = {"success": True, "output": {}}

# Child protocol: 77 = committed deferral, 76 = stopped before settlement,
# 75 = non-boolean success refused, 3 = repository refused, 4 = hook never ran.
COMMITTED, BEFORE, NONBOOL, REFUSED, MISSED = 77, 76, 75, 3, 4


class RecordingAdapter:
    """Report one fixed result and retain task IDs dispatched by the executor."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, task):
        self.calls.append(task.id)
        return dict(self.result)


@contextmanager
def open_cli(path, adapter=None, *, repository_type=SQLiteRepository):
    """Own one CLI connection, including when a public test seam is installed."""
    cli = WorkflowSchedulerCLI(db_path=str(path))
    repository = cli.repository
    if repository_type is not SQLiteRepository:
        repository.close()
        repository = repository_type(str(path))
        cli.repository = cli.executor.repository = cli.audit_logger.repository = repository
    if adapter is not None:
        cli.executor.adapter = adapter
    try:
        yield cli
    finally:
        repository.close()


def make_plan(tmp_path, *, dependent=False):
    """Persist a fresh plan with stable IDs in a unique per-test SQLite file."""
    plan = tmp_path / "plan.json"  # JSON is also accepted by the YAML reader.
    tasks = [{"id": "t0", "owner": "test-owner", "action": "read:fixture"}]
    if dependent:
        tasks.append({"id": "t1", "owner": "test-owner", "action": "read:fixture",
                      "depends_on": ["t0"]})
    plan.write_text(json.dumps({"workflow_id": "wf", "title": "S8", "created_by": "test",
                                "mode": "Draft", "tasks": tasks}), encoding="utf-8")
    database = tmp_path / "scheduler.sqlite"
    with open_cli(database) as cli:
        outcome = cli.create_workflow(str(plan))
    if outcome["status"] != "pass":
        raise RuntimeError(f"could not create test workflow: {outcome}")
    return database


def request_fields(request):
    """All dataclass fields as detached JSON; timestamp precision is preserved."""
    return json.loads(json.dumps(asdict(request), default=lambda item: item.isoformat()))


def crash_probe(db, receipt, mode):
    """Exit the test process at the public claimed-settlement boundary."""

    class CrashRepository(SQLiteRepository):
        def update_claimed_task(self, task, token, *, approval_request=None):
            if approval_request is None:
                return super().update_claimed_task(task, token)
            Path(receipt).write_text(json.dumps(request_fields(approval_request)), encoding="utf-8")
            if mode == "before":
                os._exit(BEFORE)
            settled = 1 if mode == "truthy" else super().update_claimed_task(
                task, token, approval_request=approval_request,
            )
            os._exit(COMMITTED if settled is True else REFUSED if settled is False else NONBOOL)

    with open_cli(db, RecordingAdapter(DEFER), repository_type=CrashRepository) as cli:
        cli.run_workflow("wf")
    return MISSED


if __name__ == "__main__":
    raise SystemExit(crash_probe(*sys.argv[1:]))
