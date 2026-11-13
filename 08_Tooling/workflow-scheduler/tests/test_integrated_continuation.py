"""Integrated approval, execution and continuation acceptance."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import yaml

from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import TaskStatus


def prepare(tmp_path, two_approvals=False):
    db = str(tmp_path / "integration.sqlite")
    cli = WorkflowSchedulerCLI(db_path=db)
    tasks = [{
        "id": "first", "type": "test", "owner": "system",
        "action": "read:first", "idempotency_key": "first",
        "approval_required": True,
    }]
    tasks.append({
        "id": "second", "type": "test", "owner": "system",
        "action": "read:second", "idempotency_key": "second",
        "depends_on": ["first"],
        "approval_required": two_approvals,
    })
    plan = {
        "workflow_id": "integration",
        "title": "Automatic continuation",
        "created_by": "test",
        "mode": "Draft",
        "tasks": tasks,
    }
    path = tmp_path / "workflow.yaml"
    path.write_text(yaml.safe_dump(plan))
    assert cli.create_workflow(str(path))["status"] == "pass"
    assert cli.run_workflow("integration")["status"] == "blocked"
    return cli, db


def test_one_approval_continues_dependencies_without_second_run(tmp_path):
    cli, _ = prepare(tmp_path)
    decision = cli.approve("first", approver="owner")
    assert decision["status"] == "pass"
    assert decision["continuation"]["status"] == "pass"
    assert len(cli.adapter.execution_log) == 2
    assert cli.repository.get_task("first").status == TaskStatus.COMPLETED
    assert cli.repository.get_task("second").status == TaskStatus.COMPLETED
    assert cli.repository.get_workflow("integration").status.value == "completed"
    assert cli.approve("first", approver="owner")["status"] == "blocked"
    assert len(cli.adapter.execution_log) == 2


def test_two_concurrent_approvals_execute_only_once(tmp_path):
    first, db = prepare(tmp_path)
    second = WorkflowSchedulerCLI(db_path=db)
    barrier = Barrier(2)
    for cli in (first, second):
        original = cli.repository.try_decide_pending_approval

        def synchronize(*args, _original=original, **kwargs):
            barrier.wait(timeout=10)
            return _original(*args, **kwargs)

        cli.repository.try_decide_pending_approval = synchronize

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first.approve, "first", "owner-a")
        b = pool.submit(second.approve, "first", "owner-b")
        responses = [a.result(timeout=20), b.result(timeout=20)]

    assert sorted(x["status"] for x in responses) == ["blocked", "pass"]
    calls = len(first.adapter.execution_log) + len(second.adapter.execution_log)
    assert calls == 2
    assert first.repository.get_workflow("integration").status.value == "completed"
    assert first.repository.get_task("first").status == TaskStatus.COMPLETED


def test_new_approval_for_different_task_is_still_required(tmp_path):
    cli, _ = prepare(tmp_path, two_approvals=True)
    first = cli.approve("first", approver="owner")
    assert first["status"] == "pass"
    assert first["continuation"]["status"] == "blocked"
    assert cli.repository.get_task("first").status == TaskStatus.COMPLETED
    assert cli.repository.get_task("second").status == TaskStatus.APPROVAL_PENDING
    assert len(cli.adapter.execution_log) == 1

    second = cli.approve("second", approver="owner")
    assert second["status"] == "pass"
    assert second["continuation"]["status"] == "pass"
    assert len(cli.adapter.execution_log) == 2


def test_rejection_never_dispatches(tmp_path):
    cli, _ = prepare(tmp_path)
    decision = cli.reject("first", approver="owner", reason="declined")
    assert decision["status"] == "pass"
    assert cli.repository.get_task("first").status == TaskStatus.CANCELLED
    assert len(cli.adapter.execution_log) == 0
    assert cli.approve("first", approver="owner")["status"] == "blocked"
