"""Pure normalization and fail-closed selection for approved visual asset rows."""
from __future__ import annotations

import dataclasses
from typing import Any

CLEARED_PERMISSIONS = {"cleared-internal", "licensed", "public-domain", "permission-documented"}
APPROVED_STATES = {"approved", "ready"}


@dataclasses.dataclass(frozen=True)
class NormalizedAsset:
    asset_id: str
    asset_name: str
    drive_file_id: str
    asset_type: str
    unit: str
    lesson_use_case: str
    student_facing: bool
    teacher_facing: bool
    approval_status: str
    permission_status: str
    duplicate_status: str
    disposition: str
    canonical_asset_ref: str | None

    @property
    def drive_uri(self) -> str:
        return f"https://drive.google.com/uc?export=download&id={self.drive_file_id}"


def _required_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"asset metadata missing required field: {key}")
    return value.strip()


def _required_bool(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise ValueError(f"asset metadata field must be boolean: {key}")
    return value


def normalize_asset_row(row: dict[str, Any]) -> NormalizedAsset:
    """Normalize one canonical asset-sheet row without performing I/O or inventing values."""
    if type(row) is not dict:
        raise ValueError("asset metadata row must be a mapping")
    duplicate_status = _required_text(row, "Duplicate Status")
    canonical_ref = row.get("Canonical Asset ID")
    if canonical_ref is not None and (not isinstance(canonical_ref, str) or not canonical_ref.strip()):
        raise ValueError("Canonical Asset ID must be non-empty when supplied")
    disposition = _required_text(row, "Disposition")
    return NormalizedAsset(
        asset_id=_required_text(row, "Asset ID"),
        asset_name=_required_text(row, "Asset Name"),
        drive_file_id=_required_text(row, "Drive File ID"),
        asset_type=_required_text(row, "Asset Type"),
        unit=_required_text(row, "Best-Fit Unit"),
        lesson_use_case=_required_text(row, "Lesson / Use Case"),
        student_facing=_required_bool(row, "Student-Facing?"),
        teacher_facing=_required_bool(row, "Teacher-Facing?"),
        approval_status=_required_text(row, "Approval Status"),
        permission_status=_required_text(row, "Source / Permission Status"),
        duplicate_status=duplicate_status,
        disposition=disposition,
        canonical_asset_ref=None if canonical_ref is None else canonical_ref.strip(),
    )


def authorize_reuse(asset: NormalizedAsset) -> tuple[bool, tuple[str, ...]]:
    """Return fail-closed evidence compatible with existing reuse-planner safety semantics."""
    reasons: list[str] = []
    if asset.approval_status.lower() not in APPROVED_STATES:
        reasons.append("asset-not-approved")
    if asset.permission_status.lower() not in CLEARED_PERMISSIONS:
        reasons.append("asset-rights-review-required")
    if asset.duplicate_status.lower() == "unknown":
        reasons.append("asset-duplicate-evidence-ambiguous")
    if asset.disposition.lower() == "archive-candidate":
        reasons.append("asset-archive-candidate-rejected")
    if asset.disposition.lower() == "alternate" and not asset.canonical_asset_ref:
        reasons.append("asset-missing-canonical-reference")
    if asset.disposition.lower() not in {"canonical", "alternate"}:
        reasons.append("asset-manual-review-required")
    return not reasons, tuple(sorted(set(reasons)))
