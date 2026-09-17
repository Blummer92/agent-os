"""Pure ID-backed Classroom Unit Workspace contract for Issue #2575.

This module represents semantic classroom workspace roles and exact Google Drive
folder identity. It performs no Drive/Notion calls and grants no execution,
external-write, approval, readiness, publication, or production authority.
"""
from __future__ import annotations

from typing import Any

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

CONTRACT_ID = "classroom-unit-workspace-v1"
WORKSPACE_ROLES = frozenset(
    {
        "unit-root",
        "slides",
        "student-materials",
        "teacher-models",
        "visual-assets",
        "assessment",
        "teacher-reference",
    }
)
BINDING_STATES = frozenset({"resolved", "unverified", "stale", "missing", "ambiguous"})
_AUTHORITY = {
    "execution_authorized": False,
    "external_write_authorized": False,
    "approval_authorized": False,
    "classroom_readiness_authorized": False,
    "publication_authorized": False,
    "production_authorized": False,
}


def validate_classroom_unit_workspace(value: object) -> ValidationResult:
    """Validate one non-authorizing unit workspace and issue stable identity."""
    try:
        payload = validate_and_normalize_json(value, max_bytes=MAX_RESULT_BYTES)
        if type(payload) is not dict:
            raise ContractValidationError("workspace-invalid", "workspace must be an object")
        if payload.get("contract_version") != CONTRACT_ID:
            raise ContractValidationError("workspace-version-invalid", "unsupported workspace contract")

        course_ref = validate_stable_id(payload.get("course_ref"), "course_ref")
        unit_ref = validate_stable_id(payload.get("unit_ref"), "unit_ref")
        display_name = _optional_text(payload.get("display_name"), "display_name")
        bindings = _validate_bindings(payload.get("role_bindings"))
        _validate_binding_relationships(bindings)

        root = next((item for item in bindings if item["role"] == "unit-root"), None)
        if root is None or root["state"] in {"missing", "ambiguous"} or root["drive_folder_id"] is None:
            raise ContractValidationError(
                "workspace-root-invalid", "unit-root must identify one exact Drive folder"
            )
        for item in bindings:
            if item["role"] != "unit-root" and item["drive_folder_id"] is not None:
                parent = item["parent_folder_id"]
                if parent is not None and parent != root["drive_folder_id"]:
                    raise ContractValidationError(
                        "workspace-parent-contradiction",
                        "resolved child role parent must match the unit-root folder",
                    )

        canonical = {
            "contract_version": CONTRACT_ID,
            "workspace_id": validate_stable_id(
                "classroom-unit-workspace-"
                + sha256_hex({"course_ref": course_ref, "unit_ref": unit_ref})[:24],
                "workspace_id",
            ),
            "course_ref": course_ref,
            "unit_ref": unit_ref,
            "display_name": display_name,
            "role_bindings": bindings,
            "authority": dict(_AUTHORITY),
        }
        normalized = validate_and_normalize_json(canonical, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict or canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError("workspace-oversized", "workspace exceeds result-size bound")
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=canonical["workspace_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        status = _workspace_status(bindings)
        reasons: tuple[str, ...] = ()
        details: tuple[str, ...] = ()
        if status is ValidationStatus.MANUAL_REVIEW_REQUIRED:
            reasons = ("workspace-role-review-required",)
            details = ("one or more semantic folder roles require bounded review",)
        return ValidationResult(status=status, record=record, reason_codes=reasons, details=details)
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("workspace-invalid", sanitize_detail(str(exc)))


def _validate_bindings(value: object) -> list[dict[str, Any]]:
    if type(value) is not list or not value:
        raise ContractValidationError("workspace-bindings-invalid", "role_bindings must be a non-empty list")
    result: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for raw in value:
        if type(raw) is not dict:
            raise ContractValidationError("workspace-binding-invalid", "role binding must be an object")
        role = raw.get("role")
        state = raw.get("state")
        if role not in WORKSPACE_ROLES:
            raise ContractValidationError("workspace-role-unsupported", "role is unsupported")
        if role in seen_roles:
            raise ContractValidationError("workspace-role-duplicate", "semantic role is bound more than once")
        seen_roles.add(role)
        if state not in BINDING_STATES:
            raise ContractValidationError("workspace-binding-state-invalid", "binding state is unsupported")
        folder_id = _optional_stable_id(raw.get("drive_folder_id"), "drive_folder_id")
        parent_id = _optional_stable_id(raw.get("parent_folder_id"), "parent_folder_id")
        display_name = _optional_text(raw.get("display_name"), "binding.display_name")
        last_verified = _optional_text(raw.get("last_verified"), "last_verified")
        if state in {"resolved", "unverified", "stale"} and folder_id is None:
            raise ContractValidationError("workspace-folder-id-missing", "binding state requires exact Drive folder ID")
        if state in {"missing", "ambiguous"} and folder_id is not None:
            raise ContractValidationError("workspace-binding-contradiction", "missing/ambiguous role cannot claim exact folder identity")
        if state == "resolved" and last_verified is None:
            raise ContractValidationError("workspace-currentness-missing", "resolved binding requires verification evidence")
        result.append(
            {
                "role": role,
                "state": state,
                "drive_folder_id": folder_id,
                "parent_folder_id": parent_id,
                "display_name": display_name,
                "last_verified": last_verified,
            }
        )
    return sorted(result, key=lambda item: item["role"])


def _validate_binding_relationships(bindings: list[dict[str, Any]]) -> None:
    identities: dict[str, str] = {}
    for item in bindings:
        folder_id = item["drive_folder_id"]
        if folder_id is None:
            continue
        other = identities.get(folder_id)
        if other is not None and other != item["role"]:
            raise ContractValidationError(
                "workspace-folder-identity-conflict",
                "one Drive folder ID cannot satisfy multiple semantic roles",
            )
        identities[folder_id] = item["role"]


def _workspace_status(bindings: list[dict[str, Any]]) -> ValidationStatus:
    if any(item["state"] == "ambiguous" for item in bindings):
        return ValidationStatus.MANUAL_REVIEW_REQUIRED
    return ValidationStatus.VALID


def _optional_stable_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    return validate_stable_id(value, field)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip() or len(value) > 512:
        raise ContractValidationError("workspace-text-invalid", f"{field} is invalid")
    return value.strip()
