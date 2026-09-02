"""Pure deterministic cohesive visual-set planning from approved candidates."""

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
    validate_revision,
    validate_stable_id,
)
from .visual_asset_candidates import V2_CONTRACT_ID as CANDIDATE_CONTRACT_ID
from .visual_needs import CONTRACT_ID as VISUAL_NEEDS_CONTRACT_ID

CONTRACT_ID = "curriculum-cohesive-visual-plan-v1"
MAX_SELECTED_ASSETS = 8
MAX_GAP_BRIEFS = 8
_COHESION_FIELDS = (
    "visual_style_family",
    "medium",
    "representation_class",
    "palette_family",
    "line_treatment",
    "rendering_style",
    "perspective",
    "background_treatment",
)
_AUTHORITY = {
    "execution_authorized": False,
    "external_write_authorized": False,
    "production_authorized": False,
    "publication_authorized": False,
    "side_effects_performed": False,
}


def plan_cohesive_visual_set(
    visual_needs_plan: object,
    candidate_filter_result: object,
) -> ValidationResult:
    """Select one bounded cohesive visual set and deterministic gap briefs."""
    try:
        plan = _plan_record(visual_needs_plan)
        plan_payload = plan.to_dict()
        if plan_payload["outcome"] != "visuals-required":
            raise ContractValidationError(
                "asset-cohesive-plan-not-actionable",
                "visual-needs plan must require visuals",
            )

        candidates = _candidate_record(candidate_filter_result)
        candidate_payload = candidates.to_dict()
        _bind_candidate_result_to_plan(candidate_payload, plan)

        required_roles = list(plan_payload["required_roles"])
        optional_roles = list(plan_payload["optional_roles"])
        max_visuals = plan_payload["maximum_visual_count"]
        cognitive_ceiling = plan_payload["cognitive_load_ceiling"]
        material_type = plan_payload["material_type"]

        selected: list[dict[str, Any]] = []
        required_assignments: list[dict[str, Any]] = []
        optional_assignments: list[dict[str, Any]] = []
        rejected_assignments: list[dict[str, Any]] = []
        rejected_sets: list[dict[str, Any]] = []
        unfilled_required: list[dict[str, Any]] = []
        unfilled_required_roles: list[dict[str, Any]] = []
        unfilled_optional: list[dict[str, Any]] = []
        manual_reasons: set[str] = set()
        total_cognitive_load = 0
        used_asset_keys: set[tuple[str, str, str]] = set()

        if candidate_payload["manual_review"]:
            manual_reasons.add("manual-review-visual-candidates")

        eligible = list(candidate_payload["eligible"])
        if len(eligible) > 32:
            raise ContractValidationError(
                "handoff-oversized",
                "eligible candidate count exceeds the governed bound",
            )

        for role in required_roles:
            if len(selected) >= min(max_visuals, MAX_SELECTED_ASSETS):
                raise ContractValidationError(
                    "handoff-oversized",
                    "required roles exceed the governed maximum visual count",
                )
            match = _select_for_role(
                role,
                eligible,
                selected=selected,
                used_asset_keys=used_asset_keys,
                material_type=material_type,
                current_cognitive_load=total_cognitive_load,
                cognitive_ceiling=cognitive_ceiling,
                rejected_assignments=rejected_assignments,
                rejected_sets=rejected_sets,
            )
            if match["manual_review"]:
                manual_reasons.update(match["manual_review"])
            candidate = match["candidate"]
            if candidate is None:
                if "manual-review-visual-assignment-tie" in match["manual_review"]:
                    unfilled_required.append(_unfilled_role(role, tie_blocked=True))
                else:
                    unfilled_required.append(_unfilled_role(role))
                    unfilled_required_roles.append(role)
                continue
            assignment = _assignment(
                role,
                candidate,
                requirement_state="required",
            )
            required_assignments.append(assignment)
            selected.append(candidate)
            used_asset_keys.add(_asset_key(candidate))
            total_cognitive_load += candidate["cohesion_profile"][
                "cognitive_load_rating"
            ]

        for role in optional_roles:
            if len(selected) >= min(max_visuals, MAX_SELECTED_ASSETS):
                unfilled_optional.append(_unfilled_role(role))
                continue
            match = _select_for_role(
                role,
                eligible,
                selected=selected,
                used_asset_keys=used_asset_keys,
                material_type=material_type,
                current_cognitive_load=total_cognitive_load,
                cognitive_ceiling=cognitive_ceiling,
                rejected_assignments=rejected_assignments,
                rejected_sets=rejected_sets,
            )
            if match["manual_review"]:
                manual_reasons.update(match["manual_review"])
            candidate = match["candidate"]
            if candidate is None:
                unfilled_optional.append(_unfilled_role(role))
                continue
            assignment = _assignment(
                role,
                candidate,
                requirement_state="optional",
            )
            optional_assignments.append(assignment)
            selected.append(candidate)
            used_asset_keys.add(_asset_key(candidate))
            total_cognitive_load += candidate["cohesion_profile"][
                "cognitive_load_rating"
            ]

        if len(selected) > MAX_SELECTED_ASSETS:
            raise ContractValidationError(
                "handoff-oversized",
                "selected visual set exceeds the governed bound",
            )

        gap_briefs = [
            _gap_brief(
                role,
                material_type=material_type,
                selected=selected,
            )
            for role in unfilled_required_roles
        ]
        if len(gap_briefs) > MAX_GAP_BRIEFS:
            raise ContractValidationError(
                "handoff-oversized",
                "image-gap briefs exceed the governed bound",
            )

        if manual_reasons:
            outcome = "manual-review-required"
        elif unfilled_required:
            outcome = "partial-set"
        else:
            outcome = "complete-set"

        payload = {
            "contract_version": CONTRACT_ID,
            "cohesive_visual_plan_id": _plan_id(
                plan=plan,
                candidates=candidates,
                required_assignments=required_assignments,
                optional_assignments=optional_assignments,
                unfilled_required=unfilled_required,
                manual_reasons=tuple(sorted(manual_reasons)),
            ),
            "source_visual_needs_plan": {
                "contract_version": plan.contract_version,
                "plan_id": plan.record_id,
                "record_revision": plan.record_revision,
                "fingerprint": plan.fingerprint,
            },
            "source_candidate_filter_result": {
                "contract_version": candidates.contract_version,
                "candidate_set_id": candidates.record_id,
                "record_revision": candidates.record_revision,
                "fingerprint": candidates.fingerprint,
            },
            "source_revision": candidate_payload["source_revision"],
            "outcome": outcome,
            "required_role_assignments": required_assignments,
            "optional_role_assignments": optional_assignments,
            "selected_candidates": [_candidate_identity(item) for item in selected],
            "rejected_assignments": sorted(
                rejected_assignments,
                key=lambda item: (
                    item["role_id"],
                    item["compatibility_id"],
                    tuple(item["reason_codes"]),
                ),
            ),
            "rejected_set_combinations": sorted(
                rejected_sets,
                key=lambda item: (
                    item["role_id"],
                    item["compatibility_id"],
                    tuple(item["reason_codes"]),
                ),
            ),
            "unfilled_required_roles": unfilled_required,
            "unfilled_optional_roles": unfilled_optional,
            "image_gap_briefs": gap_briefs,
            "cognitive_load": {
                "total": total_cognitive_load,
                "ceiling": cognitive_ceiling,
            },
            "manual_review_required": bool(manual_reasons),
            "manual_review_reasons": list(sorted(manual_reasons)),
            "authority": dict(_AUTHORITY),
        }
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict:
            raise ContractValidationError(
                "asset-cohesive-plan-invalid",
                "cohesive visual plan must be a built-in mapping",
            )
        if canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized",
                "cohesive visual plan exceeds the shared result-size bound",
            )

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=normalized["cohesive_visual_plan_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        if outcome == "manual-review-required":
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=tuple(sorted(manual_reasons)),
                details=("cohesive visual planning requires bounded human review",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("asset-cohesive-plan-invalid", sanitize_detail(str(exc)))


def _plan_record(value: object) -> ValidatedRecord:
    if type(value) is ValidationResult:
        if value.status is not ValidationStatus.VALID or value.record is None:
            raise ContractValidationError(
                "asset-cohesive-plan-invalid-plan",
                "visual-needs result must be valid and contain a record",
            )
        supplied = value.record
    elif type(value) is ValidatedRecord:
        supplied = value
    else:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-plan",
            "visual-needs plan must be validated evidence",
        )
    if supplied.contract_version != VISUAL_NEEDS_CONTRACT_ID:
        raise ContractValidationError(
            "asset-cohesive-plan-incompatible-plan",
            "visual-needs contract version is incompatible",
        )
    payload = supplied.to_dict()
    expected = {
        "contract_version", "plan_id", "source_requirement", "material_type",
        "outcome", "source_visual_decision", "required_roles", "optional_roles",
        "accessibility_requirements", "cognitive_load_ceiling",
        "maximum_visual_count", "manual_review_required", "reason_codes", "authority",
    }
    if set(payload) != expected:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-plan",
            "visual-needs plan fields are not exact",
        )
    if payload["plan_id"] != supplied.record_id:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-plan",
            "visual-needs plan identity does not match its validated record",
        )
    validate_revision(supplied.record_revision)
    if sha256_hex(payload) != supplied.fingerprint:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-plan",
            "visual-needs plan fingerprint does not reconstruct exactly",
        )
    return supplied


def _candidate_record(value: object) -> ValidatedRecord:
    if type(value) is ValidationResult:
        if value.record is None:
            raise ContractValidationError(
                "asset-cohesive-plan-invalid-candidates",
                "candidate-filter result must contain a record",
            )
        if value.status not in {
            ValidationStatus.VALID,
            ValidationStatus.MANUAL_REVIEW_REQUIRED,
        }:
            raise ContractValidationError(
                "asset-cohesive-plan-invalid-candidates",
                "candidate-filter result is not usable validated evidence",
            )
        supplied = value.record
    elif type(value) is ValidatedRecord:
        supplied = value
    else:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-candidates",
            "candidate-filter result must be validated evidence",
        )
    if supplied.contract_version != CANDIDATE_CONTRACT_ID:
        raise ContractValidationError(
            "asset-cohesive-plan-incompatible-candidates",
            "candidate-filter contract version is incompatible",
        )
    payload = supplied.to_dict()
    expected = {
        "contract_version", "candidate_set_id", "source_revision",
        "visual_needs_plan", "maximum_candidate_count", "candidate_count",
        "eligible", "rejected", "manual_review", "authority",
    }
    if set(payload) != expected:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-candidates",
            "candidate-filter fields are not exact",
        )
    if payload["candidate_set_id"] != supplied.record_id:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-candidates",
            "candidate-filter identity does not match its validated record",
        )
    validate_revision(supplied.record_revision)
    if sha256_hex(payload) != supplied.fingerprint:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-candidates",
            "candidate-filter fingerprint does not reconstruct exactly",
        )
    if canonical_size(payload) > MAX_RESULT_BYTES:
        raise ContractValidationError(
            "handoff-oversized",
            "candidate-filter payload exceeds the shared result-size bound",
        )
    return supplied


def _bind_candidate_result_to_plan(
    candidate_payload: dict[str, Any],
    plan: ValidatedRecord,
) -> None:
    reference = candidate_payload["visual_needs_plan"]
    expected = {
        "contract_version": plan.contract_version,
        "plan_id": plan.record_id,
        "record_revision": plan.record_revision,
        "fingerprint": plan.fingerprint,
    }
    if reference != expected:
        raise ContractValidationError(
            "identity-invalid",
            "candidate-filter result is not bound to the supplied visual-needs plan",
        )


def _select_for_role(
    role: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    selected: list[dict[str, Any]],
    used_asset_keys: set[tuple[str, str, str]],
    material_type: str,
    current_cognitive_load: int,
    cognitive_ceiling: int,
    rejected_assignments: list[dict[str, Any]],
    rejected_sets: list[dict[str, Any]],
) -> dict[str, Any]:
    viable: list[tuple[tuple[int, int, int, int], str, dict[str, Any]]] = []
    manual: set[str] = set()
    for candidate in candidates:
        reasons = _role_rejection_reasons(
            role,
            candidate,
            material_type=material_type,
        )
        if reasons:
            rejected_assignments.append(_rejection(role, candidate, reasons))
            continue
        set_reasons = _set_rejection_reasons(
            role,
            candidate,
            selected=selected,
            used_asset_keys=used_asset_keys,
            current_cognitive_load=current_cognitive_load,
            cognitive_ceiling=cognitive_ceiling,
        )
        if set_reasons:
            rejected_sets.append(_rejection(role, candidate, set_reasons))
            continue
        score = _score(role, candidate)
        viable.append((score, _candidate_sort_key(candidate), candidate))

    if not viable:
        return {"candidate": None, "manual_review": tuple(sorted(manual))}

    viable.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], -item[0][3], item[1]))
    if len(viable) > 1 and viable[0][0] == viable[1][0]:
        manual.add("manual-review-visual-assignment-tie")
        return {"candidate": None, "manual_review": tuple(sorted(manual))}
    return {"candidate": viable[0][2], "manual_review": tuple(sorted(manual))}


def _role_rejection_reasons(
    role: dict[str, Any],
    candidate: dict[str, Any],
    *,
    material_type: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    role_type = role["role_type"]
    if role_type not in candidate["purpose"]["role_types"]:
        reasons.append("asset-role-mismatch")
    if role_type not in candidate["approved_use"]["role_types"]:
        reasons.append("asset-approved-use-role-mismatch")
    if material_type not in candidate["approved_use"]["material_types"]:
        reasons.append("asset-approved-use-material-mismatch")
    orientation = candidate["orientation"]["orientation"]
    role_orientation = role["orientation"]
    if orientation != "flexible" and role_orientation not in {
        orientation,
        "unspecified",
    }:
        reasons.append("asset-orientation-mismatch")
    if any(
        candidate["cohesion_profile"][field] == "unspecified"
        for field in _COHESION_FIELDS
    ):
        reasons.append("asset-cohesion-missing")
    if candidate["cohesion_profile"]["audience_compatibility"]["state"] != "approved":
        reasons.append("asset-audience-incompatible")
    return tuple(sorted(reasons))


def _set_rejection_reasons(
    role: dict[str, Any],
    candidate: dict[str, Any],
    *,
    selected: list[dict[str, Any]],
    used_asset_keys: set[tuple[str, str, str]],
    current_cognitive_load: int,
    cognitive_ceiling: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if _asset_key(candidate) in used_asset_keys:
        reasons.append("asset-duplicate-selected")

    candidate_asset = candidate["matched_asset"]
    candidate_group = candidate_asset["duplicate_group_id"]
    candidate_stable = candidate_asset["stable_ref"]
    candidate_canonical = candidate_asset["canonical_asset_ref"]
    for selected_candidate in selected:
        selected_asset = selected_candidate["matched_asset"]
        if candidate_group is not None and candidate_group == selected_asset["duplicate_group_id"]:
            reasons.append("asset-duplicate-selected")
        if candidate_canonical is not None and candidate_canonical == selected_asset["stable_ref"]:
            reasons.append("asset-duplicate-selected")
        if selected_asset["canonical_asset_ref"] is not None and selected_asset["canonical_asset_ref"] == candidate_stable:
            reasons.append("asset-duplicate-selected")

        cohesion_reasons = _cohesion_conflict_reasons(
            candidate["cohesion_profile"],
            selected_candidate["cohesion_profile"],
        )
        reasons.extend(cohesion_reasons)

    candidate_load = candidate["cohesion_profile"]["cognitive_load_rating"]
    if current_cognitive_load + candidate_load > cognitive_ceiling:
        reasons.append("asset-cognitive-load-exceeded")
    return tuple(sorted(set(reasons)))


def _cohesion_conflict_reasons(
    first: dict[str, Any],
    second: dict[str, Any],
) -> tuple[str, ...]:
    reasons: list[str] = []
    reason_map = {
        "visual_style_family": "asset-cohesion-style-conflict",
        "medium": "asset-cohesion-medium-conflict",
        "representation_class": "asset-cohesion-representation-conflict",
        "palette_family": "asset-cohesion-palette-conflict",
        "line_treatment": "asset-cohesion-line-conflict",
        "rendering_style": "asset-cohesion-rendering-conflict",
        "perspective": "asset-cohesion-perspective-conflict",
        "background_treatment": "asset-cohesion-background-conflict",
    }
    for field, reason in reason_map.items():
        if first[field] != second[field]:
            reasons.append(reason)
    return tuple(sorted(reasons))


def _score(role: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, int, int, int]:
    score = 0
    role_type = role["role_type"]
    if role_type in candidate["purpose"]["role_types"]:
        score += 20
    if role_type in candidate["approved_use"]["role_types"]:
        score += 20
    canonical = 1 if candidate["matched_asset"]["disposition"] == "canonical" else 0
    if canonical:
        score += 10
    orientation = candidate["orientation"]["orientation"]
    orientation_exact = 1 if orientation == role["orientation"] else 0
    if orientation_exact:
        score += 5
    elif orientation == "flexible":
        score += 2
    cognitive_preference = 5 - candidate["cohesion_profile"]["cognitive_load_rating"]
    score += cognitive_preference
    return (score, canonical, orientation_exact, cognitive_preference)


def _assignment(
    role: dict[str, Any],
    candidate: dict[str, Any],
    *,
    requirement_state: str,
) -> dict[str, Any]:
    score = _score(role, candidate)
    return {
        "role_id": role["role_id"],
        "role_type": role["role_type"],
        "requirement_state": requirement_state,
        "instructional_purpose": role["instructional_purpose"],
        "intended_placement": role["intended_placement"],
        "selected_candidate": _candidate_identity(candidate),
        "assignment_score": score[0],
        "score_evidence": {
            "exact_role_match": role["role_type"] in candidate["purpose"]["role_types"],
            "approved_use_match": role["role_type"] in candidate["approved_use"]["role_types"],
            "canonical_asset": candidate["matched_asset"]["disposition"] == "canonical",
            "orientation_match": (
                candidate["orientation"]["orientation"] == "flexible"
                or role["orientation"] in {candidate["orientation"]["orientation"], "unspecified"}
            ),
            "cognitive_load_rating": candidate["cohesion_profile"]["cognitive_load_rating"],
        },
        "compatibility_evidence": {
            "cohesion_profile": candidate["cohesion_profile"],
            "orientation": candidate["orientation"],
            "accessibility": candidate["accessibility"],
            "approved_use": candidate["approved_use"],
        },
        "authority": dict(_AUTHORITY),
    }


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "compatibility_id": candidate["compatibility_id"],
        "compatibility_fingerprint": candidate["fingerprint"],
        "manifest_reference": candidate["manifest_reference"],
        "asset_reference": candidate["asset_reference"],
        "library_reference": candidate["library_reference"],
        "matched_asset": candidate["matched_asset"],
    }


def _rejection(
    role: dict[str, Any],
    candidate: dict[str, Any],
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "role_id": role["role_id"],
        "role_type": role["role_type"],
        "compatibility_id": candidate["compatibility_id"],
        "asset_reference": candidate["asset_reference"],
        "reason_codes": list(reasons),
    }


def _unfilled_role(role: dict[str, Any], *, tie_blocked: bool = False) -> dict[str, Any]:
    reason_code = (
        "asset-required-role-tie-blocked"
        if tie_blocked
        else "asset-required-role-unfilled"
    )
    return {
        "role_id": role["role_id"],
        "role_type": role["role_type"],
        "requirement_state": role["requirement_state"],
        "instructional_purpose": role["instructional_purpose"],
        "intended_placement": role["intended_placement"],
        "orientation": role["orientation"],
        "reason_codes": [reason_code],
    }


def _gap_brief(
    role: dict[str, Any],
    *,
    material_type: str,
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    reference_ids = [
        item["asset_reference"]["stable_ref"]
        for item in sorted(selected, key=_candidate_sort_key)
    ]
    role_id = role["role_id"]
    return {
        "brief_id": validate_stable_id(
            "image-gap-" + sha256_hex({"role_id": role_id, "material_type": material_type})[:24],
            "image-gap brief_id",
        ),
        "missing_visual_role_id": role_id,
        "missing_visual_role_type": role["role_type"],
        "subject_or_concept": role["role_type"],
        "instructional_purpose": role["instructional_purpose"],
        "material_type": material_type,
        "intended_placement": role["intended_placement"],
        "required_visual_style_family": "unspecified",
        "approved_reference_asset_ids_to_match": reference_ids,
        "composition": "unspecified",
        "perspective": "unspecified",
        "palette": "unspecified",
        "line_treatment": "unspecified",
        "shading_treatment": "unspecified",
        "background_requirement": "unspecified",
        "orientation": role["orientation"],
        "dimensions_or_aspect_ratio": "unspecified",
        "required_elements": [role["role_type"]],
        "excluded_elements": [],
        "intended_reusable_uses": [material_type, role["role_type"]],
        "draft_alt_text": f"{role['role_type']} visual for {material_type}.",
        "accessibility_considerations": [role["accessibility_reference"]],
        "reason_asset_is_needed": "No approved eligible asset filled this required visual role.",
        "human_review_required": True,
        "authority": dict(_AUTHORITY),
    }


def _asset_key(candidate: dict[str, Any]) -> tuple[str, str, str]:
    asset = candidate["asset_reference"]
    return (
        asset["asset_id"],
        asset["stable_ref"],
        asset["content_fingerprint"],
    )


def _candidate_sort_key(candidate: dict[str, Any]) -> str:
    return sha256_hex(
        {
            "compatibility_id": candidate["compatibility_id"],
            "asset_reference": candidate["asset_reference"],
            "library_reference": candidate["library_reference"],
            "fingerprint": candidate["fingerprint"],
        }
    )


def _plan_id(
    *,
    plan: ValidatedRecord,
    candidates: ValidatedRecord,
    required_assignments: list[dict[str, Any]],
    optional_assignments: list[dict[str, Any]],
    unfilled_required: list[dict[str, Any]],
    manual_reasons: tuple[str, ...],
) -> str:
    return validate_stable_id(
        "cohesive-visual-plan-" + sha256_hex(
            {
                "contract_version": CONTRACT_ID,
                "visual_needs_plan": plan.fingerprint,
                "candidate_filter_result": candidates.fingerprint,
                "required_assignments": required_assignments,
                "optional_assignments": optional_assignments,
                "unfilled_required": unfilled_required,
                "manual_reasons": list(manual_reasons),
            }
        )[:24],
        "cohesive_visual_plan_id",
    )
