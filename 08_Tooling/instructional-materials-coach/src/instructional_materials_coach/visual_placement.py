"""Fail-closed contracts for exact reusable-visual placement.

This module is pure repository-side planning/verification. It performs no
Workspace calls and grants no external-write authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

_MARKER_RE = re.compile(r"^\{\{visual:([a-z0-9][a-z0-9-]{2,127})\}\}$")
_SUPPORTED_ARTIFACTS = frozenset({"docs", "slides"})


class VisualPlacementError(ValueError):
    """Raised when placement evidence is missing, ambiguous, or contradictory."""


@dataclass(frozen=True)
class PlacementTarget:
    artifact_type: str
    artifact_id: str
    role_id: str
    marker: str
    container_id: str
    element_id: str
    index: int | None = None
    bounds: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PlacementRequest:
    asset_id: str
    drive_file_id: str
    role_id: str
    source_plan_id: str
    target: PlacementTarget


@dataclass(frozen=True)
class PlacementReceipt:
    asset_id: str
    drive_file_id: str
    role_id: str
    artifact_type: str
    artifact_id: str
    marker: str
    container_id: str
    inserted_element_id: str
    state: str


def marker_for_role(role_id: str) -> str:
    role = _required_id(role_id, "role_id")
    marker = "{{visual:" + role + "}}"
    if not _MARKER_RE.fullmatch(marker):
        raise VisualPlacementError("role_id cannot be represented by the controlled visual marker syntax")
    return marker


def parse_marker(value: object) -> str:
    if not isinstance(value, str):
        raise VisualPlacementError("visual marker must be a string")
    match = _MARKER_RE.fullmatch(value)
    if match is None:
        raise VisualPlacementError("unsupported or malformed visual marker")
    return match.group(1)


def resolve_exact_target(
    *,
    artifact_type: str,
    artifact_id: str,
    role_id: str,
    matches: Iterable[Mapping[str, Any]],
) -> PlacementTarget:
    """Resolve exactly one pre-discovered controlled marker match."""
    kind = str(artifact_type).strip().lower()
    if kind not in _SUPPORTED_ARTIFACTS:
        raise VisualPlacementError("unsupported placement artifact type")
    artifact = _required_id(artifact_id, "artifact_id")
    role = _required_id(role_id, "role_id")
    expected_marker = marker_for_role(role)
    candidates = list(matches)
    if len(candidates) != 1:
        raise VisualPlacementError("visual placement requires exactly one marker match")
    raw = candidates[0]
    if not isinstance(raw, Mapping):
        raise VisualPlacementError("marker match must be a mapping")
    if raw.get("marker") != expected_marker:
        raise VisualPlacementError("marker match does not bind the requested role")
    if parse_marker(raw.get("marker")) != role:
        raise VisualPlacementError("marker role identity mismatch")
    container_id = _required_id(raw.get("container_id"), "container_id")
    element_id = _required_id(raw.get("element_id"), "element_id")
    index = raw.get("index")
    if index is not None and (not isinstance(index, int) or isinstance(index, bool) or index < 0):
        raise VisualPlacementError("placement index must be a non-negative integer")
    bounds = raw.get("bounds")
    if bounds is not None and not isinstance(bounds, Mapping):
        raise VisualPlacementError("placement bounds must be a mapping")
    return PlacementTarget(
        artifact_type=kind,
        artifact_id=artifact,
        role_id=role,
        marker=expected_marker,
        container_id=container_id,
        element_id=element_id,
        index=index,
        bounds=dict(bounds) if bounds is not None else None,
    )


def build_placement_request(
    *,
    selected_asset: Mapping[str, Any],
    role_id: str,
    source_plan_id: str,
    target: PlacementTarget,
) -> PlacementRequest:
    """Bind one exact governed asset identity to one exact placement target."""
    if not isinstance(selected_asset, Mapping):
        raise VisualPlacementError("selected_asset must be a mapping")
    asset_id = _required_id(selected_asset.get("asset_id"), "asset_id")
    drive_file_id = _required_id(selected_asset.get("drive_file_id"), "drive_file_id")
    role = _required_id(role_id, "role_id")
    plan = _required_id(source_plan_id, "source_plan_id")
    if target.role_id != role or target.marker != marker_for_role(role):
        raise VisualPlacementError("placement target does not bind the requested role")
    return PlacementRequest(
        asset_id=asset_id,
        drive_file_id=drive_file_id,
        role_id=role,
        source_plan_id=plan,
        target=target,
    )


def verify_placement_receipt(request: PlacementRequest, receipt: object) -> PlacementReceipt:
    """Accept placement only when the receipt exactly reconstructs request identity."""
    if not isinstance(receipt, Mapping):
        raise VisualPlacementError("placement receipt must be a mapping")
    if receipt.get("state") != "placed":
        raise VisualPlacementError("transport result is not a completed placement")
    expected = {
        "asset_id": request.asset_id,
        "drive_file_id": request.drive_file_id,
        "role_id": request.role_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise VisualPlacementError(f"placement receipt {key} mismatch")
    inserted = _required_id(receipt.get("inserted_element_id"), "inserted_element_id")
    return PlacementReceipt(
        **expected,
        inserted_element_id=inserted,
        state="verified",
    )


def retry_is_safe(*, request: PlacementRequest, receipt: object | None) -> bool:
    """Permit retry only when there is positive evidence that no placement occurred."""
    if receipt is None:
        return False
    if not isinstance(receipt, Mapping):
        return False
    if receipt.get("state") != "not-placed":
        return False
    identity = (
        receipt.get("asset_id") == request.asset_id
        and receipt.get("drive_file_id") == request.drive_file_id
        and receipt.get("role_id") == request.role_id
        and receipt.get("artifact_type") == request.target.artifact_type
        and receipt.get("artifact_id") == request.target.artifact_id
        and receipt.get("marker") == request.target.marker
        and receipt.get("container_id") == request.target.container_id
    )
    return bool(identity and receipt.get("inserted_element_id") in (None, ""))


def _required_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualPlacementError(f"{name} is required")
    normalized = value.strip()
    if len(normalized) > 256 or any(ch.isspace() for ch in normalized):
        raise VisualPlacementError(f"{name} is malformed")
    return normalized
