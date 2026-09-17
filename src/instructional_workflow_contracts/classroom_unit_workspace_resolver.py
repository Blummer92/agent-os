"""Pure exact-ID Classroom Unit Workspace resolver for Issue #2580.

The resolver consumes validated workspace evidence plus injected folder metadata.
It performs no Drive/network calls and grants no external-operation authority.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol

from .classroom_unit_workspace import CONTRACT_ID as WORKSPACE_CONTRACT_ID
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

CONTRACT_ID = "classroom-unit-workspace-resolution-v1"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
ROLE_OUTCOMES = frozenset(
    {"resolved", "missing", "moved", "trashed", "inaccessible", "wrong-kind", "ambiguous"}
)
OVERALL_STATES = frozenset({"resolved", "partial", "stale", "missing", "ambiguous", "manual-review"})
_AUTHORITY = {
    "execution_authorized": False,
    "external_write_authorized": False,
    "approval_authorized": False,
    "classroom_readiness_authorized": False,
    "publication_authorized": False,
    "production_authorized": False,
}


class FolderMetadataReader(Protocol):
    """Small read-only protocol; adapters may implement exact-ID metadata lookup."""

    def get_folder_metadata(self, drive_folder_id: str) -> Mapping[str, Any] | None: ...


def resolve_classroom_unit_workspace(
    workspace: ValidatedRecord,
    reader: FolderMetadataReader,
) -> ValidationResult:
    """Resolve exact workspace folder IDs against current injected metadata."""
    try:
        source = _validated_workspace(workspace)
        source_payload = source.to_dict()
        bindings = source_payload["role_bindings"]
        root_binding = next(item for item in bindings if item["role"] == "unit-root")
        root_id = root_binding["drive_folder_id"]
        root_resolution = _resolve_known_binding(root_binding, reader, expected_parent=None)

        role_resolutions = []
        for binding in bindings:
            if binding["role"] == "unit-root":
                role_resolutions.append(root_resolution)
                continue
            if binding["drive_folder_id"] is None:
                role_resolutions.append(
                    {
                        "role": binding["role"],
                        "outcome": "missing" if binding["state"] == "missing" else "ambiguous",
                        "drive_folder_id": None,
                        "current_parent_folder_id": None,
                        "current_display_name": binding["display_name"],
                        "metadata_fingerprint": None,
                    }
                )
                continue
            role_resolutions.append(_resolve_known_binding(binding, reader, expected_parent=root_id))

        overall, status, reasons = _overall(role_resolutions)
        payload = {
            "contract_version": CONTRACT_ID,
            "resolution_id": validate_stable_id(
                "classroom-unit-workspace-resolution-"
                + sha256_hex(
                    {
                        "workspace_id": source.record_id,
                        "workspace_fingerprint": source.fingerprint,
                        "roles": role_resolutions,
                    }
                )[:24],
                "resolution_id",
            ),
            "source_workspace": {
                "contract_version": source.contract_version,
                "workspace_id": source.record_id,
                "record_revision": source.record_revision,
                "fingerprint": source.fingerprint,
            },
            "overall_state": overall,
            "role_resolutions": sorted(role_resolutions, key=lambda item: item["role"]),
            "authority": dict(_AUTHORITY),
        }
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict or canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError("destination-workspace-resolution-oversized", "resolution exceeds result-size bound")
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=payload["resolution_id"],
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
        return invalid_result("destination-workspace-resolution-invalid", sanitize_detail(str(exc)))


def _validated_workspace(value: object) -> ValidatedRecord:
    if type(value) is not ValidatedRecord or value.contract_version != WORKSPACE_CONTRACT_ID:
        raise ContractValidationError("destination-workspace-resolution-source-invalid", "validated workspace evidence is required")
    payload = value.to_dict()
    if payload.get("contract_version") != WORKSPACE_CONTRACT_ID or payload.get("workspace_id") != value.record_id:
        raise ContractValidationError("identity-invalid", "workspace identity is invalid")
    if sha256_hex(payload) != value.fingerprint:
        raise ContractValidationError("identity-invalid", "workspace fingerprint does not reconstruct")
    authority = payload.get("authority")
    if type(authority) is not dict or any(authority.values()):
        raise ContractValidationError("authority-invalid", "workspace authority must remain false")
    return value


def _resolve_known_binding(
    binding: Mapping[str, Any],
    reader: FolderMetadataReader,
    *,
    expected_parent: str | None,
) -> dict[str, Any]:
    folder_id = validate_stable_id(binding["drive_folder_id"], "drive_folder_id")
    raw = reader.get_folder_metadata(folder_id)
    if raw is None:
        return _role(binding, "missing")
    if type(raw) is not dict and not isinstance(raw, Mapping):
        raise ContractValidationError("destination-workspace-metadata-invalid", "folder metadata must be a mapping")
    metadata = dict(raw)
    if metadata.get("drive_folder_id") != folder_id:
        return _role(binding, "ambiguous")
    if metadata.get("accessible") is False:
        return _role(binding, "inaccessible", metadata)
    if metadata.get("trashed") is True:
        return _role(binding, "trashed", metadata)
    if metadata.get("mime_type") != FOLDER_MIME_TYPE:
        return _role(binding, "wrong-kind", metadata)
    parent = metadata.get("parent_folder_id")
    if parent is not None:
        parent = validate_stable_id(parent, "current_parent_folder_id")
    if expected_parent is not None and parent != expected_parent:
        return _role(binding, "moved", metadata)
    return _role(binding, "resolved", metadata)


def _role(binding: Mapping[str, Any], outcome: str, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if outcome not in ROLE_OUTCOMES:
        raise ContractValidationError("destination-workspace-resolution-outcome-invalid", "unsupported role outcome")
    metadata = dict(metadata or {})
    folder_id = binding.get("drive_folder_id")
    current_name = metadata.get("display_name")
    if current_name is not None and (type(current_name) is not str or not current_name.strip()):
        raise ContractValidationError("destination-workspace-metadata-invalid", "current display name is invalid")
    evidence = None
    if metadata:
        safe_metadata = {
            "drive_folder_id": metadata.get("drive_folder_id"),
            "parent_folder_id": metadata.get("parent_folder_id"),
            "display_name": current_name.strip() if type(current_name) is str else None,
            "mime_type": metadata.get("mime_type"),
            "trashed": metadata.get("trashed"),
            "accessible": metadata.get("accessible"),
        }
        evidence = sha256_hex(safe_metadata)
    return {
        "role": binding["role"],
        "outcome": outcome,
        "drive_folder_id": folder_id,
        "current_parent_folder_id": metadata.get("parent_folder_id"),
        "current_display_name": current_name.strip() if type(current_name) is str else binding.get("display_name"),
        "metadata_fingerprint": evidence,
    }


def _overall(roles: list[dict[str, Any]]) -> tuple[str, ValidationStatus, list[str]]:
    outcomes = {item["outcome"] for item in roles}
    root = next(item for item in roles if item["role"] == "unit-root")
    if "ambiguous" in outcomes:
        return "ambiguous", ValidationStatus.MANUAL_REVIEW_REQUIRED, ["destination-workspace-resolution-ambiguous"]
    if root["outcome"] != "resolved":
        return "missing", ValidationStatus.MANUAL_REVIEW_REQUIRED, [f"destination-workspace-root-{root['outcome']}"]
    drift = outcomes & {"moved", "trashed", "inaccessible", "wrong-kind"}
    if drift:
        return "stale", ValidationStatus.MANUAL_REVIEW_REQUIRED, ["destination-workspace-resolution-drift"]
    if "missing" in outcomes:
        # Intentionally lazy roles are not a defect, so this stays VALID. The shared
        # ValidationResult contract forbids reasons/blockers on a valid result, so the
        # partial signal is carried by ``overall_state`` rather than a reason code.
        return "partial", ValidationStatus.VALID, []
    return "resolved", ValidationStatus.VALID, []


def _reason_detail(reason: str) -> str:
    return {
        "destination-workspace-resolution-ambiguous": "one or more exact-ID metadata results are contradictory",
        "destination-workspace-resolution-drift": "one or more known role folders have structural/currentness drift",
    }.get(reason, "unit-root exact-ID verification did not resolve to a current folder")
