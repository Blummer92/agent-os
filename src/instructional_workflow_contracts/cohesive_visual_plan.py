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
from .visual_asset_candidates import (
    PROJECTION_TRANSPORT_BY_REFERENCE,
    PROJECTION_TRANSPORT_INLINE,
    V2_CONTRACT_ID as CANDIDATE_CONTRACT_ID,
)
from .visual_asset_compatibility import (
    V1_CONTRACT_ID as V1_COMPATIBILITY_CONTRACT_ID,
    V2_CONTRACT_ID as V2_COMPATIBILITY_CONTRACT_ID,
)
from .visual_needs import CONTRACT_ID as VISUAL_NEEDS_CONTRACT_ID

CONTRACT_ID = "curriculum-cohesive-visual-plan-v1"
MAX_SELECTED_ASSETS = 8
MAX_GAP_BRIEFS = 8

# Canonical visual outcome-code registry is owned by #3248
# (~/workspace/wave1-campaign/outcome-code-registry.md). This module emits codes
# into that registry and must not redefine their semantics. Only "proven-absence"
# may produce an image-gap brief or authorize creation.
OUTCOME_PROVEN_ABSENCE = "proven-absence"
OUTCOME_POLICY_UNASSIGNED = "policy-unassigned"
OUTCOME_REVIEW_PENDING = "review-pending"
OUTCOME_INCOMPATIBLE = "incompatible"
OUTCOME_INACCESSIBLE = "inaccessible"
OUTCOME_INCOMPLETE_EVIDENCE = "incomplete-evidence"

# Role-intrinsic rejection reasons that classify as hard incompatibility.
_INCOMPATIBLE_ROLE_REASONS = frozenset(
    {
        "asset-role-mismatch",
        "asset-approved-use-role-mismatch",
        "asset-approved-use-material-mismatch",
        "asset-orientation-mismatch",
        "asset-audience-incompatible",
    }
)
# Filter-level rejection classification for "invalid" (unconsumable) entries.
_FILTER_INVALID_CLASSIFICATION = "invalid"
# Filter-level reason fragment marking an access/verification failure.
_ACCESS_FAILURE_REASON = "asset-compatibility-invalid-manifest"

_REMEDY_CLASS = {
    OUTCOME_PROVEN_ABSENCE: "absent",
    OUTCOME_INCOMPATIBLE: "unapproved-for-use",
    OUTCOME_INACCESSIBLE: "unapproved-for-use",
    OUTCOME_REVIEW_PENDING: "unapproved-for-use",
    OUTCOME_INCOMPLETE_EVIDENCE: "unapproved-for-use",
    OUTCOME_POLICY_UNASSIGNED: "policy-unassigned",
}

# Governed eligible-input bound, reconciled with the candidate filter's
# maximum (#3255). Above this bound the plan is INVALID with the explicit
# `capacity-exceeded` reason code: an input-contract violation, never
# absence or review.
MAX_ELIGIBLE_CANDIDATES = 64
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
    *,
    candidate_projections: object = None,
) -> ValidationResult:
    """Select one bounded cohesive visual set and deterministic gap briefs.

    ``candidate_projections`` supplies the validated compatibility records
    for a by-reference filter result: a mapping keyed by
    ``(compatibility_id, fingerprint)`` whose values are the
    ``ValidatedRecord`` instances the filter classified. Each reference is
    fingerprint-verified before selection; a missing or mismatched
    projection fails closed. Inline filter results do not need it.
    """
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

        eligible_refs = list(candidate_payload["eligible"])
        if len(eligible_refs) > MAX_ELIGIBLE_CANDIDATES:
            raise ContractValidationError(
                "capacity-exceeded",
                "eligible candidate count exceeds the governed bound",
            )
        eligible = _resolve_eligible_candidates(
            eligible_refs,
            transport=candidate_payload.get("projection_transport"),
            candidate_projections=candidate_projections,
            candidate_contract_version=candidates.contract_version,
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
                outcome_code, reason_codes, rejected_ids = _classify_unfilled_role(
                    role,
                    match,
                    candidate_payload,
                )
                unfilled_required.append(
                    _unfilled_role(
                        role,
                        outcome_code=outcome_code,
                        reason_codes=reason_codes,
                        rejected_candidate_ids=rejected_ids,
                    )
                )
                # A gap brief is emitted ONLY for proven absence: governed
                # evidence proves no eligible reusable asset exists for the role
                # under the stated scope and snapshot. Every other non-absence
                # state carries its own outcome code and never becomes a brief.
                if outcome_code == OUTCOME_PROVEN_ABSENCE:
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
                outcome_code, reason_codes, rejected_ids = _classify_unfilled_role(
                    role,
                    match,
                    candidate_payload,
                )
                unfilled_optional.append(
                    _unfilled_role(
                        role,
                        outcome_code=outcome_code,
                        reason_codes=reason_codes,
                        rejected_candidate_ids=rejected_ids,
                    )
                )
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

        # Manual-review plans never emit gap briefs: a brief asserts proven
        # absence, which a plan awaiting bounded human review cannot claim.
        gap_briefs = (
            []
            if manual_reasons
            else [
                _gap_brief(
                    role,
                    material_type=material_type,
                    selected=selected,
                    plan=plan,
                    candidates=candidates,
                    candidate_payload=candidate_payload,
                )
                for role in unfilled_required_roles
            ]
        )
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
        "eligible", "rejected", "manual_review", "capacity_exceeded",
        "projection_transport", "authority",
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


def _resolve_eligible_candidates(
    entries: list[dict[str, Any]],
    *,
    transport: object,
    candidate_projections: object,
    candidate_contract_version: str,
) -> list[dict[str, Any]]:
    """Resolve eligible entries to the full candidate dicts selection consumes.

    Inline entries are used directly. By-reference entries are resolved
    through the caller-supplied projection store with fingerprint
    verification: the store record's identity and exact bytes must match
    the reference, and its contract version must be the compatibility
    version the filter classified. Anything else fails closed. The resolved
    dicts are byte-identical to the inline entries the filter would have
    carried, so selection is transport-independent.
    """
    if transport is None or transport == PROJECTION_TRANSPORT_INLINE:
        return entries
    if transport != PROJECTION_TRANSPORT_BY_REFERENCE:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-candidates",
            "candidate-filter projection transport is not supported",
        )
    if candidate_projections is None:
        raise ContractValidationError(
            "asset-cohesive-plan-missing-projections",
            "by-reference candidate result requires candidate projections",
        )
    if type(candidate_projections) is not dict:
        raise ContractValidationError(
            "asset-cohesive-plan-invalid-projections",
            "candidate projections must be a mapping",
        )
    expected_compatibility_version = (
        V1_COMPATIBILITY_CONTRACT_ID
        if candidate_contract_version
        == "curriculum-visual-asset-candidates-v1"
        else V2_COMPATIBILITY_CONTRACT_ID
    )
    resolved: list[dict[str, Any]] = []
    for entry in entries:
        if type(entry) is not dict:
            raise ContractValidationError(
                "asset-cohesive-plan-projection-mismatch",
                "candidate reference must be a built-in mapping",
            )
        compatibility_id = entry.get("compatibility_id")
        fingerprint = entry.get("fingerprint")
        record = candidate_projections.get((compatibility_id, fingerprint))
        if type(record) is not ValidatedRecord:
            raise ContractValidationError(
                "asset-cohesive-plan-projection-mismatch",
                "candidate projection is missing or not a validated record",
            )
        if (
            record.record_id != compatibility_id
            or record.fingerprint != fingerprint
        ):
            raise ContractValidationError(
                "asset-cohesive-plan-projection-mismatch",
                "candidate projection identity does not match its reference",
            )
        if record.contract_version != expected_compatibility_version:
            raise ContractValidationError(
                "asset-cohesive-plan-projection-mismatch",
                "candidate projection contract version is incompatible",
            )
        projection = record.to_dict()
        resolved.append(
            {
                "compatibility_contract_version": record.contract_version,
                "compatibility_id": record.record_id,
                "compatibility_record_revision": record.record_revision,
                "fingerprint": record.fingerprint,
                "classification": projection["classification"],
                "reason_codes": list(projection["reason_codes"]),
                "manifest_reference": projection["manifest_reference"],
                "asset_reference": projection["asset_reference"],
                "library_reference": projection["library_reference"],
                "purpose": projection["purpose"],
                "approved_use": projection["approved_use"],
                "orientation": projection["orientation"],
                "accessibility": projection["accessibility"],
                "freshness": projection["freshness"],
                "matched_asset": projection["matched_asset"],
                "cohesion_profile": projection.get("cohesion_profile"),
                "authority": projection["authority"],
            }
        )
    return resolved


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
    # Candidates that pass role-intrinsic rejection but fail set-level rejection
    # (cohesion / load / duplicate-selected against the already-selected set).
    role_eligible: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    # Candidates rejected for role-intrinsic reasons, with those reasons.
    role_rejections: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    for candidate in candidates:
        reasons = _role_rejection_reasons(
            role,
            candidate,
            material_type=material_type,
        )
        if reasons:
            rejected_assignments.append(_rejection(role, candidate, reasons))
            role_rejections.append((candidate, reasons))
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
            role_eligible.append((candidate, set_reasons))
            continue
        score = _score(role, candidate)
        viable.append((score, _candidate_sort_key(candidate), candidate))

    if not viable:
        return {
            "candidate": None,
            "manual_review": tuple(sorted(manual)),
            "role_eligible": role_eligible,
            "role_rejections": role_rejections,
        }

    viable.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], -item[0][3], item[1]))
    if len(viable) > 1 and viable[0][0] == viable[1][0]:
        manual.add("manual-review-visual-assignment-tie")
        return {
            "candidate": None,
            "manual_review": tuple(sorted(manual)),
            "role_eligible": role_eligible,
            "role_rejections": role_rejections,
        }
    return {
        "candidate": viable[0][2],
        "manual_review": tuple(sorted(manual)),
        "role_eligible": role_eligible,
        "role_rejections": role_rejections,
    }


def _classify_unfilled_role(
    role: dict[str, Any],
    match: dict[str, Any],
    candidate_payload: dict[str, Any],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Classify one unfilled role into the canonical outcome-code registry.

    Returns (outcome_code, reason_codes, rejected_candidate_ids). Only
    ``proven-absence`` may later become an image-gap brief.
    """
    del role  # classification uses the match and filter evidence only
    if "manual-review-visual-assignment-tie" in match["manual_review"]:
        return (
            OUTCOME_REVIEW_PENDING,
            (OUTCOME_REVIEW_PENDING, "asset-required-role-tie-blocked"),
            (),
        )
    role_eligible = match["role_eligible"]
    if role_eligible:
        # Eligible candidates exist for this role but assignment policy rejected
        # every one of them (cohesion / load / duplicate-selected). Per #3248
        # this is policy-unassigned, reported with the candidate identities —
        # never a visual gap.
        set_reasons: set[str] = set()
        rejected_ids: list[str] = []
        for candidate, reasons in role_eligible:
            set_reasons.update(reasons)
            rejected_ids.append(candidate["compatibility_id"])
        return (
            OUTCOME_POLICY_UNASSIGNED,
            (OUTCOME_POLICY_UNASSIGNED, *sorted(set_reasons)),
            tuple(sorted(set(rejected_ids))),
        )
    if candidate_payload["manual_review"]:
        return (OUTCOME_REVIEW_PENDING, (OUTCOME_REVIEW_PENDING,), ())
    if candidate_payload["eligible"]:
        # Candidates exist but none is role-eligible for this role.
        intrinsic: set[str] = set()
        for _, reasons in match["role_rejections"]:
            intrinsic.update(reasons)
        if intrinsic & _INCOMPATIBLE_ROLE_REASONS:
            return (
                OUTCOME_INCOMPATIBLE,
                (OUTCOME_INCOMPATIBLE, *sorted(intrinsic)),
                (),
            )
        if "asset-cohesion-missing" in intrinsic:
            return (
                OUTCOME_INCOMPLETE_EVIDENCE,
                (OUTCOME_INCOMPLETE_EVIDENCE, "asset-cohesion-missing"),
                (),
            )
        return (OUTCOME_INCOMPATIBLE, (OUTCOME_INCOMPATIBLE,), ())
    if candidate_payload["rejected"]:
        # The filter saw assets but rejected every one of them. An access /
        # verification failure means the asset exists but cannot be recovered
        # (inaccessible), even when the filter also marks the entry invalid.
        access_failure = any(
            _ACCESS_FAILURE_REASON in entry.get("reason_codes", [])
            for entry in candidate_payload["rejected"]
        )
        if access_failure:
            return (OUTCOME_INACCESSIBLE, (OUTCOME_INACCESSIBLE,), ())
        invalid = any(
            entry.get("classification") == _FILTER_INVALID_CLASSIFICATION
            for entry in candidate_payload["rejected"]
        )
        if invalid:
            return (OUTCOME_INCOMPLETE_EVIDENCE, (OUTCOME_INCOMPLETE_EVIDENCE,), ())
        return (OUTCOME_INCOMPATIBLE, (OUTCOME_INCOMPATIBLE,), ())
    # The filter ran over an identified read (source_revision is required
    # non-empty by the filter contract) and admitted zero candidates in every
    # group: governed evidence proves no eligible reusable asset exists for this
    # role under the stated scope and snapshot.
    return (OUTCOME_PROVEN_ABSENCE, (OUTCOME_PROVEN_ABSENCE,), ())


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


def _unfilled_role(
    role: dict[str, Any],
    *,
    outcome_code: str,
    reason_codes: tuple[str, ...],
    rejected_candidate_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "role_id": role["role_id"],
        "role_type": role["role_type"],
        "requirement_state": role["requirement_state"],
        "instructional_purpose": role["instructional_purpose"],
        "intended_placement": role["intended_placement"],
        "orientation": role["orientation"],
        # Canonical outcome-code registry (#3248): the single machine-readable
        # classification of why this role went unfilled. Only "proven-absence"
        # may become an image-gap brief.
        "outcome_code": outcome_code,
        "reason_codes": list(reason_codes),
        # Candidate identities rejected for this role (populated for
        # policy-unassigned so the policy owner can adjudicate).
        "rejected_candidate_ids": list(rejected_candidate_ids),
        "remedy_class": _REMEDY_CLASS[outcome_code],
    }


def _gap_brief(
    role: dict[str, Any],
    *,
    material_type: str,
    selected: list[dict[str, Any]],
    plan: ValidatedRecord,
    candidates: ValidatedRecord,
    candidate_payload: dict[str, Any],
) -> dict[str, Any]:
    reference_ids = [
        item["asset_reference"]["stable_ref"]
        for item in sorted(selected, key=_candidate_sort_key)
    ]
    role_id = role["role_id"]
    # #3254: concept/vocabulary carry-through. The brief carries the role's
    # concept when the requirement author supplied one; otherwise the role
    # type. Never invented.
    concept = role.get("concept") or role["role_type"]
    return {
        "brief_id": validate_stable_id(
            "image-gap-" + sha256_hex({"role_id": role_id, "material_type": material_type})[:24],
            "image-gap brief_id",
        ),
        "missing_visual_role_id": role_id,
        "missing_visual_role_type": role["role_type"],
        "subject_or_concept": concept,
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
        # Proven-absence assertion, backed by the recorded evidence below. A
        # brief is emitted ONLY when governed evidence proves no eligible
        # reusable asset exists for this role under the stated scope/snapshot.
        "reason_asset_is_needed": (
            "Governed evidence proves no eligible reusable asset exists for "
            "this required visual role under the stated scope and snapshot."
        ),
        # Tamper-evident absence evidence: the binding admission checks this
        # block before any ImageIntent handoff is authorized.
        "absence_evidence": {
            "proven_absence": True,
            "scope": {
                "visual_needs_plan_id": plan.record_id,
                "material_type": material_type,
            },
            "snapshot": {
                "candidate_filter_id": candidates.record_id,
                "candidate_filter_fingerprint": candidates.fingerprint,
                "source_revision": candidate_payload["source_revision"],
            },
            "filter_evidence": {
                "candidate_count": candidate_payload["candidate_count"],
                "eligible": len(candidate_payload["eligible"]),
                "rejected": len(candidate_payload["rejected"]),
                "manual_review": len(candidate_payload["manual_review"]),
            },
            "remedy_class": "absent",
        },
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
