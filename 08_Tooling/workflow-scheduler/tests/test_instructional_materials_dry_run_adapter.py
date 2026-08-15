import inspect
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

import workflow_scheduler.adapters.instructional_materials_dry_run_adapter as adapter_module
from workflow_scheduler.adapters import InstructionalMaterialsDryRunAdapter
from workflow_scheduler.adapters.instructional_materials_contract import (
    validate_instructional_materials_contract,
)
from workflow_scheduler.cli import WorkflowSchedulerCLI
from workflow_scheduler.models import ExecutionContext, ExecutionRequest, TaskStatus


def _payload():
    return {
        "contract_version": "imc-materials-task-v1",
        "operation": "build_materials_bundle",
        "dry_run": True,
        "execution_authorized": False,
        "content_path": "lessons/example lesson.yaml",
        "slides_template_id": "slides-template-example",
        "doc_template_id": "doc-template-example",
        "target_drive_folder_id": "drive-folder-example",
        "lessons_dir": "reports/lessons",
        "production_gates": {
            "source_confidence": "approved",
            "unit_readiness": "ready",
            "modeling_readiness": "ready_for_slides",
            "evidence_target": "example-modeling-handoff",
            "blockers": "none",
        },
        "governed_field_risk": False,
        "writes_governed_field": False,
    }


def _request(**overrides):
    values = {
        "task_id": "build-materials-bundle",
        "workflow_id": "classroom-artifact-dry-run-v1",
        "owner": "instructional-materials-coach",
        "payload": _payload(),
        "idempotency_key": "example-materials-dry-run-001",
        "mode": "Draft",
        "approval_required": False,
        "production_ready": False,
        "execution_id": "execution-1",
        "run_id": "run-1",
        "attempt_number": 0,
        "created_at": datetime(2026, 8, 15, tzinfo=timezone.utc),
        "execution_context": ExecutionContext(),
        "batch_id": None,
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def test_adapter_opts_into_execution_request_and_delegates_result_unchanged(monkeypatch):
    execution_request = _request()
    sentinel = {"status": "success", "message": "sentinel"}
    seen = []

    def fake_validator(value):
        seen.append(value)
        return sentinel

    monkeypatch.setattr(
        adapter_module,
        "validate_instructional_materials_contract",
        fake_validator,
    )
    adapter = InstructionalMaterialsDryRunAdapter()
    assert adapter.accepts_execution_request is True
    assert adapter.execute(execution_request) is sentinel
    assert seen == [execution_request]


def test_valid_result_matches_c3a_and_preserves_request_state():
    execution_request = _request()
    payload_before = deepcopy(execution_request.payload)
    context_before = deepcopy(execution_request.execution_context)
    result = InstructionalMaterialsDryRunAdapter().execute(execution_request)

    assert result == validate_instructional_materials_contract(execution_request)
    assert result["status"] == "success"
    assert isinstance(result["output"]["command"], list)
    assert result["output"]["command"][3] == "lessons/example lesson.yaml"
    assert execution_request.payload == payload_before
    assert execution_request.execution_context == context_before


@pytest.mark.parametrize(
    ("execution_request", "reason"),
    [
        (
            _request(payload={**_payload(), "dry_run": False}),
            "live-execution-not-authorized",
        ),
        (
            _request(payload={**_payload(), "execution_authorized": True}),
            "live-execution-not-authorized",
        ),
        (_request(mode="Production"), "production-mode-not-authorized"),
        (_request(approval_required=True), "approval-path-not-authorized"),
        (_request(production_ready=True), "production-mode-not-authorized"),
        (_request(batch_id="batch-1"), "batching-not-authorized"),
        (
            _request(payload={**_payload(), "governed_field_risk": True}),
            "governed-field-risk",
        ),
        (
            _request(
                payload={
                    **_payload(),
                    "production_gates": {
                        **_payload()["production_gates"],
                        "source_confidence": "pending",
                    },
                }
            ),
            "production-gate-not-satisfied",
        ),
    ],
)
def test_c3a_blocked_results_pass_through_unchanged(execution_request, reason):
    result = InstructionalMaterialsDryRunAdapter().execute(execution_request)

    assert result == validate_instructional_materials_contract(execution_request)
    assert result == {
        "status": "blocked",
        "message": "Instructional Materials Coach dry-run request is not authorized.",
        "blocked_reason": reason,
    }


def test_hostile_value_is_rejected_not_executed():
    payload = _payload()
    payload["content_path"] = "lessons/$(whoami).yaml"

    result = InstructionalMaterialsDryRunAdapter().execute(_request(payload=payload))
    assert result["status"] == "failure"


def test_adapter_source_has_no_execution_or_external_io_sink():
    source = inspect.getsource(adapter_module)
    for banned in (
        "subprocess",
        "os.system",
        "Popen",
        "instructional_materials_coach",
        "google",
        "oauth",
        "requests",
        "socket",
        "SQLiteRepository",
        "JobQueue",
        "AuditLogger",
        "ALLOW_WRITE",
        "open(",
    ):
        assert banned not in source


def test_example_loads_as_draft_without_adapter_execution():
    example = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "instructional-materials-dry-run.yaml"
    )
    cli = WorkflowSchedulerCLI(db_path=":memory:")
    result = cli.create_workflow(str(example))

    assert result["status"] == "pass"
    workflow = cli.repository.get_workflow("classroom-artifact-dry-run-v1")
    tasks = cli.repository.list_workflow_tasks("classroom-artifact-dry-run-v1")
    assert workflow.status.value == "draft"
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.DRAFT
    assert cli.adapter.get_execution_log() == []
