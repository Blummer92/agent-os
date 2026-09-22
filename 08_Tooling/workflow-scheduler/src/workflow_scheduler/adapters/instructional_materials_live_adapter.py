"""Governed C4B Scheduler binding for one instructional-materials live operation.

The adapter owns orchestration only. Approval applicability, execution-authorization
reacquisition, live-build input construction, provider clients, and the #1195
live builder are injected by the authorized host.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from scripts.agent_os_issue_acceptance.typed_subject_approval import (
    INSTRUCTIONAL_LIVE_SUBJECT_KIND,
    validate_typed_subject_reference,
)
from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import ExecutionRequest

CONTRACT_VERSION = "imc-materials-live-task-v1"
OPERATION = INSTRUCTIONAL_LIVE_SUBJECT_KIND
OWNER = "instructional-materials-coach"
_PAYLOAD_KEYS = frozenset(
    {
        "contract_version",
        "operation",
        "repository",
        "authorization_issue_number",
        "subject",
        "approval_id",
        "approval_revision",
        "projection_id",
        "authorization_id",
    }
)


def _blocked(reason: str) -> dict[str, Any]:
    return {"success": False, "status": "blocked", "error": reason, "output": None}


def _failure(reason: str) -> dict[str, Any]:
    return {"success": False, "status": "fail", "error": reason, "output": None}


def _status_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw if type(raw) is str else ""


def _utc_seconds() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class InstructionalMaterialsLiveAdapter(TaskAdapter):
    """Bind one exact Scheduler request to current approval/auth and #1195."""

    accepts_execution_request = True

    def __init__(
        self,
        *,
        approval_revalidator: Callable[..., object],
        authorization_reacquirer: Callable[..., object],
        live_build_input_factory: Callable[[ExecutionRequest, Mapping[str, Any]], object],
        live_builder: Callable[..., object],
        drive_service: object,
        slides_service: object,
        docs_service: object,
        evaluated_at: Callable[[], str] = _utc_seconds,
    ) -> None:
        for value, name in (
            (approval_revalidator, "approval_revalidator"),
            (authorization_reacquirer, "authorization_reacquirer"),
            (live_build_input_factory, "live_build_input_factory"),
            (live_builder, "live_builder"),
            (evaluated_at, "evaluated_at"),
        ):
            if not callable(value):
                raise TypeError(f"{name} must be callable")
        self._approval_revalidator = approval_revalidator
        self._authorization_reacquirer = authorization_reacquirer
        self._live_build_input_factory = live_build_input_factory
        self._live_builder = live_builder
        self._drive_service = drive_service
        self._slides_service = slides_service
        self._docs_service = docs_service
        self._evaluated_at = evaluated_at

    def execute(self, request: ExecutionRequest) -> dict[str, Any]:
        if type(request) is not ExecutionRequest:
            return _failure("execution-request-required")
        if request.owner != OWNER:
            return _failure("owner-mismatch")
        if request.batch_id is not None:
            return _blocked("batching-not-authorized")
        payload = request.payload
        if type(payload) is not dict or set(payload) != _PAYLOAD_KEYS:
            return _failure("live-contract-shape-invalid")
        if payload.get("contract_version") != CONTRACT_VERSION or payload.get("operation") != OPERATION:
            return _failure("live-contract-version-or-operation-invalid")
        if type(payload.get("repository")) is not str or "/" not in payload["repository"]:
            return _failure("repository-invalid")
        if type(payload.get("authorization_issue_number")) is not int or payload["authorization_issue_number"] < 1:
            return _failure("authorization-issue-invalid")
        for key in ("approval_id", "approval_revision", "projection_id", "authorization_id"):
            if type(payload.get(key)) is not str or not payload[key]:
                return _failure(f"{key.replace('_', '-')}-invalid")
        subject = payload.get("subject")
        if type(subject) is not dict:
            return _failure("typed-subject-invalid")
        try:
            subject_ref = validate_typed_subject_reference(subject)
        except (TypeError, ValueError):
            return _failure("typed-subject-invalid")

        try:
            approval = self._approval_revalidator(
                subject=subject,
                expected_subject_id=subject_ref.subject_id,
                expected_approval_id=payload["approval_id"],
                expected_approval_revision=payload["approval_revision"],
                expected_projection_id=payload["projection_id"],
                evaluated_at=self._evaluated_at(),
            )
        except (TypeError, ValueError, RuntimeError):
            return _blocked("approval-revalidation-unavailable")
        if _status_value(getattr(approval, "status", "")) != "applicable":
            return _blocked("approval-not-current")
        if getattr(approval, "approval_id", None) != payload["approval_id"]:
            return _blocked("approval-identity-mismatch")
        if getattr(approval, "approval_revision", None) != payload["approval_revision"]:
            return _blocked("approval-revision-mismatch")
        projection = getattr(approval, "projection", None)
        projection_id = getattr(projection, "projection_id", None)
        if projection_id is None:
            projection_id = getattr(approval, "projection_id", None)
        if projection_id != payload["projection_id"]:
            return _blocked("projection-identity-mismatch")
        approved_subject = getattr(approval, "subject", None)
        if approved_subject is not None and getattr(approved_subject, "subject_id", None) != subject_ref.subject_id:
            return _blocked("approval-subject-mismatch")

        evaluated_at = self._evaluated_at()
        try:
            authorization = self._authorization_reacquirer(
                repository=payload["repository"],
                issue_number=payload["authorization_issue_number"],
                expected_subject_id=subject_ref.subject_id,
                expected_approval_id=payload["approval_id"],
                expected_approval_revision=payload["approval_revision"],
                expected_projection_id=payload["projection_id"],
                expected_run_id=request.run_id,
                expected_task_id=request.task_id,
                expected_attempt_number=request.attempt_number,
                expected_operation=OPERATION,
                evaluated_at=evaluated_at,
                expected_authorization_id=payload["authorization_id"],
            )
        except (TypeError, ValueError, RuntimeError, OSError):
            return _blocked("execution-authorization-reacquisition-unavailable")
        if _status_value(getattr(authorization, "status", "")) != "current":
            return _blocked("execution-authorization-not-current")
        evidence = getattr(authorization, "evidence", None)
        if evidence is None or getattr(evidence, "authorization_id", None) != payload["authorization_id"]:
            return _blocked("execution-authorization-identity-mismatch")
        if getattr(evidence, "authorized_subject_id", None) != subject_ref.subject_id:
            return _blocked("execution-authorization-subject-mismatch")
        if getattr(evidence, "authorized_run_id", None) != request.run_id:
            return _blocked("execution-authorization-run-mismatch")
        if getattr(evidence, "authorized_task_id", None) != request.task_id:
            return _blocked("execution-authorization-task-mismatch")
        if getattr(evidence, "authorized_attempt_number", None) != request.attempt_number:
            return _blocked("execution-authorization-attempt-mismatch")
        if getattr(evidence, "authorized_operation", None) != OPERATION:
            return _blocked("execution-authorization-operation-mismatch")
        if getattr(evidence, "execution_authorized", None) is not True:
            return _blocked("execution-authorization-not-current")

        try:
            build_input = self._live_build_input_factory(request, subject)
        except (TypeError, ValueError, RuntimeError):
            return _failure("live-build-input-invalid")

        receipt = self._live_builder(
            build_input,
            drive_service=self._drive_service,
            slides_service=self._slides_service,
            docs_service=self._docs_service,
        )
        return {
            "success": bool(getattr(receipt, "succeeded", False)),
            "status": "pass" if bool(getattr(receipt, "succeeded", False)) else "fail",
            "error": None if bool(getattr(receipt, "succeeded", False)) else "live-build-incomplete",
            "output": {
                "contract_version": CONTRACT_VERSION,
                "operation": OPERATION,
                "subject_id": subject_ref.subject_id,
                "approval_id": payload["approval_id"],
                "approval_revision": payload["approval_revision"],
                "projection_id": payload["projection_id"],
                "authorization_id": payload["authorization_id"],
                "run_id": request.run_id,
                "task_id": request.task_id,
                "attempt_number": request.attempt_number,
                "receipt": receipt,
            },
        }
