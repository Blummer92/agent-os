"""Regression proof for stale writes and competing workflow runners."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import yaml

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import TaskStatus, WorkflowStatus


def setup_workflow(tmp_path, name="race-wf"):
    db = str(tmp_path / "state.sqlite")
    cli = WorkflowSchedulerCLI(db_path=db)
    spec = {
        "workflow_id": name,
        "title": "Workflow claim proof",
        "created_by": "test",
        "mode": "Draft",
        "tasks": [{
            "id": "one-task",
            "type": "test",
            "owner": "system",
            "action": "read:probe",
            "idempotency_key": "one-task",
        }],
    }
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(spec))
    assert cli.create_workflow(str(path))["status"] == "pass"
    return cli, db


def test_two_runners_preserve_completed_workflow(tmp_path):
    first, db = setup_workflow(tmp_path)
    second = WorkflowSchedulerCLI(db_path=db)
    barrier = Barrier(2)

    for runner in (first, second):
        original = runner.repository.try_claim_execution

        def synchronize(task_id, original=original):
            barrier.wait(timeout=10)
            return original(task_id)

        runner.repository.try_claim_execution = synchronize

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first.run_workflow, "race-wf")
        b = pool.submit(second.run_workflow, "race-wf")
        results = [a.result(timeout=20), b.result(timeout=20)]

    executions = len(first.adapter.execution_log) + len(second.adapter.execution_log)
    assert executions == 1
    assert first.repository.get_task("one-task").status == TaskStatus.COMPLETED
    assert first.repository.get_workflow("race-wf").status == WorkflowStatus.COMPLETED
    assert all(r["status"] in ("pass", "blocked") for r in results)


def test_stale_snapshot_cannot_requeue_completed_task(tmp_path):
    cli, _ = setup_workflow(tmp_path)
    stale = cli.repository.get_task("one-task")
    assert cli.run_workflow("race-wf")["status"] == "pass"
    stale.status = TaskStatus.QUEUED
    cli.repository.update_task(stale)
    assert cli.repository.get_task("one-task").status == TaskStatus.COMPLETED


def test_stale_workflow_cannot_overwrite_completion(tmp_path):
    cli, _ = setup_workflow(tmp_path)
    stale = cli.repository.get_workflow("race-wf")
    assert cli.run_workflow("race-wf")["status"] == "pass"
    stale.mark_failed(reason="stale runner")
    cli.repository.update_workflow(stale)
    assert cli.repository.get_workflow("race-wf").status == WorkflowStatus.COMPLETED
