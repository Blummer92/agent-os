"""Tests for the PYLIB5 pilot status wrapper (#3222).

Proves the acceptance criteria: exit-code mapping, JSON byte-identity with the
canonical payload (machine path never passes through Rich), CI-mode ANSI
suppression, help snapshot, and read-only behavior against a missing database.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from task_helpers import make_plain_task
from workflow_scheduler.models import TaskStatus, WorkflowPlan
from workflow_scheduler.repository import SQLiteRepository
from workflow_scheduler.status_cli import app, build_status_payload

runner = CliRunner()
PACKAGE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db_path(tmp_path):
    """Synthetic scheduler DB: one workflow, two batches, mixed statuses."""
    path = tmp_path / "status.db"
    repo = SQLiteRepository(str(path))
    repo.create_workflow(
        WorkflowPlan(
            workflow_id="wf-1", title="Pilot workflow", created_by="test"
        )
    )
    repo.create_task(
        make_plain_task(
            "t1",
            workflow_id="wf-1",
            status=TaskStatus.COMPLETED,
            batch_id="b1",
        )
    )
    repo.create_task(
        make_plain_task(
            "t2",
            workflow_id="wf-1",
            status=TaskStatus.FAILED,
            batch_id="b1",
        )
    )
    repo.create_task(
        make_plain_task(
            "t3",
            workflow_id="wf-1",
            status=TaskStatus.RUNNING,
            batch_id="b2",
        )
    )
    repo.create_task(
        make_plain_task(
            "t4",
            workflow_id="wf-1",
            status=TaskStatus.COMPLETED,
            batch_id="b2",
        )
    )
    repo.close()
    return path


def _args(db_path, *extra):
    return ["wf-1", "--db", str(db_path), *extra]


def test_text_renders_batch_rollups(db_path):
    result = runner.invoke(app, _args(db_path))
    assert result.exit_code == 0, result.output
    assert "wf-1" in result.output
    assert "b1" in result.output
    assert "failed" in result.output  # b1 rollup: one member FAILED
    assert "b2" in result.output
    assert "partial" in result.output  # b2 rollup: RUNNING only


def test_json_byte_identical_to_canonical_payload(db_path):
    result = runner.invoke(app, _args(db_path, "--format", "json"))
    assert result.exit_code == 0, result.output
    repo = SQLiteRepository(str(db_path))
    try:
        expected = (
            json.dumps(build_status_payload("wf-1", repo), indent=2, sort_keys=True)
            + "\n"
        )
    finally:
        repo.close()
    assert result.stdout == expected


def test_json_payload_shape(db_path):
    result = runner.invoke(app, _args(db_path, "--format", "json"))
    payload = json.loads(result.stdout)
    assert payload["workflow_id"] == "wf-1"
    assert payload["task_count"] == 4
    rollups = {b["batch_id"]: b["rollup"] for b in payload["batches"]}
    assert rollups == {"b1": "failed", "b2": "partial"}


def test_unknown_workflow_exit_1(db_path):
    result = runner.invoke(app, ["nope", "--db", str(db_path)])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not found" in result.output


def test_missing_db_exit_1_and_not_created(tmp_path):
    missing = tmp_path / "does-not-exist.db"
    result = runner.invoke(app, ["wf-1", "--db", str(missing)])
    assert result.exit_code == 1
    assert not missing.exists()  # read-only: never create the database
    assert "not found" in result.output


def test_ci_mode_no_ansi(db_path):
    result = runner.invoke(app, _args(db_path), env={"NO_COLOR": "1"})
    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.output


def test_piped_non_tty_no_ansi_without_no_color(db_path):
    # CliRunner captures output (not a TTY): Rich must suppress color itself.
    result = runner.invoke(app, _args(db_path))
    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.output


def test_help_names_program_and_format(db_path):
    # Type-derived help content via the app object.
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "--format" in result.output
    assert "text" in result.output and "json" in result.output
    assert "workflow_id" in result.output


def test_help_program_name_not_script_filename():
    # The installed entry point must show the explicit program name, never
    # the module filename (#1142 constraint). Exercises main()'s prog_name.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PACKAGE_DIR / "src")
    env["NO_COLOR"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "workflow_scheduler.status_cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PACKAGE_DIR),
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "agent-os-scheduler-status" in proc.stdout
    assert "status_cli" not in proc.stdout


def test_invalid_format_exit_2(db_path):
    result = runner.invoke(app, _args(db_path, "--format", "yaml"))
    assert result.exit_code == 2
