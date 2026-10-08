"""Fail-closed contracts for exact reusable-visual placement.

This module is pure repository-side planning/verification. It performs no
Workspace calls and grants no external-write authority.

Content identity (#3256)
------------------------
Every placement request binds the canonical content identity recorded at
approval/selection (see ``instructional_workflow_contracts.asset_content_identity``).
The request carries the identity; ``verify_request_content_identity`` checks it
against fresh Drive metadata immediately before insertion. A mismatch fails
closed with the explicit ``content-identity-mismatch`` outcome -- never
absence, never a generation handoff. The placement receipt must reconstruct
the bound content identity exactly.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from instructional_workflow_contracts.asset_content_identity import (
    is_valid_content_identity,
    verify_content_identity,
)

_MARKER_RE = re.compile(
    r"^\{\{visual:([a-z0-9][a-z0-9-]{2,127})(?::([A-Za-z0-9][A-Za-z0-9_-]{0,63}))?\}\}$"
)
_SUPPORTED_ARTIFACTS = frozenset({"docs", "slides"})
# Implicit slot for roles with no declared slots (#3251). Role-only
# markers ({{visual:<role_id>}}) address the implicit slot; slot markers
# ({{visual:<role_id>:<slot_id>}}) address one explicit slot.
IMPLICIT_SLOT_ID = "0"


class VisualPlacementError(ValueError):
    """Raised when placement evidence is missing, ambiguous, or contradictory."""


@dataclass(frozen=True)
class PlacementTarget:
    artifact_type: str
    artifact_id: str
    artifact_revision_id: str
    role_id: str
    marker: str
    container_id: str
    element_id: str
    index: int | None = None
    bounds: Mapping[str, Any] | None = None
    fit_mode: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    # #3251: the (role_id, slot_id) binding this target places. Defaults to
    # the implicit slot so role-only markers keep working unchanged.
    slot_id: str = IMPLICIT_SLOT_ID


@dataclass(frozen=True)
class PlacementRequest:
    asset_id: str
    drive_file_id: str
    role_id: str
    source_plan_id: str
    target: PlacementTarget
    content_identity: Mapping[str, Any]
    slot_id: str = IMPLICIT_SLOT_ID


@dataclass(frozen=True)
class PlacementReceipt:
    asset_id: str
    drive_file_id: str
    role_id: str
    artifact_type: str
    artifact_id: str
    artifact_revision_id: str
    marker: str
    container_id: str
    inserted_element_id: str
    state: str
    slot_id: str = IMPLICIT_SLOT_ID


def marker_for_role(role_id: str) -> str:
    role = _required_id(role_id, "role_id")
    marker = "{{visual:" + role + "}}"
    if not _MARKER_RE.fullmatch(marker):
        raise VisualPlacementError("role_id cannot be represented by the controlled visual marker syntax")
    return marker


def marker_for_role_slot(role_id: str, slot_id: str) -> str:
    """Build the slot-aware controlled marker ``{{visual:<role_id>:<slot_id>}}``."""
    role = _required_id(role_id, "role_id")
    slot = _required_slot_id(slot_id)
    marker = "{{visual:" + role + ":" + slot + "}}"
    if not _MARKER_RE.fullmatch(marker):
        raise VisualPlacementError("role_id/slot_id cannot be represented by the controlled visual marker syntax")
    return marker


def parse_marker(value: object) -> str:
    if not isinstance(value, str):
        raise VisualPlacementError("visual marker must be a string")
    match = _MARKER_RE.fullmatch(value)
    if match is None:
        raise VisualPlacementError("unsupported or malformed visual marker")
    return match.group(1)


def parse_marker_binding(value: object) -> tuple[str, str]:
    """Parse a controlled marker into its ``(role_id, slot_id)`` binding.

    Role-only markers bind the implicit slot ``"0"``; slot markers bind
    their explicit slot. The pair is the placement identity -- two slots of
    one role are two distinct bindings (#3251).
    """
    if not isinstance(value, str):
        raise VisualPlacementError("visual marker must be a string")
    match = _MARKER_RE.fullmatch(value)
    if match is None:
        raise VisualPlacementError("unsupported or malformed visual marker")
    return match.group(1), match.group(2) or IMPLICIT_SLOT_ID


def resolve_exact_target(
    *,
    artifact_type: str,
    artifact_id: str,
    artifact_revision_id: str,
    role_id: str,
    slot_id: str = IMPLICIT_SLOT_ID,
    matches: Iterable[Mapping[str, Any]],
) -> PlacementTarget:
    """Resolve exactly one pre-discovered controlled marker match.

    The match must be the marker for the requested ``(role_id, slot_id)``
    binding: role-only markers address the implicit slot, slot markers
    address their explicit slot. More than one match for the same binding
    fails closed instead of guessing the target.
    """
    kind = str(artifact_type).strip().lower()
    if kind not in _SUPPORTED_ARTIFACTS:
        raise VisualPlacementError("unsupported placement artifact type")
    artifact = _required_id(artifact_id, "artifact_id")
    artifact_revision = _required_id(artifact_revision_id, "artifact_revision_id")
    role = _required_id(role_id, "role_id")
    slot = _required_slot_id(slot_id)
    candidates = list(matches)
    if len(candidates) != 1:
        raise VisualPlacementError("visual placement requires exactly one marker match")
    raw = candidates[0]
    if not isinstance(raw, Mapping):
        raise VisualPlacementError("marker match must be a mapping")
    marker_text = raw.get("marker")
    # Binding identity is the (role_id, slot_id) pair: {{visual:<role>}} and
    # {{visual:<role>:0}} denote the same implicit-slot binding. The marker
    # text carried on the target is the artifact's own spelling so receipts
    # reconstruct it exactly.
    if parse_marker_binding(marker_text) != (role, slot):
        raise VisualPlacementError("marker match does not bind the requested role/slot")
    assert isinstance(marker_text, str)
    container_id = _required_id(raw.get("container_id"), "container_id")
    element_id = _required_id(raw.get("element_id"), "element_id")
    index = raw.get("index")
    if index is not None and (not isinstance(index, int) or isinstance(index, bool) or index < 0):
        raise VisualPlacementError("placement index must be a non-negative integer")
    bounds = raw.get("bounds")
    if bounds is not None and not isinstance(bounds, Mapping):
        raise VisualPlacementError("placement bounds must be a mapping")
    fit_mode = raw.get("fit_mode")
    if fit_mode is not None:
        if fit_mode not in {"contain", "native"}:
            raise VisualPlacementError("instructional visual placement must preserve the complete asset")
    source_width = raw.get("source_width")
    source_height = raw.get("source_height")
    for name, value in (("source_width", source_width), ("source_height", source_height)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
            raise VisualPlacementError(f"{name} must be a positive integer")
    if (source_width is None) != (source_height is None):
        raise VisualPlacementError("source dimensions must be supplied together")
    return PlacementTarget(
        artifact_type=kind,
        artifact_id=artifact,
        artifact_revision_id=artifact_revision,
        role_id=role,
        marker=marker_text,
        container_id=container_id,
        element_id=element_id,
        index=index,
        bounds=dict(bounds) if bounds is not None else None,
        fit_mode=fit_mode,
        source_width=source_width,
        source_height=source_height,
        slot_id=slot,
    )


def build_placement_request(
    *,
    selected_asset: Mapping[str, Any],
    role_id: str,
    slot_id: str = IMPLICIT_SLOT_ID,
    source_plan_id: str,
    target: PlacementTarget,
    content_identity: Mapping[str, Any] | None = None,
) -> PlacementRequest:
    """Bind one exact governed asset identity to one exact placement target.

    The request carries the canonical content identity recorded at
    approval/selection (#3256): taken from ``selected_asset["content_identity"]``
    unless overridden explicitly. A missing or malformed content identity is a
    build-time failure -- placement must never proceed on bytes that were not
    reviewed. The ``(role_id, slot_id)`` binding must match the target's own
    binding exactly.
    """
    if not isinstance(selected_asset, Mapping):
        raise VisualPlacementError("selected_asset must be a mapping")
    asset_id = _required_id(selected_asset.get("asset_id"), "asset_id")
    drive_file_id = _required_id(selected_asset.get("drive_file_id"), "drive_file_id")
    identity = content_identity if content_identity is not None else selected_asset.get("content_identity")
    if not is_valid_content_identity(identity):
        raise VisualPlacementError("selected_asset must carry a valid canonical content identity (#3256)")
    role = _required_id(role_id, "role_id")
    slot = _required_slot_id(slot_id)
    plan = _required_id(source_plan_id, "source_plan_id")
    if target.role_id != role or target.slot_id != slot:
        raise VisualPlacementError("placement target does not bind the requested role/slot")
    if target.fit_mode not in (None, "contain", "native"):
        raise VisualPlacementError("instructional visual placement cannot use a clipping crop mode")
    return PlacementRequest(
        asset_id=asset_id,
        drive_file_id=drive_file_id,
        role_id=role,
        source_plan_id=plan,
        target=target,
        content_identity=dict(identity),
        slot_id=slot,
    )


def verify_request_content_identity(
    *,
    request: PlacementRequest,
    drive_metadata: Mapping[str, Any],
) -> str:
    """Verify the request's bound content identity against fresh Drive metadata.

    Call this immediately before insertion (#3257). Returns one of
    ``content-identity-match``, ``content-identity-mismatch``,
    ``content-identity-unverifiable``, or ``content-identity-not-recorded``.
    Anything but a match must fail the placement closed for that asset.
    """
    return verify_content_identity(expected=request.content_identity, metadata=drive_metadata)


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
        "slot_id": request.slot_id,
        "artifact_type": request.target.artifact_type,
        "artifact_id": request.target.artifact_id,
        "artifact_revision_id": request.target.artifact_revision_id,
        "marker": request.target.marker,
        "container_id": request.target.container_id,
        "content_identity": dict(request.content_identity),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise VisualPlacementError(f"placement receipt {key} mismatch")
    inserted = _required_id(receipt.get("inserted_element_id"), "inserted_element_id")
    return PlacementReceipt(
        **{key: value for key, value in expected.items() if key != "content_identity"},
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
        and receipt.get("slot_id", IMPLICIT_SLOT_ID) == request.slot_id
        and receipt.get("artifact_type") == request.target.artifact_type
        and receipt.get("artifact_id") == request.target.artifact_id
        and receipt.get("artifact_revision_id") == request.target.artifact_revision_id
        and receipt.get("marker") == request.target.marker
        and receipt.get("container_id") == request.target.container_id
        and receipt.get("content_identity", dict(request.content_identity)) == dict(request.content_identity)
    )
    return bool(identity and receipt.get("inserted_element_id") in (None, ""))


def _required_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VisualPlacementError(f"{name} is required")
    normalized = value.strip()
    if len(normalized) > 256 or any(ch.isspace() for ch in normalized):
        raise VisualPlacementError(f"{name} is malformed")
    return normalized


def _required_slot_id(value: object) -> str:
    """Validate a placement slot id (#3251).

    Slot ids must survive the controlled marker syntax: the same charset
    the MaterialRequirement contract enforces, so a declared slot always
    renders to a parseable ``{{visual:<role_id>:<slot_id>}}`` marker.
    """
    if not isinstance(value, str) or not value.strip():
        raise VisualPlacementError("slot_id is required")
    normalized = value.strip()
    if len(normalized) > 64 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", normalized):
        raise VisualPlacementError("slot_id is malformed")
    return normalized
