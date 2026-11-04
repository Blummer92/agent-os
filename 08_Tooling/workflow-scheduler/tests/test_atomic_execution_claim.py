"""Atomic execution claims across independent SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from workflow_scheduler.models import Task, TaskStatus
from workflow_scheduler.repository import SQLiteRepository
from workflow_scheduler.execution import Executor
from workflow_scheduler.adapters import NoopAdapter
from workflow_scheduler.audit import AuditLogger


def make_task():
    return Task(
        id="claim-test",
        workflow_id="claim-test",
        type="test",
        owner="system",
        action="read:probe",
        idempotency_key="claim-test",
    )


def test_simultaneous_execution_has_one_winner(tmp_path):
    db = str(tmp_path / "race.db")
    a, b = SQLiteRepository(db), SQLiteRepository(db)
    a.create_task(make_task())
    adapter_a, adapter_b = NoopAdapter(), NoopAdapter()
    ex_a = Executor(adapter_a, a, AuditLogger(repository=a))
    ex_b = Executor(adapter_b, b, AuditLogger(repository=b))
    task_a, task_b = a.get_task("claim-test"), b.get_task("claim-test")

    barrier = Barrier(2)
    for repository in (a, b):
        original = repository.try_claim_execution

        def racing(task_id, _original=original):
            barrier.wait(timeout=10)
            return _original(task_id)

        repository.try_claim_execution = racing

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(ex_a.execute, task_a)
        f2 = pool.submit(ex_b.execute, task_b)
        results = [f1.result(timeout=20), f2.result(timeout=20)]

    calls = len(adapter_a.execution_log) + len(adapter_b.execution_log)
    assert calls == 1, f"Expected one adapter call, got {calls}"
    assert sum(result.success for result in results) == 1
    assert a.get_task("claim-test").status == TaskStatus.COMPLETED
    assert a.get_task("claim-test").lease_lock is None


def test_stale_task_update_cannot_overwrite_claim(tmp_path):
    db = str(tmp_path / "fence.db")
    a, b = SQLiteRepository(db), SQLiteRepository(db)
    a.create_task(make_task())
    stale = b.get_task("claim-test")

    token = a.try_claim_execution("claim-test")
    assert token is not None

    stale.mark_completed()
    b.update_task(stale)
    assert a.get_task("claim-test").status == TaskStatus.RUNNING

    owned = a.get_task("claim-test")
    owned.mark_completed()
    assert a.update_claimed_task(owned, token)
    assert not b.release_execution_claim("claim-test", "wrong-token")
    assert a.release_execution_claim("claim-test", token)
    assert a.get_task("claim-test").status == TaskStatus.COMPLETED


def test_unfinished_claim_is_not_silently_stolen(tmp_path):
    db = str(tmp_path / "crash.db")
    a, b = SQLiteRepository(db), SQLiteRepository(db)
    a.create_task(make_task())
    assert a.try_claim_execution("claim-test") is not None
    assert b.try_claim_execution("claim-test") is None
