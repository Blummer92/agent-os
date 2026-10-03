"""Assemble bounded provider-neutral evidence for the current curriculum state resolver."""

from __future__ import annotations

import copy
from typing import Any

from .common import ContractValidationError, validate_and_normalize_json, validate_stable_id, validate_text
from .current_curriculum_state import INPUT_CONTRACT_ID, resolve_current_curriculum_state

MAX_OWNER_EVIDENCE = 24
MAX_ASSET_EVIDENCE = 24
MAX_REQUIRED_KEYS = 24
MAX_SCOPE_UNIT_IDS = 24

# #3253: governed reuse-scope classes for curriculum asset evidence.
# Scope and reuse status are SEPARATE fields and must never be conflated:
# scope answers "where is this asset eligible", reuse status answers "may it
# be reused at all". The scope signal is the Icon System "Reusable Across
# Units?" checkbox (no Notion schema change); #3254 owns the Notion field
# projection, this module owns the scope vocabulary and eligibility policy.
REUSE_SCOPES = frozenset({
    "unit-specific",  # bound to one Canonical Unit; requires the relation-first read
    "coursewide",     # reusable across all units of the course; no unit relation required
    "cross-unit",     # reusable across a bounded unit set; admitted only for listed units
    "global",         # reusable across courses; no unit relation required
    "unrelated",      # explicitly not related to the requesting unit; never admitted
    "unknown",        # scope not evidenced; never admitted (fail closed)
})
REUSE_STATUSES = frozenset({"reusable", "single-use", "unknown"})
SCOPE_ELIGIBLE = frozenset({"unit-specific", "coursewide", "cross-unit", "global"})

_MODELING_KEYS = {"modeling-handoff-ready"}
_SLIDES_KEYS = {"unit-generation-approval", "modeling-handoff-ready", "packet-generation-gate", "instructional-materials-readiness", "source-control-gate", "production-authorized"}
_WORKSHEET_KEYS = {"unit-generation-approval", "packet-generation-gate", "instructional-materials-readiness", "source-control-gate", "production-authorized"}
_LESSON_KEYS = {"unit-generation-approval", "modeling-handoff-ready", "packet-generation-gate", "instructional-materials-readiness"}


def assemble_current_curriculum_evidence(*, request: object, canonical_unit: object, owner_evidence: object = (), asset_evidence: object = (), current_context: object | None = None) -> dict[str, Any]:
    """Build one deterministic #973 input packet from already-normalized evidence.

    This function performs no provider reads, search, persistence, or authority decisions.
    Provider-specific relation lookup and identity formatting must be resolved upstream.
    """
    normalized_request = _mapping(request, "request")
    normalized_unit = _mapping(canonical_unit, "canonical_unit")
    owners = _sequence(owner_evidence, "owner_evidence", MAX_OWNER_EVIDENCE)
    assets = _sequence(asset_evidence, "asset_evidence", MAX_ASSET_EVIDENCE)

    action = validate_text(normalized_request.get("action"), "request action")
    artifact_type = validate_text(normalized_request.get("artifact_type", "none"), "request artifact_type")
    relative_time = validate_text(normalized_request.get("relative_time", "none"), "request relative_time")
    requires_assets = normalized_request.get("requires_reusable_assets", False)
    if type(requires_assets) is not bool:
        raise ContractValidationError("handoff-invalid-field", "request requires_reusable_assets must be boolean")

    mode = _request_mode(action, artifact_type)
    selected_owners = _select_owner_evidence(owners, mode)
    canonical_unit_stable_id = validate_stable_id(normalized_unit.get("stable_id"), "canonical unit stable_id")
    selected_assets, scope_excluded_asset_ids = _select_assets(
        assets, requires_assets or mode == "images", canonical_unit_stable_id
    )
    required_keys = _required_keys(mode, selected_owners)

    packet: dict[str, Any] = {
        "contract_version": INPUT_CONTRACT_ID,
        "canonical_unit": copy.deepcopy(normalized_unit),
        "request": {"action": action, "artifact_type": artifact_type, "relative_time": relative_time, "requires_reusable_assets": bool(requires_assets or mode == "images")},
        "required_decision_keys": required_keys,
        "owner_evidence": selected_owners,
        "asset_evidence": selected_assets,
        # #3253: assets dropped for scope reasons are named explicitly so the
        # resolver can report out-of-scope as a non-absence outcome code
        # instead of letting the absence claim absorb them.
        "scope_excluded_asset_ids": scope_excluded_asset_ids,
    }
    if current_context is not None:
        packet["current_context"] = copy.deepcopy(_mapping(current_context, "current_context"))

    normalized = validate_and_normalize_json(packet)
    compatibility = resolve_current_curriculum_state(normalized)
    if compatibility.record is None:
        raise ContractValidationError("handoff-current-state-incompatible", "assembled evidence is not compatible with the current curriculum state resolver")
    return copy.deepcopy(normalized)


def _request_mode(action: str, artifact_type: str) -> str:
    """Classify only the already-resolved bounded request vocabulary.

    Keep this vocabulary identical to the live-read planner. Unknown values stay
    bounded instead of being reinterpreted from substrings.
    """
    normalized_action = action.lower()
    normalized_artifact = artifact_type.lower()
    if normalized_artifact in {"image", "images", "visual-assets"} or normalized_action == "images":
        return "images"
    if normalized_action in {"modeling", "improve-modeling"}:
        return "modeling"
    if normalized_action in {"blockers", "what-is-blocking"}:
        return "blockers"
    if normalized_artifact in {"slides", "slide-deck"}:
        return "slides"
    if normalized_artifact in {"worksheet", "worksheets"}:
        return "worksheet"
    if normalized_artifact in {"lesson", "lesson-plan"} or normalized_action in {"teach-next", "next-teaching"}:
        return "lesson"
    return "bounded"


def _required_keys(mode: str, owners: list[dict[str, Any]]) -> list[str]:
    if mode == "modeling": keys = _MODELING_KEYS
    elif mode == "slides": keys = _SLIDES_KEYS
    elif mode == "worksheet": keys = _WORKSHEET_KEYS
    elif mode == "lesson": keys = _LESSON_KEYS
    elif mode in {"images", "blockers"}: keys = set()
    else: keys = {str(item.get("decision_key")) for item in owners if item.get("material") is True}
    return sorted(key for key in keys if key)[:MAX_REQUIRED_KEYS]


def _select_owner_evidence(owners: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "images": return []
    if mode == "modeling": allowed = _MODELING_KEYS
    elif mode == "slides": allowed = _SLIDES_KEYS
    elif mode == "worksheet": allowed = _WORKSHEET_KEYS
    elif mode == "lesson": allowed = _LESSON_KEYS
    elif mode == "blockers": return _sorted_owners([item for item in owners if item.get("material") is True])
    else: return _sorted_owners(owners)
    return _sorted_owners([item for item in owners if item.get("decision_key") in allowed])


def _select_assets(
    assets: list[dict[str, Any]], include: bool, canonical_unit_stable_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Admit scope-eligible assets; name scope-excluded ones explicitly.

    Returns (selected, scope_excluded_asset_ids). Eligibility policy (#3253):
    - "unit-specific" requires canonical_unit_relation True (relation-first
      path; #2816's requirement is unchanged);
    - "coursewide" and "global" are admitted without any unit relation;
    - "cross-unit" is admitted only when the requesting unit is listed in the
      asset's scope_unit_ids;
    - "unrelated" and "unknown" are never admitted;
    - assets with no reuse_scope keep the legacy behavior (relation required),
      so pre-scope evidence is neither admitted loosely nor mislabeled.
    Scope and reuse status are contract data and ride on the admitted record;
    only the provider-specific canonical_unit_relation marker is stripped.
    """
    if not include:
        return [], []
    selected: list[dict[str, Any]] = []
    excluded: list[str] = []
    for item in assets:
        asset_id = str(item.get("asset_id", ""))
        scope = item.get("reuse_scope")
        if scope is None:
            if item.get("canonical_unit_relation") is True:
                selected.append(_selected_asset(item))
            continue
        if not isinstance(scope, str) or scope not in REUSE_SCOPES:
            raise ContractValidationError("handoff-invalid-field", "asset reuse_scope is unsupported")
        status = item.get("reuse_status", "unknown")
        if not isinstance(status, str) or status not in REUSE_STATUSES:
            raise ContractValidationError("handoff-invalid-field", "asset reuse_status is unsupported")
        if scope in {"unrelated", "unknown"}:
            excluded.append(asset_id)
            continue
        if scope == "unit-specific":
            if item.get("canonical_unit_relation") is not True:
                excluded.append(asset_id)
                continue
        elif scope == "cross-unit":
            unit_ids = item.get("scope_unit_ids", [])
            if (
                not isinstance(unit_ids, list)
                or len(unit_ids) > MAX_SCOPE_UNIT_IDS
                or not all(isinstance(unit_id, str) and unit_id for unit_id in unit_ids)
                or canonical_unit_stable_id not in unit_ids
            ):
                excluded.append(asset_id)
                continue
        # coursewide and global need no relation and no unit list.
        selected.append(_selected_asset(item))
    return (
        sorted(selected, key=lambda item: str(item.get("asset_id", ""))),
        sorted(set(excluded)),
    )


def _selected_asset(item: dict[str, Any]) -> dict[str, Any]:
    """Copy the contract fields; strip only the provider-specific relation marker."""
    return {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key != "canonical_unit_relation"
    }


def _sorted_owners(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((copy.deepcopy(item) for item in items), key=lambda item: (str(item.get("decision_key", "")), str(item.get("classification", "")), str(item.get("evidence_id", ""))))


def _mapping(value: object, label: str) -> dict[str, Any]:
    normalized = validate_and_normalize_json(value)
    if not isinstance(normalized, dict): raise ContractValidationError("handoff-invalid-field", f"{label} must be an object")
    return normalized


def _sequence(value: object, label: str, maximum: int) -> list[dict[str, Any]]:
    source = list(value) if isinstance(value, tuple) else value
    normalized = validate_and_normalize_json(source)
    if not isinstance(normalized, list): raise ContractValidationError("handoff-invalid-field", f"{label} must be a list")
    if len(normalized) > maximum: raise ContractValidationError("handoff-oversized", f"{label} exceeds bounded count")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(normalized):
        if not isinstance(item, dict): raise ContractValidationError("handoff-invalid-field", f"{label}[{index}] must be an object")
        if "evidence_id" in item: validate_stable_id(item["evidence_id"], f"{label}[{index}] evidence_id")
        if "asset_id" in item: validate_stable_id(item["asset_id"], f"{label}[{index}] asset_id")
        result.append(item)
    return result
