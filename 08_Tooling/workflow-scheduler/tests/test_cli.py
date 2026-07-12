"""Tests for CLI."""

import pytest
import tempfile
import yaml
from pathlib import Path

from workflow_scheduler.cli import WorkflowSchedulerCLI


@pytest.fixture
def temp_db():
    """Create temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name


@pytest.fixture
def temp_yaml():
    """Create temporary YAML workflow file."""
    workflow_data = {
        "workflow_id": "test-workflow",
        "title": "Test Workflow",
        "created_by": "test",
        "mode": "Draft",
        "tasks": [
            {
                "id": "task-1",
                "type": "test",
                "owner": "system",
                "action": "test_action",
                "idempotency_key": "key-1",
                "priority": 1,
            },
            {
                "id": "task-2",
                "type": "test",
                "owner": "system",
                "action": "test_action",
                "idempotency_key": "key-2",
                "depends_on": ["task-1"],
                "priority": 0,
            },
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(workflow_data, f)
        yield f.name


class TestCLI:
    """Tests for WorkflowSchedulerCLI."""

    def test_create_workflow_from_yaml(self, temp_db, temp_yaml):
        """Test creating workflow from YAML."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        result = cli.create_workflow(temp_yaml)

        assert result["success"] is True
        assert result["workflow_id"] == "test-workflow"
        assert result["task_count"] == 2

    def test_create_workflow_file_not_found(self, temp_db):
        """Test creating workflow from nonexistent file."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        result = cli.create_workflow("/nonexistent/path/workflow.yaml")

        assert result["success"] is False
        assert "File not found" in result["error"]

    def test_create_workflow_invalid_yaml(self, temp_db):
        """Test creating workflow from invalid YAML."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            temp_invalid = f.name

        cli = WorkflowSchedulerCLI(db_path=temp_db)
        result = cli.create_workflow(temp_invalid)

        assert result["success"] is False
        assert "Invalid YAML" in result["error"]

    def test_get_workflow_status(self, temp_db, temp_yaml):
        """Test getting workflow status."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.get_workflow_status("test-workflow")

        assert result["success"] is True
        assert result["workflow_id"] == "test-workflow"
        assert result["title"] == "Test Workflow"
        assert result["task_count"] == 2

    def test_get_workflow_status_not_found(self, temp_db):
        """Test getting status of nonexistent workflow."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        result = cli.get_workflow_status("nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_list_workflows(self, temp_db, temp_yaml):
        """Test listing workflows."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.list_workflows()

        assert result["success"] is True
        assert "workflows" in result

    def test_run_workflow_success(self, temp_db, temp_yaml):
        """Test running a workflow successfully."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.run_workflow("test-workflow")

        assert result["success"] is True
        assert result["workflow_id"] == "test-workflow"
        assert result["completed"] > 0

    def test_run_workflow_not_found(self, temp_db):
        """Test running nonexistent workflow."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        result = cli.run_workflow("nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_run_workflow_already_terminal(self, temp_db, temp_yaml):
        """Test running workflow that's already in terminal state."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        # Run it once
        cli.run_workflow("test-workflow")

        # Try to run again (should fail - already terminal)
        result = cli.run_workflow("test-workflow")

        assert result["success"] is False
        assert "terminal state" in result["error"]

    def test_show_audit_log_all(self, temp_db, temp_yaml):
        """Test showing all audit log entries."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.show_audit_log()

        assert result["success"] is True
        assert result["event_count"] > 0

    def test_show_audit_log_by_workflow(self, temp_db, temp_yaml):
        """Test showing audit log for specific workflow."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.show_audit_log(workflow_id="test-workflow")

        assert result["success"] is True
        assert result["event_count"] > 0
        assert all(e["workflow_id"] == "test-workflow" for e in result["events"])

    def test_show_audit_log_by_task(self, temp_db, temp_yaml):
        """Test showing audit log for specific task."""
        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.show_audit_log(task_id="task-1")

        assert result["success"] is True

    def test_workflow_with_cycle_detection(self, temp_db):
        """Test that workflow with cycles is rejected."""
        workflow_data = {
            "workflow_id": "cycle-workflow",
            "title": "Cycle Workflow",
            "created_by": "test",
            "tasks": [
                {
                    "id": "task-A",
                    "type": "test",
                    "owner": "system",
                    "action": "test",
                    "idempotency_key": "key-A",
                    "depends_on": ["task-B"],
                },
                {
                    "id": "task-B",
                    "type": "test",
                    "owner": "system",
                    "action": "test",
                    "idempotency_key": "key-B",
                    "depends_on": ["task-A"],
                },
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(workflow_data, f)
            temp_yaml = f.name

        cli = WorkflowSchedulerCLI(db_path=temp_db)
        cli.create_workflow(temp_yaml)

        result = cli.run_workflow("cycle-workflow")

        assert result["success"] is False
        assert "Circular dependency" in result["error"]
