"""Pure Classroom Workspace provisioning planner for Issue #2582.

The planner consumes validated workspace and resolution evidence and emits a
non-authorizing deterministic mutation plan. It performs no external operations.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .classroom_unit_workspace import (
    CONTRACT_ID as WORKSPACE_CONTRACT_ID,
    WORKSPACE_ROLES,
)
from .classroom_unit_workspace_resolver import (
    CONTRACT_ID as RESOLUTION_CONTRACT_ID,
)
from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    invalid_result,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_stable_id,
)

CONTRACT_ID = "classroom-workspace-provisioning-plan-v1"
OPERATION_TYPES = frozenset({"no-op", "create-folder", "manual-review", "blocked"})
DEFAULT_ROLE_DISPLAY_NAMES = {
    "slides": "Slides",
    "student-materials": "Student Materials",
    "teacher-models": "Teacher Models",
    "visual-assets": "Visual Assets",
    "assessment": "Assessment",
    "teacher-reference": "Teacher Reference",
}
_AUTHORITY = {
    "execution_authorized": False,
    "external_write_authorized": False,
    "approval_authorized": False,
    "classroom_readiness_authorized": False,
    "publication_authorized": False,
    "production_authorized": False,
}


def plan_classroom_workspace_provisioning(
    workspace: ValidatedRecord,
    resolution: ValidatedRecord,
    requested_roles: Sequence[str],
    *,
    display_name_overrides: Mapping[str, str] | None = None,
) -> ValidationResult:
    """Plan exact-parent semantic-role folder provisioning without executing it."""
    try:
        workspace_record = _validated_record(workspace, WORKSPACE_CONTRACT_ID, "workspace")
        resolution_record = _validated_record(resolution, RESOLUTION_CONTRACT_ID, "resolution")
        resolution_payload = resolution_record.to_dict()
        _validate_lineage(workspace_record, resolution_payload)

        roles = _requested_roles(requested_roles)
        overrides = _display_overrides(display_name_overrides or {}, roles)
        role_resolutions = {item["role"]: item for item in resolution_payload["role_resolutions"]}
        root = role_resolutions.get("unit-root")
        if type(root) is not dict:
            raise ContractValidationError("destination-workspace-plan-root-invalid", "unit-root resolution is required")
        root_id = root.get("drive_folder_id")
        root_healthy = root.get("outcome") == "resolved" and type(root_id) is str

        operations = []
        for role in roles:
            current = role_resolutions.get(role)
            if type(current) is not dict:
                raise ContractValidationError("destination-workspace-plan-role-missing", "requested role is absent from resolver evidence")
            operations.append(
                _operation(
                    workspace_record.record_id,
                    role,
                    current,
                    root_id if type(root_id) is str else None,
                    root_healthy=root_healthy,
                    display_name=overrides.get(role, DEFAULT_ROLE_DISPLAY_NAMES[role]),
                )
            )

        overall, status, reasons = _overall(operations, root_healthy=root_healthy)
        plan_basis = {
            "workspace_id": workspace_record.record_id,
            "workspace_fingerprint": workspace_record.fingerprint,
            "resolution_id": resolution_record.record_id,
            "resolution_fingerprint": resolution_record.fingerprint,
            "requested_roles": roles,
            "operations": operations,
        }
        payload = {
            "contract_version": CONTRACT_ID,
            "plan_id": validate_stable_id(
                "classroom-workspace-plan-" + sha256_hex(plan_basis)[:24],
                "plan_id",
            ),
            "source_workspace": {
                "workspace_id": workspace_record.record_id,
                "fingerprint": workspace_record.fingerprint,
            },
            "source_resolution": {
                "resolution_id": resolution_record.record_id,
                "fingerprint": resolution_record.fingerprint,
            },
            "unit_root_folder_id": root_id if root_healthy else None,
            "requested_roles": roles,
            "overall_state": overall,
            "operations": operations,
            "authority": dict(_AUTHORITY),
        }
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict or canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError("destination-workspace-plan-oversized", "provisioning plan exceeds result-size bound")
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=payload["plan_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        return ValidationResult(
            status=status,
            record=record,
            reason_codes=tuple(reasons),
            details=tuple(_reason_detail(reason) for reason in reasons),
        )
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("destination-workspace-plan-invalid", sanitize_detail(str(exc)))


def _validated_record(value: object, contract_id: str, label: str) -> ValidatedRecord:
    if type(value) is not ValidatedRecord or value.contract_version != contract_id:
        raise ContractValidationError(f"destination-workspace-plan-{label}-invalid", f"validated {label} evidence is required")
    payload = value.to_dict()
    identity_field = "workspace_id" if label == "workspace" else "resolution_id"
    if payload.get("contract_version") != contract_id or payload.get(identity_field) != value.record_id:
        raise ContractValidationError("identity-invalid", f"{label} identity is invalid")
    if sha256_hex(payload) != value.fingerprint:
        raise ContractValidationError("identity-invalid", f"{label} fingerprint does not reconstruct")
    authority = payload.get("authority")
    if type(authority) is not dict or any(authority.values()):
        raise ContractValidationError("authority-invalid", f"{label} authority must remain false")
    return value


def _validate_lineage(workspace: ValidatedRecord, resolution_payload: dict) -> None:
    source = resolution_payload.get("source_workspace")
    if type(source) is not dict:
        raise ContractValidationError("destination-workspace-plan-lineage-invalid", "resolution source workspace is missing")
    if source.get("workspace_id") != workspace.record_id or source.get("fingerprint") != workspace.fingerprint:
        raise ContractValidationError("destination-workspace-plan-lineage-mismatch", "resolver evidence does not match workspace")


def _requested_roles(value: Sequence[str]) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ContractValidationError("destination-workspace-plan-roles-invalid", "requested_roles must be a non-empty sequence")
    roles = []
    for role in value:
        if role == "unit-root" or role not in WORKSPACE_ROLES or role not in DEFAULT_ROLE_DISPLAY_NAMES:
            raise ContractValidationError("destination-workspace-plan-role-unsupported", "requested semantic role is unsupported")
        if role in roles:
            raise ContractValidationError("destination-workspace-plan-role-duplicate", "requested semantic role is duplicated")
        roles.append(role)
    return sorted(roles)


def _display_overrides(value: Mapping[str, str], requested_roles: list[str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("destination-workspace-plan-display-overrides-invalid", "display-name overrides must be a mapping")
    result = {}
    for role, name in value.items():
        if role not in requested_roles:
            raise ContractValidationError("destination-workspace-plan-display-override-role-invalid", "override role was not requested")
        if type(name) is not str or not name.strip() or len(name) > 256:
            raise ContractValidationError("destination-workspace-plan-display-name-invalid", "display-name override is invalid")
        result[role] = name.strip()
    return result


def _operation(
    workspace_id: str,
    role: str,
    current: dict,
    root_id: str | None,
    *,
    root_healthy: bool,
    display_name: str,
) -> dict:
    outcome = current.get("outcome")
    if not root_healthy:
        operation_type = "blocked"
        reason = "destination-workspace-plan-root-not-current"
    elif outcome == "resolved":
        operation_type = "no-op"
        reason = "destination-workspace-role-already-current"
    elif outcome == "missing":
        operation_type = "create-folder"
        reason = "destination-workspace-role-folder-missing"
    elif outcome in {"moved", "ambiguous"}:
        operation_type = "manual-review"
        reason = f"destination-workspace-role-{outcome}"
    elif outcome in {"trashed", "inaccessible", "wrong-kind"}:
        operation_type = "blocked"
        reason = f"destination-workspace-role-{outcome}"
    else:
        operation_type = "blocked"
        reason = "destination-workspace-role-state-unsupported"

    identity_basis = {
        "workspace_id": workspace_id,
        "semantic_role": role,
        "parent_folder_id": root_id,
        "operation_type": operation_type,
    }
    operation_id = validate_stable_id(
        "workspace-operation-" + sha256_hex(identity_basis)[:24],
        "operation_id",
    )
    return {
        "operation_id": operation_id,
        "operation_type": operation_type,
        "semantic_role": role,
        "display_name": display_name,
        "parent_folder_id": root_id if root_healthy else None,
        "current_drive_folder_id": current.get("drive_folder_id"),
        "preconditions": {
            "unit_root_must_remain_exact": root_id if root_healthy else None,
            "role_outcome_must_remain": outcome,
        },
        "expected_postconditions": {
            "semantic_role": role,
            "parent_folder_id": root_id if root_healthy else None,
            "resource_kind": "folder",
            "requires_exact_id_readback": operation_type == "create-folder",
        },
        "reason_code": reason,
        "operation_fingerprint": sha256_hex(
            {
                "identity": identity_basis,
                "display_name": display_name,
                "current_drive_folder_id": current.get("drive_folder_id"),
                "outcome": outcome,
            }
        ),
    }


def _overall(operations: list[dict], *, root_healthy: bool) -> tuple[str, ValidationStatus, list[str]]:
    if not root_healthy:
        return "blocked", ValidationStatus.MANUAL_REVIEW_REQUIRED, ["destination-workspace-plan-root-not-current"]
    kinds = {item["operation_type"] for item in operations}
    if "blocked" in kinds:
        return "blocked", ValidationStatus.MANUAL_REVIEW_REQUIRED, ["destination-workspace-plan-blocked"]
    if "manual-review" in kinds:
        return "manual-review", ValidationStatus.MANUAL_REVIEW_REQUIRED, ["destination-workspace-plan-review-required"]
    if "create-folder" in kinds:
        return "planned", ValidationStatus.VALID, []
    return "no-op", ValidationStatus.VALID, []


def _reason_detail(reason: str) -> str:
    return {
        "destination-workspace-plan-root-not-current": "unit-root must be currently resolved before child provisioning can be planned",
        "destination-workspace-plan-blocked": "one or more requested roles are unsafe to provision automatically",
        "destination-workspace-plan-review-required": "one or more requested roles require bounded manual review",
    }.get(reason, "workspace provisioning plan requires review")
