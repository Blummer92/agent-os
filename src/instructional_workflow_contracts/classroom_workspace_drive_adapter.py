"""Provider-thin Classroom Workspace Drive adapter for Issue #2614.

The module contains no Google client.  It normalizes exact-ID metadata for the
existing DRIVE2 resolver and can exercise one DRIVE3 create-folder operation
through an injected client.  Live execution remains separately authorized.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

from .classroom_unit_workspace_resolver import FOLDER_MIME_TYPE
from .classroom_workspace_provisioner import CONTRACT_ID as PLAN_CONTRACT_ID
from .common import ValidatedRecord, sha256_hex, validate_stable_id


class WorkspaceDriveState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PRECHECK_FAILED = "PRECHECK_FAILED"
    NO_OP = "NO_OP"
    CREATED_VERIFIED = "CREATED_VERIFIED"
    RECONCILED_EXISTING = "RECONCILED_EXISTING"
    AMBIGUOUS_WRITE_RESULT = "AMBIGUOUS_WRITE_RESULT"
    READBACK_FAILED = "READBACK_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class WorkspaceDriveResult:
    state: WorkspaceDriveState
    plan_id: str | None
    operation_id: str | None
    semantic_role: str | None
    parent_folder_id: str | None
    folder_id: str | None
    reason_codes: tuple[str, ...]
    readback_verified: bool = False
    external_write_performed: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    publication_authorized: bool = False
    production_authorized: bool = False


class WorkspaceDriveClient(Protocol):
    """Minimal provider protocol implemented by a future authorized connector adapter."""

    def get_file_metadata(self, file_id: str) -> Mapping[str, Any] | None: ...
    def create_folder(self, *, name: str, parent_folder_id: str, operation_id: str) -> str: ...
    def find_created_folder(self, *, operation_id: str, parent_folder_id: str) -> tuple[str, ...]: ...


class DriveFolderMetadataReader:
    """Adapt provider metadata to the existing DRIVE2 FolderMetadataReader shape."""

    def __init__(self, client: WorkspaceDriveClient):
        self._client = client

    def get_folder_metadata(self, drive_folder_id: str) -> Mapping[str, Any] | None:
        requested = validate_stable_id(drive_folder_id, "drive_folder_id")
        raw = self._client.get_file_metadata(requested)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            return {"drive_folder_id": requested, "accessible": False}
        provider = dict(raw)
        returned = provider.get("id")
        if returned != requested:
            return {"drive_folder_id": returned, "accessible": True}
        parents = provider.get("parents", [])
        if parents is None:
            parents = []
        if type(parents) is not list or any(type(item) is not str or not item.strip() for item in parents):
            return {"drive_folder_id": requested, "accessible": False}
        if len(parents) > 1:
            # DRIVE2 treats an ID mismatch as ambiguous.  Use a deliberately
            # contradictory identity rather than guessing one parent.
            return {"drive_folder_id": requested + "-ambiguous-parent", "accessible": True}
        name = provider.get("name")
        if name is not None and (type(name) is not str or not name.strip()):
            return {"drive_folder_id": requested, "accessible": False}
        return {
            "drive_folder_id": requested,
            "parent_folder_id": parents[0] if parents else None,
            "display_name": name.strip() if type(name) is str else None,
            "mime_type": provider.get("mimeType"),
            "trashed": provider.get("trashed", False) is True,
            "accessible": True,
        }


def execute_workspace_create(
    plan: ValidatedRecord,
    operation_id: str,
    *,
    client: WorkspaceDriveClient | None = None,
    dry_run: bool = True,
) -> WorkspaceDriveResult:
    """Dry-run or execute one validated DRIVE3 create-folder operation."""
    operation = _validated_operation(plan, operation_id)
    if operation is None:
        return _result(WorkspaceDriveState.PRECHECK_FAILED, None, None, ("workspace-drive-plan-or-operation-invalid",))
    plan_payload = plan.to_dict()
    plan_id = plan.record_id
    role = operation["semantic_role"]
    parent = operation.get("parent_folder_id")
    if operation["operation_type"] == "no-op":
        return _result(WorkspaceDriveState.NO_OP, plan_id, operation, ("workspace-drive-operation-no-op",))
    if operation["operation_type"] in {"manual-review", "blocked"}:
        return _result(WorkspaceDriveState.MANUAL_REVIEW_REQUIRED, plan_id, operation, ("workspace-drive-operation-not-executable",))
    if operation["operation_type"] != "create-folder" or type(parent) is not str:
        return _result(WorkspaceDriveState.PRECHECK_FAILED, plan_id, operation, ("workspace-drive-operation-invalid",))
    if dry_run:
        return _result(WorkspaceDriveState.DRY_RUN, plan_id, operation, ("workspace-drive-dry-run-valid",))
    if client is None:
        return _result(WorkspaceDriveState.PRECHECK_FAILED, plan_id, operation, ("workspace-drive-client-required",))

    # Exact parent is re-read immediately before any possible create.
    root = DriveFolderMetadataReader(client).get_folder_metadata(parent)
    if not _current_folder(root, expected_id=parent, expected_parent=None):
        return _result(WorkspaceDriveState.PRECHECK_FAILED, plan_id, operation, ("workspace-drive-parent-not-current",))

    existing = client.find_created_folder(operation_id=operation_id, parent_folder_id=parent)
    if len(existing) > 1:
        return _result(WorkspaceDriveState.MANUAL_REVIEW_REQUIRED, plan_id, operation, ("workspace-drive-existing-ambiguous",))
    if len(existing) == 1:
        evidence = DriveFolderMetadataReader(client).get_folder_metadata(existing[0])
        if _current_folder(evidence, expected_id=existing[0], expected_parent=parent):
            return _result(WorkspaceDriveState.RECONCILED_EXISTING, plan_id, operation, ("workspace-drive-existing-verified",), folder_id=existing[0], readback=True)
        return _result(WorkspaceDriveState.READBACK_FAILED, plan_id, operation, ("workspace-drive-existing-readback-failed",), folder_id=existing[0])

    try:
        folder_id = client.create_folder(name=operation["display_name"], parent_folder_id=parent, operation_id=operation_id)
    except Exception:
        reconciled = client.find_created_folder(operation_id=operation_id, parent_folder_id=parent)
        if len(reconciled) == 1:
            evidence = DriveFolderMetadataReader(client).get_folder_metadata(reconciled[0])
            if _current_folder(evidence, expected_id=reconciled[0], expected_parent=parent):
                return _result(WorkspaceDriveState.RECONCILED_EXISTING, plan_id, operation, ("workspace-drive-create-reconciled",), folder_id=reconciled[0], readback=True, wrote=True)
        return _result(WorkspaceDriveState.AMBIGUOUS_WRITE_RESULT, plan_id, operation, ("workspace-drive-create-outcome-ambiguous",), wrote=True)

    if type(folder_id) is not str or not folder_id.strip():
        return _result(WorkspaceDriveState.AMBIGUOUS_WRITE_RESULT, plan_id, operation, ("workspace-drive-create-id-missing",), wrote=True)
    evidence = DriveFolderMetadataReader(client).get_folder_metadata(folder_id)
    if not _current_folder(evidence, expected_id=folder_id, expected_parent=parent):
        return _result(WorkspaceDriveState.READBACK_FAILED, plan_id, operation, ("workspace-drive-create-readback-failed",), folder_id=folder_id, wrote=True)
    return _result(WorkspaceDriveState.CREATED_VERIFIED, plan_id, operation, ("workspace-drive-create-verified",), folder_id=folder_id, readback=True, wrote=True)


def _validated_operation(plan: object, operation_id: str) -> dict[str, Any] | None:
    if type(plan) is not ValidatedRecord or plan.contract_version != PLAN_CONTRACT_ID:
        return None
    payload = plan.to_dict()
    if payload.get("contract_version") != PLAN_CONTRACT_ID or payload.get("plan_id") != plan.record_id:
        return None
    if sha256_hex(payload) != plan.fingerprint or any(payload.get("authority", {}).values()):
        return None
    try:
        wanted = validate_stable_id(operation_id, "operation_id")
    except Exception:
        return None
    matches = [item for item in payload.get("operations", []) if type(item) is dict and item.get("operation_id") == wanted]
    if len(matches) != 1:
        return None
    operation = matches[0]
    basis = {
        "workspace_id": payload["source_workspace"]["workspace_id"],
        "semantic_role": operation.get("semantic_role"),
        "parent_folder_id": operation.get("parent_folder_id"),
        "operation_type": operation.get("operation_type"),
    }
    expected_id = "workspace-operation-" + sha256_hex(basis)[:24]
    if expected_id != wanted:
        return None
    expected_fingerprint = sha256_hex(
        {
            "identity": basis,
            "display_name": operation.get("display_name"),
            "current_drive_folder_id": operation.get("current_drive_folder_id"),
            "outcome": operation.get("preconditions", {}).get("role_outcome_must_remain"),
        }
    )
    if operation.get("operation_fingerprint") != expected_fingerprint:
        return None
    return operation


def _current_folder(metadata: Mapping[str, Any] | None, *, expected_id: str, expected_parent: str | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    if metadata.get("drive_folder_id") != expected_id or metadata.get("accessible") is not True:
        return False
    if metadata.get("trashed") is True or metadata.get("mime_type") != FOLDER_MIME_TYPE:
        return False
    if expected_parent is not None and metadata.get("parent_folder_id") != expected_parent:
        return False
    return True


def _result(state, plan_id, operation, reasons, *, folder_id=None, readback=False, wrote=False):
    return WorkspaceDriveResult(
        state=state,
        plan_id=plan_id,
        operation_id=operation.get("operation_id") if operation else None,
        semantic_role=operation.get("semantic_role") if operation else None,
        parent_folder_id=operation.get("parent_folder_id") if operation else None,
        folder_id=folder_id,
        reason_codes=tuple(reasons),
        readback_verified=readback,
        external_write_performed=wrote,
    )
