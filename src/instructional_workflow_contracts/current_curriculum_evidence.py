"""Assemble bounded provider-neutral evidence for the current curriculum state resolver."""

from __future__ import annotations

import copy
from typing import Any

from .common import ContractValidationError, validate_and_normalize_json, validate_stable_id, validate_text
from .current_curriculum_state import INPUT_CONTRACT_ID, resolve_current_curriculum_state

MAX_OWNER_EVIDENCE = 24
MAX_ASSET_EVIDENCE = 24
MAX_REQUIRED_KEYS = 24

_MODELING_KEYS = {"modeling-handoff-ready"}
_SLIDES_KEYS = {
    "unit-generation-approval",
    "modeling-handoff-ready",
    "packet-generation-gate",
    "instructional-materials-readiness",
    "source-control-gate",
    "production-authorized",
}
_WORKSHEET_KEYS = {
    "unit-generation-approval",
    "packet-generation-gate",
    "instructional-materials-readiness",
    "source-control-gate",
    "production-authorized",
}
_LESSON_KEYS = {
    "unit-generation-approval",
    "modeling-handoff-ready",
    "packet-generation-gate",
    "instructional-materials-readiness",
}


def assemble_current_curriculum_evidence(
    *,
    request: object,
    canonical_unit: object,
    owner_evidence: object = (),
    asset_evidence: object = (),
    current_context: object | None = None,
) -> dict[str, Any]:
    """Build one deterministic #973 input packet from already-normalized evidence.

    This function performs no provider reads, search, persistence, or authority decisions.
    Provider-specific relation lookup and identity formatting must be resolved upstream.
    """
    normalized_request = _mapping(request, "request")
    normalized_unit = _mapping(canonical_unit, "canonical_unit")
    owners = _sequence(owner_evidence, "owner_evidence", MAX_OWNER_EVIDENCE)
    assets = _sequence(asset_evidence, "asset_evidence", MAX_ASSET_EVIDENCE)

    action = validate_text(normalized_request.get("action"), "request action")
    artifact_type = validate_text(
        normalized_request.get("artifact_type", "none"), "request artifact_type"
    )
    relative_time = validate_text(
        normalized_request.get("relative_time", "none"), "request relative_time"
    )
    requires_assets = normalized_request.get("requires_reusable_assets", False)
    if type(requires_assets) is not bool:
        raise ContractValidationError(
            "handoff-invalid-field", "request requires_reusable_assets must be boolean"
        )

    mode = _request_mode(action, artifact_type)
    selected_owners = _select_owner_evidence(owners, mode)
    selected_assets = _select_assets(assets, requires_assets or mode == "images")
    required_keys = _required_keys(mode, selected_owners)

    packet: dict[str, Any] = {
        "contract_version": INPUT_CONTRACT_ID,
        "canonical_unit": copy.deepcopy(normalized_unit),
        "request": {
            "action": action,
            "artifact_type": artifact_type,
            "relative_time": relative_time,
            "requires_reusable_assets": bool(requires_assets or mode == "images"),
        },
        "required_decision_keys": required_keys,
        "owner_evidence": selected_owners,
        "asset_evidence": selected_assets,
    }
    if current_context is not None:
        packet["current_context"] = copy.deepcopy(_mapping(current_context, "current_context"))

    normalized = validate_and_normalize_json(packet)
    compatibility = resolve_current_curriculum_state(normalized)
    if compatibility.record is None:
        raise ContractValidationError(
            "handoff-current-state-incompatible",
            "assembled evidence is not compatible with the current curriculum state resolver",
        )
    return copy.deepcopy(normalized)


def _request_mode(action: str, artifact_type: str) -> str:
    token = f"{action} {artifact_type}".lower()
    if artifact_type.lower() in {"image", "images", "visual-assets"} or "images" in token:
        return "images"
    if "model" in token:
        return "modeling"
    if "block" in token:
        return "blockers"
    if artifact_type.lower() in {"slides", "slide-deck"}:
        return "slides"
    if artifact_type.lower() in {"worksheet", "worksheets"}:
        return "worksheet"
    if artifact_type.lower() in {"lesson", "lesson-plan"} or "teach-next" in token:
        return "lesson"
    return "bounded"


def _required_keys(mode: str, owners: list[dict[str, Any]]) -> list[str]:
    if mode == "modeling":
        keys = _MODELING_KEYS
    elif mode == "slides":
        keys = _SLIDES_KEYS
    elif mode == "worksheet":
        keys = _WORKSHEET_KEYS
    elif mode == "lesson":
        keys = _LESSON_KEYS
    elif mode in {"images", "blockers"}:
        keys = set()
    else:
        keys = {str(item.get("decision_key")) for item in owners if item.get("material") is True}
    return sorted(key for key in keys if key)[:MAX_REQUIRED_KEYS]


def _select_owner_evidence(owners: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "images":
        return []
    if mode == "modeling":
        allowed = _MODELING_KEYS
    elif mode == "slides":
        allowed = _SLIDES_KEYS
    elif mode == "worksheet":
        allowed = _WORKSHEET_KEYS
    elif mode == "lesson":
        allowed = _LESSON_KEYS
    elif mode == "blockers":
        return _sorted_owners([item for item in owners if item.get("material") is True])
    else:
        return _sorted_owners(owners)
    return _sorted_owners([item for item in owners if item.get("decision_key") in allowed])


def _select_assets(assets: list[dict[str, Any]], include: bool) -> list[dict[str, Any]]:
    if not include:
        return []
    selected: list[dict[str, Any]] = []
    for item in assets:
        relation = item.get("canonical_unit_relation")
        if relation is not None and relation is not True:
            continue
        clean = {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key != "canonical_unit_relation"
        }
        selected.append(clean)
    return sorted(selected, key=lambda item: str(item.get("asset_id", "")))


def _sorted_owners(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (copy.deepcopy(item) for item in items),
        key=lambda item: (
            str(item.get("decision_key", "")),
            str(item.get("classification", "")),
            str(item.get("evidence_id", "")),
        ),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    normalized = validate_and_normalize_json(value)
    if not isinstance(normalized, dict):
        raise ContractValidationError("handoff-invalid-field", f"{label} must be an object")
    return normalized


def _sequence(value: object, label: str, maximum: int) -> list[dict[str, Any]]:
    source = list(value) if isinstance(value, tuple) else value
    normalized = validate_and_normalize_json(source)
    if not isinstance(normalized, list):
        raise ContractValidationError("handoff-invalid-field", f"{label} must be a list")
    if len(normalized) > maximum:
        raise ContractValidationError("handoff-oversized", f"{label} exceeds bounded count")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(normalized):
        if not isinstance(item, dict):
            raise ContractValidationError(
                "handoff-invalid-field", f"{label}[{index}] must be an object"
            )
        if "evidence_id" in item:
            validate_stable_id(item["evidence_id"], f"{label}[{index}] evidence_id")
        if "asset_id" in item:
            validate_stable_id(item["asset_id"], f"{label}[{index}] asset_id")
        result.append(item)
    return result
