"""Workflow scheduler CLI checks (wire status: pass/0, fail or blocked/1)."""

from contextlib import ExitStack, closing
from dataclasses import dataclass, field
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
import yaml

import workflow_scheduler.cli as cli_module
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import TaskStatus, WorkflowMode, WorkflowStatus


@pytest.fixture
def workflow_data(request):
    """Use deliberate task IDs in a fresh database and a test-specific workflow."""
    return {
        "workflow_id": request.node.originalname,
        "title": "Test Workflow",
        "created_by": "test",
        "mode": "Draft",
        "tasks": [
            {"id": "task-1", "action": "fixture:one", "idempotency_key": "key-1", "priority": 1},
            {"id": "task-2", "action": "fixture:two", "idempotency_key": "key-2",
             "depends_on": ["task-1"], "priority": 2},
        ],
    }


def write_plan(tmp_path, data, name="workflow"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


@pytest.fixture
def cli_factory(tmp_path):
    """Close each connection, even if setup or an assertion fails."""
    with ExitStack() as stack:
        def open_cli(path=tmp_path / "workflow.db"):
            cli = WorkflowSchedulerCLI(db_path=str(path))
            stack.callback(cli.repository.close)
            return cli

        yield open_cli


@pytest.fixture
def cli(cli_factory):
    return cli_factory()


@dataclass
class RecordingAdapter:
    """Observe every adapter call, independently from reported status/count."""
    task_ids: list[str] = field(default_factory=list)

    def execute(self, task):
        self.task_ids.append(task.id)
        return {"success": True, "output": {"observed_task": task.id}}


@pytest.fixture
def seeded(cli, tmp_path, workflow_data):
    result = cli.create_workflow(write_plan(tmp_path, workflow_data))
    assert result["workflow_id"] == workflow_data["workflow_id"]
    assert result["checks_passed"] == ["workflow_created", "tasks_created"]
    assert result["status"] == "pass"
    return result


@pytest.fixture
def ran(cli, seeded):
    recorder = RecordingAdapter()
    cli.executor.adapter = recorder
    result = cli.run_workflow(seeded["workflow_id"])
    assert recorder.task_ids == ["task-1", "task-2"]
    assert result["workflow_id"] == seeded["workflow_id"]
    assert result["status"] == "pass"
    assert result["completed"] == 2
    assert cli.repository.get_workflow(seeded["workflow_id"]).status is WorkflowStatus.COMPLETED
    assert {t.id: t.status for t in cli.repository.list_workflow_tasks(seeded["workflow_id"])} == {
        "task-1": TaskStatus.COMPLETED, "task-2": TaskStatus.COMPLETED,
    }
    return result, recorder


def assert_failure(result, check, *, status="fail", blockers=()):
    assert result["status"] == status
    assert result["checks_failed"] == [check]
    assert result["checks_passed"] == []
    # Equality plus size catches additional, missing, and duplicate blockers.
    assert set(result["blockers"]) == set(blockers)
    assert len(result["blockers"]) == len(blockers)
    assert result["error"]


def test_create_workflow_from_yaml(cli, seeded):
    workflow_id = seeded["workflow_id"]
    assert seeded["task_count"] == 2
    workflow = cli.repository.get_workflow(workflow_id)
    assert (workflow.title, workflow.created_by, workflow.mode) == ("Test Workflow", "test", WorkflowMode.DRAFT)
    assert workflow.tasks == ["task-1", "task-2"]
    assert workflow.dependencies == {"task-1": [], "task-2": ["task-1"]}
    assert [(t.id, t.priority, t.depends_on, t.action) for t in cli.repository.list_workflow_tasks(workflow_id)] == [
        ("task-2", 2, ["task-1"], "fixture:two"), ("task-1", 1, [], "fixture:one"),
    ]


def test_create_workflow_file_not_found(cli, tmp_path):
    missing = tmp_path / "missing.yaml"
    assert not missing.exists()
    result = cli.create_workflow(str(missing))
    assert_failure(result, "file_not_found")
    assert str(missing) in result["error"]
    assert cli.show_audit_log()["events"] == []


def test_create_workflow_invalid_yaml(cli, tmp_path):
    invalid = tmp_path / "invalid.yaml"
    malformed = "tasks: [\n"
    invalid.write_text(malformed, encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(malformed)
    result = cli.create_workflow(str(invalid))
    assert_failure(result, "yaml_parse")
    assert cli.show_audit_log()["events"] == []


def test_get_workflow_status(cli, seeded):
    result = cli.get_workflow_status(seeded["workflow_id"])
    assert result["status"] == "pass"
    assert result["workflow_id"] == seeded["workflow_id"]
    assert result["title"] == seeded["title"]
    assert result["workflow_status"] == WorkflowStatus.DRAFT.value
    assert result["mode"] == WorkflowMode.DRAFT.value
    assert result["task_count"] == 2
    assert result["task_statuses"] == {"task-1": TaskStatus.DRAFT.value, "task-2": TaskStatus.DRAFT.value}


@pytest.mark.parametrize("method", ["get_workflow_status", "run_workflow"])
def test_workflow_lookup_not_found(cli, method):
    result = getattr(cli, method)("absent-workflow")
    assert_failure(result, "workflow_not_found")
    assert "absent-workflow" in result["error"]


def test_list_workflows(cli, seeded):
    result = cli.list_workflows()
    assert result["status"] == "pass"
    assert result["workflows"] == [
        {"workflow_id": seeded["workflow_id"], "title": seeded["title"],
         "status": WorkflowStatus.DRAFT.value, "mode": WorkflowMode.DRAFT.value}
    ]


def test_run_workflow_success(cli, ran, seeded):
    result, recorder = ran
    assert result["completed"] == len(recorder.task_ids) == seeded["task_count"] == 2
    completed = [e for e in cli.show_audit_log()["events"] if e["event_type"] == "task_completed"]
    assert [(e["task_id"], e["details"]["result"]["observed_task"]) for e in completed] == [
        ("task-1", "task-1"), ("task-2", "task-2"),
    ]


def test_run_workflow_already_terminal(cli, ran):
    first, recorder = ran
    result = cli.run_workflow(first["workflow_id"])
    assert_failure(result, "workflow_not_in_runnable_state", status="blocked", blockers={"workflow_terminal"})
    assert WorkflowStatus.COMPLETED.value in result["error"]
    assert recorder.task_ids == ["task-1", "task-2"]
    assert cli.repository.get_workflow(first["workflow_id"]).status is WorkflowStatus.COMPLETED


def test_show_audit_log_all(cli, seeded, ran):
    result = cli.show_audit_log()
    assert result["status"] == "pass"
    assert result["event_count"] == len(result["events"])
    events = result["events"]
    assert [(e["event_type"], e["task_id"]) for e in events] == [
        ("workflow_created", None), ("workflow_started", None),
        ("governance_check_passed", "task-1"), ("task_completed", "task-1"),
        ("governance_check_passed", "task-2"), ("task_completed", "task-2"),
        ("workflow_completed", None),
    ]
    assert {e["workflow_id"] for e in events} == {seeded["workflow_id"]}
    assert [e["timestamp"] for e in events] == sorted(e["timestamp"] for e in events)
    assert events[0]["details"] == {"title": seeded["title"], "created_by": "test"}
    assert events[-1]["status_after"] == WorkflowStatus.COMPLETED.value


def test_show_audit_log_by_workflow(cli, tmp_path, seeded, workflow_data):
    other = workflow_data | {"workflow_id": "other-workflow", "tasks": [{"id": "other-task"}]}
    alternate = cli.create_workflow(write_plan(tmp_path, other, "other"))
    assert alternate["workflow_id"] == other["workflow_id"]
    assert alternate["task_count"] == 1
    assert cli.show_audit_log()["event_count"] == 2
    result = cli.show_audit_log(workflow_id=seeded["workflow_id"])
    assert result["status"] == "pass"
    assert result["event_count"] == 1
    assert [(e["workflow_id"], e["event_type"]) for e in result["events"]] == [
        (seeded["workflow_id"], "workflow_created"),
    ]


@pytest.mark.parametrize("include_workflow", [False, True], ids=["task-only", "workflow-and-task"])
def test_show_audit_log_by_task(cli, seeded, ran, include_workflow):
    result = cli.show_audit_log(workflow_id=seeded["workflow_id"] if include_workflow else None, task_id="task-1")
    assert result["status"] == "pass"
    assert result["event_count"] == 2
    assert [(e["task_id"], e["event_type"]) for e in result["events"]] == [
        ("task-1", "governance_check_passed"), ("task-1", "task_completed"),
    ]


def test_workflow_with_cycle_detection(cli, tmp_path, workflow_data):
    workflow_data["tasks"][0]["depends_on"] = ["task-2"]
    workflow_id = workflow_data["workflow_id"]
    result = cli.create_workflow(write_plan(tmp_path, workflow_data))
    assert_failure(result, "invalid_workflow_plan")
    assert "Circular dependency" in result["error"]
    assert cli.repository.get_workflow(workflow_id) is None
    assert cli.repository.list_workflow_tasks(workflow_id) == []
    assert cli.show_audit_log()["events"] == []


def test_create_accepts_forward_dependency_declaration(cli, tmp_path, workflow_data):
    workflow_data["tasks"].reverse()
    result = cli.create_workflow(write_plan(tmp_path, workflow_data))
    workflow_id = result["workflow_id"]
    assert cli.repository.get_workflow(workflow_id).tasks == ["task-2", "task-1"]
    assert cli.repository.get_workflow(workflow_id).dependencies["task-2"] == ["task-1"]
    recorder = RecordingAdapter()
    cli.executor.adapter = recorder
    execution = cli.run_workflow(workflow_id)
    assert execution["status"] == "pass"
    assert execution["completed"] == 2
    assert recorder.task_ids == ["task-1", "task-2"]


def test_list_workflow_tasks_missing_has_explicit_empty_contract(cli, seeded):
    """Low-level query returns an empty collection; the CLI identifies absence."""
    assert len(cli.repository.list_workflow_tasks(seeded["workflow_id"])) == 2
    assert cli.repository.list_workflow_tasks("not-a-workflow") == []
    assert_failure(cli.get_workflow_status("not-a-workflow"), "workflow_not_found")


@pytest.mark.parametrize("case", [
    "empty-tasks", "missing-tasks", "duplicate-task", "duplicate-key", "non-integer-priority",
    "boolean-priority", "oversized-priority", "non-mapping", "null-document",
    "blank-workflow-id", "missing-dependency", "malformed-dependency",
])
def test_invalid_plan_refused_without_writes(cli, tmp_path, workflow_data, case):
    if case == "empty-tasks":
        workflow_data["tasks"] = []
    elif case == "missing-tasks":
        del workflow_data["tasks"]
    elif case == "duplicate-task":
        workflow_data["tasks"][1]["id"] = "task-1"
    elif case == "duplicate-key":
        workflow_data["tasks"][1]["idempotency_key"] = "key-1"
    elif case.endswith("-priority"):
        workflow_data["tasks"][0]["priority"] = {
            "non-integer-priority": "high", "boolean-priority": True, "oversized-priority": 2**63,
        }[case]
    elif case == "blank-workflow-id":
        workflow_data["workflow_id"] = " "
    elif case == "missing-dependency":
        workflow_data["tasks"][1]["depends_on"] = ["unknown-task"]
    elif case == "malformed-dependency":
        workflow_data["tasks"][1]["depends_on"] = "task-1"
    workflow_id = workflow_data["workflow_id"]
    source = {"non-mapping": [], "null-document": None}.get(case, workflow_data)
    result = cli.create_workflow(write_plan(tmp_path, source))
    assert_failure(result, "invalid_workflow_plan")
    assert cli.repository.get_workflow(workflow_id) is None
    assert cli.repository.list_workflow_tasks(workflow_id) == []
    assert cli.show_audit_log()["events"] == []


def test_omitted_workflow_id_uses_documented_legacy_auto_id(cli, tmp_path, workflow_data):
    del workflow_data["workflow_id"]
    result = cli.create_workflow(write_plan(tmp_path, workflow_data))
    assert result["status"] == "pass"
    assert re.fullmatch(r"workflow-[0-9a-f]{8}", result["workflow_id"])
    assert cli.repository.get_workflow(result["workflow_id"]).tasks == ["task-1", "task-2"]


def test_duplicate_workflow_id_does_not_overwrite(cli, tmp_path, workflow_data, seeded):
    original = cli.repository.get_workflow(seeded["workflow_id"])
    workflow_data.update(title="New title", tasks=[{"id": "new-task"}])
    result = cli.create_workflow(write_plan(tmp_path, workflow_data))
    assert_failure(result, "workflow_creation_unconfirmed", status="blocked", blockers={"workflow_creation_unconfirmed"})
    assert cli.repository.get_workflow(seeded["workflow_id"]) == original
    assert cli.repository.get_task("new-task") is None
    assert cli.show_audit_log()["event_count"] == 1


def test_second_task_unique_constraint_rolls_back_entire_plan(cli, seeded, tmp_path, workflow_data):
    other = workflow_data | {"workflow_id": "second-workflow", "tasks": [{"id": "new-task"}, {"id": "task-1"}]}
    result = cli.create_workflow(write_plan(tmp_path, other))
    assert_failure(result, "workflow_creation_unconfirmed", status="blocked", blockers={"workflow_creation_unconfirmed"})
    assert cli.repository.get_workflow("second-workflow") is None
    assert cli.repository.get_task("new-task") is None
    assert cli.repository.get_task("task-1").workflow_id == seeded["workflow_id"]
    assert cli.show_audit_log()["event_count"] == 1


def test_creation_audit_failure_rolls_back_workflow_and_tasks(cli, tmp_path, workflow_data):
    # Inject a deterministic database-level failure after all task inserts.
    with closing(sqlite3.connect(tmp_path / "workflow.db")) as connection, connection:
        connection.execute("""
            CREATE TRIGGER refuse_workflow_created BEFORE INSERT ON audit_log
            WHEN NEW.event_type = 'workflow_created'
            BEGIN SELECT RAISE(ABORT, 'creation audit unavailable'); END
        """)
    result = cli.create_workflow(write_plan(tmp_path, workflow_data))
    assert_failure(result, "workflow_creation_unconfirmed", status="blocked", blockers={"workflow_creation_unconfirmed"})
    assert cli.repository.get_workflow(workflow_data["workflow_id"]) is None
    assert cli.repository.get_task("task-1") is None
    assert cli.repository.get_task("task-2") is None
    assert cli.show_audit_log()["events"] == []


def test_empty_database_bootstraps_and_connections_can_be_closed(cli_factory, tmp_path, workflow_data):
    db = tmp_path / "existing-empty.db"
    db.touch()
    assert db.stat().st_size == 0
    writer = cli_factory(db)
    reader = cli_factory(db)
    result = writer.create_workflow(write_plan(tmp_path, workflow_data))
    assert result["task_count"] == 2
    assert reader.repository.get_workflow(result["workflow_id"]).tasks == ["task-1", "task-2"]
    writer.repository.close()
    reader.repository.close()
    db.unlink()
    assert not db.exists()


def cli_process(tmp_path, *args):
    module_source = str(Path(cli_module.__file__).resolve().parents[1])
    env = os.environ | {"PYTHONPATH": module_source, "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.run(
        [sys.executable, "-m", "workflow_scheduler.cli", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert process.stderr == ""
    return process.returncode, json.loads(process.stdout)


def assert_wire_shape(result):
    assert {"status", "blockers", "checks_passed", "checks_failed", "next_owner",
            "handoff_artifacts", "files_changed", "tests_run"} <= result.keys()
    assert all(isinstance(result[key], list) for key in ("blockers", "checks_passed", "checks_failed"))


def test_cli_entrypoint_create_status_and_durable_audit(tmp_path, workflow_data):
    db = str(tmp_path / "entrypoint.db")
    path = write_plan(tmp_path, workflow_data)
    code, created = cli_process(tmp_path, "create", path, "--db", db)
    assert code == 0
    assert_wire_shape(created)
    assert created["workflow_id"] == workflow_data["workflow_id"]
    assert created["task_count"] == 2
    code, status = cli_process(tmp_path, "status", created["workflow_id"], "--db", db)
    assert code == 0
    assert_wire_shape(status)
    assert status["status"] == "pass"
    assert status["task_statuses"] == {"task-1": TaskStatus.DRAFT.value, "task-2": TaskStatus.DRAFT.value}
    code, audit = cli_process(tmp_path, "audit", "--workflow-id", created["workflow_id"], "--db", db)
    assert code == 0
    assert_wire_shape(audit)
    assert audit["event_count"] == 1
    assert [(e["workflow_id"], e["event_type"], e["status_after"]) for e in audit["events"]] == [
        (created["workflow_id"], "workflow_created", WorkflowStatus.DRAFT.value)
    ]
    code, listed = cli_process(tmp_path, "list", "--db", db)
    assert code == 0
    assert_wire_shape(listed)
    assert [wf["workflow_id"] for wf in listed["workflows"]] == [created["workflow_id"]]
    code, duplicate = cli_process(tmp_path, "create", path, "--db", db)
    assert code == 1
    assert_wire_shape(duplicate)
    assert_failure(duplicate, "workflow_creation_unconfirmed", status="blocked", blockers={"workflow_creation_unconfirmed"})
    code, missing = cli_process(tmp_path, "status", "missing-workflow", "--db", db)
    assert code == 1
    assert_wire_shape(missing)
    assert_failure(missing, "workflow_not_found")


@pytest.mark.parametrize(("command", "args", "expected_check"), [
    ("status", ("missing-workflow",), "workflow_not_found"),
    ("audit", (), "database_not_found"),
    ("list", (), "database_not_found"),
])
def test_cli_entrypoint_missing_read_does_not_create_db(tmp_path, command, args, expected_check):
    db = tmp_path / "absent.db"
    code, result = cli_process(tmp_path, command, *args, "--db", str(db))
    assert code == 1
    assert_wire_shape(result)
    assert_failure(result, expected_check)
    assert not db.exists()


@pytest.mark.parametrize("use_real_adapter", [False, True], ids=["no-op", "observed-work"])
def test_production_workflow_needs_a_non_noop_adapter(cli, tmp_path, workflow_data, use_real_adapter):
    workflow_data["mode"] = "Production"
    created = cli.create_workflow(write_plan(tmp_path, workflow_data))
    assert created["status"] == "pass"
    workflow_id = created["workflow_id"]
    noop = cli.executor.adapter
    recorder = RecordingAdapter()
    if use_real_adapter:
        cli.executor.adapter = recorder

    result = cli.run_workflow(workflow_id)
    workflow = cli.repository.get_workflow(workflow_id)
    tasks = cli.repository.list_workflow_tasks(workflow_id)
    assert not noop.get_execution_log()
    if use_real_adapter:
        assert result["status"] == "pass" and result["completed"] == 2
        assert recorder.task_ids == ["task-1", "task-2"]
        assert workflow.status is WorkflowStatus.COMPLETED
        assert all(task.status is TaskStatus.COMPLETED for task in tasks)
    else:
        assert result["status"] == "blocked"
        assert set(result["blockers"]) == {"production_adapter_required"}
        assert workflow.status is WorkflowStatus.DRAFT
        assert len(tasks) == 2 and all(
            task.status is TaskStatus.DRAFT and task.lease_lock is None for task in tasks
        )
