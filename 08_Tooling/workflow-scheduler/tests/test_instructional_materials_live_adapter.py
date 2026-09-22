from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from workflow_scheduler.adapters.instructional_materials_live_adapter import (
    CONTRACT_VERSION,
    OPERATION,
    InstructionalMaterialsLiveAdapter,
)
from workflow_scheduler.models import ExecutionContext, ExecutionRequest


def _request(**changes):
    payload = {
        "contract_version": CONTRACT_VERSION,
        "operation": OPERATION,
        "repository": "Blummer92/agent-os",
        "authorization_issue_number": 119,
        "subject": {"contract_version": "fixture"},
        "approval_id": "approval:1",
        "approval_revision": "approval-revision:1",
        "projection_id": "approved-execution-projection:1",
        "authorization_id": "execution-authorization:" + "a" * 64,
    }
    payload.update(changes.pop("payload_changes", {}))
    values = {
        "task_id": "c4b-live-task",
        "workflow_id": "c4b-live-workflow",
        "owner": "instructional-materials-coach",
        "payload": payload,
        "idempotency_key": "materials-op-1",
        "mode": "Production",
        "approval_required": True,
        "production_ready": True,
        "execution_id": "trace-only-exec-id",
        "run_id": "run-1",
        "attempt_number": 2,
        "created_at": datetime(2026, 9, 21, tzinfo=timezone.utc),
        "execution_context": ExecutionContext(),
        "batch_id": None,
    }
    values.update(changes)
    return ExecutionRequest(**values)


def _approval():
    return SimpleNamespace(
        status="applicable",
        approval_id="approval:1",
        approval_revision="approval-revision:1",
        projection=SimpleNamespace(projection_id="approved-execution-projection:1"),
        subject=SimpleNamespace(subject_id="instructional-live-operation-subject:" + "b" * 64),
    )


def _authorization():
    return SimpleNamespace(
        status="current",
        evidence=SimpleNamespace(
            authorization_id="execution-authorization:" + "a" * 64,
            authorized_subject_id="instructional-live-operation-subject:" + "b" * 64,
            authorized_run_id="run-1",
            authorized_task_id="c4b-live-task",
            authorized_attempt_number=2,
            authorized_operation=OPERATION,
            execution_authorized=True,
        ),
    )


def _adapter(*, approval=None, authorization=None, builder=None):
    return InstructionalMaterialsLiveAdapter(
        approval_revalidator=approval or MagicMock(return_value=_approval()),
        authorization_reacquirer=authorization or MagicMock(return_value=_authorization()),
        live_build_input_factory=MagicMock(return_value="bounded-build-input"),
        live_builder=builder or MagicMock(return_value=SimpleNamespace(succeeded=True)),
        drive_service="drive",
        slides_service="slides",
        docs_service="docs",
        evaluated_at=lambda: "2026-09-21T21:00:00Z",
    )


def _subject_ref():
    return SimpleNamespace(subject_id="instructional-live-operation-subject:" + "b" * 64)


def test_invalid_real_subject_fails_before_authority_or_builder():
    approval = MagicMock()
    authorization = MagicMock()
    builder = MagicMock()
    result = _adapter(approval=approval, authorization=authorization, builder=builder).execute(
        _request(payload_changes={"subject": {}})
    )
    assert result["status"] == "fail"
    assert result["error"] == "typed-subject-invalid"
    approval.assert_not_called()
    authorization.assert_not_called()
    builder.assert_not_called()


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_current_approval_and_exact_authorization_call_live_builder_once(_validate):
    approval = MagicMock(return_value=_approval())
    authorization = MagicMock(return_value=_authorization())
    builder = MagicMock(return_value=SimpleNamespace(succeeded=True))
    adapter = _adapter(approval=approval, authorization=authorization, builder=builder)

    result = adapter.execute(_request())

    assert result["success"] is True
    assert result["status"] == "pass"
    builder.assert_called_once_with(
        "bounded-build-input",
        drive_service="drive",
        slides_service="slides",
        docs_service="docs",
    )
    auth_kwargs = authorization.call_args.kwargs
    assert auth_kwargs["expected_run_id"] == "run-1"
    assert auth_kwargs["expected_task_id"] == "c4b-live-task"
    assert auth_kwargs["expected_attempt_number"] == 2
    assert auth_kwargs["expected_operation"] == OPERATION
    assert "execution_id" not in auth_kwargs


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_noncurrent_approval_blocks_before_authorization_or_builder(_validate):
    approval = MagicMock(return_value=SimpleNamespace(status="stale"))
    authorization = MagicMock()
    builder = MagicMock()
    result = _adapter(approval=approval, authorization=authorization, builder=builder).execute(_request())
    assert result["error"] == "approval-not-current"
    authorization.assert_not_called()
    builder.assert_not_called()


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_projection_identity_mismatch_blocks_before_authorization(_validate):
    approval = _approval()
    approval.projection = SimpleNamespace(projection_id="other")
    authorization = MagicMock()
    result = _adapter(
        approval=MagicMock(return_value=approval), authorization=authorization
    ).execute(_request())
    assert result["error"] == "projection-identity-mismatch"
    authorization.assert_not_called()


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_noncurrent_execution_authorization_blocks_before_builder(_validate):
    authorization = MagicMock(return_value=SimpleNamespace(status="stale", evidence=None))
    builder = MagicMock()
    result = _adapter(authorization=authorization, builder=builder).execute(_request())
    assert result["error"] == "execution-authorization-not-current"
    builder.assert_not_called()


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_authorization_is_bound_to_exact_scheduler_attempt(_validate):
    auth = _authorization()
    auth.evidence.authorized_attempt_number = 1
    builder = MagicMock()
    result = _adapter(
        authorization=MagicMock(return_value=auth), builder=builder
    ).execute(_request())
    assert result["error"] == "execution-authorization-attempt-mismatch"
    builder.assert_not_called()


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_batching_and_payload_expansion_fail_closed(_validate):
    builder = MagicMock()
    assert _adapter(builder=builder).execute(_request(batch_id="batch-1"))["error"] == "batching-not-authorized"
    expanded = _request(payload_changes={"credential": "must-not-be-carried"})
    assert _adapter(builder=builder).execute(expanded)["error"] == "live-contract-shape-invalid"
    builder.assert_not_called()


@patch(
    "workflow_scheduler.adapters.instructional_materials_live_adapter.validate_typed_subject_reference",
    return_value=_subject_ref(),
)
def test_partial_live_receipt_is_returned_without_retry_or_cleanup(_validate):
    receipt = SimpleNamespace(succeeded=False, slides="created", worksheet="ambiguous")
    builder = MagicMock(return_value=receipt)
    result = _adapter(builder=builder).execute(_request())
    assert result["success"] is False
    assert result["error"] == "live-build-incomplete"
    assert result["output"]["receipt"] is receipt
    builder.assert_called_once()
