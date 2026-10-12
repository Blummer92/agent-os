"""Pure deterministic filtering of governed visual-asset candidates."""

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
    validate_text,
)
from .visual_asset_compatibility import (
    V1_CONTRACT_ID as V1_COMPATIBILITY_CONTRACT_ID,
    V2_CONTRACT_ID as V2_COMPATIBILITY_CONTRACT_ID,
    validate_visual_asset_compatibility_evidence,
)
from .visual_needs import CONTRACT_ID as VISUAL_NEEDS_CONTRACT_ID

V1_CONTRACT_ID = "curriculum-visual-asset-candidates-v1"
V2_CONTRACT_ID = "curriculum-visual-asset-candidates-v2"

# Existing callers remain explicitly bound to the v1 projection.
CONTRACT_ID = V1_CONTRACT_ID
# Governed input bound, reconciled with the Asset Picker's maximum (#3255).
# Above this bound the query is INVALID with the explicit `capacity-exceeded`
# reason code: an input-contract violation, never absence or review.
MAX_CANDIDATES = 64
MAX_SOURCE_REVISION_LENGTH = 256

# Projection transport markers for the filter result record.
PROJECTION_TRANSPORT_INLINE = "inline"
PROJECTION_TRANSPORT_BY_REFERENCE = "by-reference"

# Measurement-only normalization budget for the transport decision. The
# governed 16 KiB result bound is enforced by the explicit canonical-size
# check, never by this budget.
_MEASUREMENT_BYTES = 1024 * 1024


def filter_approved_visual_candidates(
    visual_needs_plan: object,
    candidates: object,
    *,
    source_revision: object,
    contract_version: object = CONTRACT_ID,
) -> ValidationResult:
    """Return bounded eligible, rejected, and manual-review candidate groups.

    The result record is transported inline while it fits the governed
    16 KiB result bound; larger populations are handed off by reference
    (compact identity entries resolved through a caller-supplied projection
    store). Overflow that even the by-reference form cannot carry is reported
    per item with the explicit `capacity-exceeded` outcome -- never as a
    whole-query failure, never as absence, never as review.
    """
    return _filter_with_transport_bound(
        visual_needs_plan,
        candidates,
        source_revision=source_revision,
        contract_version=contract_version,
        transport_bound=MAX_RESULT_BYTES,
    )


def _filter_with_transport_bound(
    visual_needs_plan: object,
    candidates: object,
    *,
    source_revision: object,
    contract_version: object,
    transport_bound: int,
) -> ValidationResult:
    """Filter implementation with an explicit result-transport bound.

    Production always passes the governed ``MAX_RESULT_BYTES``. Tests may
    pass a different bound to force a specific transport for equivalence
    testing (e.g. a tiny bound forces the by-reference form on a small
    population, proving selection is transport-independent).
    """
    try:
        plan = _plan_record(visual_needs_plan)
        plan_payload = plan.to_dict()
        if plan_payload["outcome"] != "visuals-required":
            raise ContractValidationError(
                "asset-candidates-plan-not-actionable",
                "visual-needs plan must require visuals",
            )

        selected_contract_version = _candidate_contract_version(
            contract_version
        )
        expected_compatibility_version = (
            V1_COMPATIBILITY_CONTRACT_ID
            if selected_contract_version == V1_CONTRACT_ID
            else V2_COMPATIBILITY_CONTRACT_ID
        )
        revision = validate_text(
            source_revision,
            "source_revision",
            max_length=MAX_SOURCE_REVISION_LENGTH,
        )
        raw_candidates = _candidate_list(candidates)
        # #3251: roles are keyed by stable role_id, never by role_type.
        # Two roles sharing a role_type keep their own orientation and
        # compatibility evidence; same-type roles never collapse.
        required_roles = {
            item["role_id"]: item
            for item in plan_payload["required_roles"]
        }
        optional_roles = {
            item["role_id"]: item
            for item in plan_payload["optional_roles"]
        }
        governed_roles = {**optional_roles, **required_roles}

        eligible: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        manual_review: list[dict[str, Any]] = []

        for candidate in raw_candidates:
            result = validate_visual_asset_compatibility_evidence(candidate)
            if result.record is None:
                rejected.append(
                    _candidate_entry(
                        result,
                        contract_version=selected_contract_version,
                    )
                )
                continue

            payload = result.record.to_dict()
            if result.record.contract_version != expected_compatibility_version:
                entry = _candidate_entry(
                    result,
                    contract_version=selected_contract_version,
                    include_projection=False,
                )
                entry["classification"] = "invalid"
                entry["reason_codes"] = [
                    "visual-candidate-contract-incompatible"
                ]
                rejected.append(entry)
                continue

            entry = _candidate_entry(
                result,
                contract_version=selected_contract_version,
            )
            classification = payload["classification"]
            if classification == "hard-rejection":
                rejected.append(entry)
                continue
            if classification == "manual-review-required":
                manual_review.append(entry)
                continue

            reasons, matched_role_ids = _plan_mismatch_reasons(
                payload,
                governed_roles=governed_roles,
                material_type=plan_payload["material_type"],
            )
            if reasons:
                entry["classification"] = "hard-rejection"
                entry["reason_codes"] = list(reasons)
                rejected.append(entry)
            else:
                # The roles that admitted this candidate stay recoverable
                # downstream (#3251): eligibility is per role, not per type.
                entry["matched_role_ids"] = list(matched_role_ids)
                eligible.append(entry)

        def key(item: dict[str, Any]) -> tuple[object, ...]:
            return (
                item.get("compatibility_id") or "",
                item.get("fingerprint") or "",
                tuple(item["reason_codes"]),
                sha256_hex(item),
            )

        eligible.sort(key=key)
        rejected.sort(key=key)
        manual_review.sort(key=key)

        return _assemble_result(
            selected_contract_version=selected_contract_version,
            plan=plan,
            plan_payload=plan_payload,
            source_revision=revision,
            eligible=eligible,
            rejected=rejected,
            manual_review=manual_review,
            candidate_count=len(raw_candidates),
            transport_bound=transport_bound,
        )
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("asset-candidates-invalid", sanitize_detail(str(exc)))


def _assemble_result(
    *,
    selected_contract_version: str,
    plan: ValidatedRecord,
    plan_payload: dict[str, Any],
    source_revision: str,
    eligible: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
    candidate_count: int,
    transport_bound: int,
) -> ValidationResult:
    """Assemble the bounded result record, choosing the projection transport.

    The candidate-set identity binds the full classification (transport
    independent). The payload is transported inline while it fits the
    governed bound; larger populations travel by reference; a population
    that even the by-reference form cannot carry degrades per item to the
    explicit ``capacity-exceeded`` outcome instead of failing the query.
    """
    candidate_set_id = _candidate_set_id(
        contract_version=selected_contract_version,
        plan=plan,
        source_revision=source_revision,
        eligible=[_compact_reference(item) for item in eligible],
        rejected=[_compact_reference(item) for item in rejected],
        manual_review=[_compact_reference(item) for item in manual_review],
    )
    header = {
        "contract_version": selected_contract_version,
        "candidate_set_id": candidate_set_id,
        "source_revision": source_revision,
        "visual_needs_plan": {
            "contract_version": plan.contract_version,
            "plan_id": plan.record_id,
            "record_revision": plan.record_revision,
            "fingerprint": plan.fingerprint,
        },
        "maximum_candidate_count": MAX_CANDIDATES,
        "candidate_count": candidate_count,
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
            "side_effects_performed": False,
        },
    }

    inline_payload = {
        **header,
        "eligible": eligible,
        "rejected": rejected,
        "manual_review": manual_review,
        "capacity_exceeded": [],
        "projection_transport": PROJECTION_TRANSPORT_INLINE,
    }
    if _measured_size(inline_payload) <= transport_bound:
        return _finalize_result(
            selected_contract_version=selected_contract_version,
            normalized=validate_and_normalize_json(
                inline_payload, max_bytes=transport_bound
            ),
            manual_review_present=bool(manual_review),
        )

    by_reference_payload = {
        **header,
        "eligible": [_compact_reference(item) for item in eligible],
        "rejected": [_compact_reference(item) for item in rejected],
        "manual_review": [_compact_reference(item) for item in manual_review],
        "capacity_exceeded": [],
        "projection_transport": PROJECTION_TRANSPORT_BY_REFERENCE,
    }
    if _measured_size(by_reference_payload) <= transport_bound:
        return _finalize_result(
            selected_contract_version=selected_contract_version,
            normalized=validate_and_normalize_json(
                by_reference_payload, max_bytes=transport_bound
            ),
            manual_review_present=bool(manual_review),
        )

    return _assemble_with_capacity_markers(
        selected_contract_version=selected_contract_version,
        header=header,
        eligible=eligible,
        rejected=rejected,
        manual_review=manual_review,
        transport_bound=transport_bound,
    )


def _measured_size(payload: dict[str, Any]) -> int:
    """Canonical size of a candidate payload, measured without the transport bound.

    Any bound exceedance during measurement means the payload does not fit
    the inline transport; it is reported as infinite size so the caller
    falls through to the by-reference form.
    """
    try:
        return canonical_size(
            validate_and_normalize_json(payload, max_bytes=_MEASUREMENT_BYTES)
        )
    except ContractValidationError:
        return _MEASUREMENT_BYTES + 1


def _compact_reference(entry: dict[str, Any]) -> dict[str, Any]:
    """Reduce one classified entry to its transport reference.

    The (compatibility_id, fingerprint) pair is the lookup key into the
    caller-supplied projection store; the fingerprint binds the exact
    validated record bytes (including contract version and revision), and
    classification plus reason codes preserve the eligibility evidence.
    """
    return {
        "compatibility_id": entry.get("compatibility_id"),
        "fingerprint": entry.get("fingerprint"),
        "classification": entry.get("classification"),
        "reason_codes": list(entry.get("reason_codes", [])),
    }


def _capacity_marker(entry: dict[str, Any], *, original_group: str) -> dict[str, Any]:
    """Mark one entry the bounded transport could not carry.

    Explicit per-item ``capacity-exceeded``: the candidate was classified,
    but its reference did not fit the result bound. It is never eligible,
    never absence, never review. The marker carries only the candidate
    identity (the fingerprint-bound full classification lives in the
    candidate-set identity); it is deliberately smaller than a reference
    so the degradation loop always converges.
    """
    return {
        "compatibility_id": entry.get("compatibility_id"),
        "classification": "capacity-exceeded",
        "reason_codes": ["capacity-exceeded"],
        "original_group": original_group,
    }


def _assemble_with_capacity_markers(
    *,
    selected_contract_version: str,
    header: dict[str, Any],
    eligible: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
    transport_bound: int,
) -> ValidationResult:
    """Degrade per item when even the by-reference form overflows the bound.

    References convert to ``capacity-exceeded`` markers from the lowest
    transport priority (rejected, then manual-review, then eligible) in
    deterministic sorted order until the record fits. Markers are strictly
    smaller than references, so the loop terminates.
    """
    kept: dict[str, list[dict[str, Any]]] = {
        "eligible": [_compact_reference(item) for item in eligible],
        "manual_review": [_compact_reference(item) for item in manual_review],
        "rejected": [_compact_reference(item) for item in rejected],
    }
    markers: list[dict[str, Any]] = []
    while True:
        payload = {
            **header,
            "eligible": kept["eligible"],
            "rejected": kept["rejected"],
            "manual_review": kept["manual_review"],
            "capacity_exceeded": markers,
            "projection_transport": PROJECTION_TRANSPORT_BY_REFERENCE,
        }
        if _measured_size(payload) <= transport_bound:
            return _finalize_result(
                selected_contract_version=selected_contract_version,
                normalized=validate_and_normalize_json(
                    payload, max_bytes=transport_bound
                ),
                manual_review_present=bool(manual_review),
            )
        converted = False
        for group in ("rejected", "manual_review", "eligible"):
            if kept[group]:
                markers.append(
                    _capacity_marker(kept[group].pop(), original_group=group)
                )
                converted = True
                break
        if not converted:
            raise ContractValidationError(
                "capacity-exceeded",
                "candidate result cannot fit the bounded transport",
            )


def _finalize_result(
    *,
    selected_contract_version: str,
    normalized: Any,
    manual_review_present: bool,
) -> ValidationResult:
    if type(normalized) is not dict:
        raise ContractValidationError(
            "asset-candidates-invalid",
            "visual candidate result must be a built-in mapping",
        )
    record = ValidatedRecord(
        contract_version=selected_contract_version,
        record_id=normalized["candidate_set_id"],
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(normalized),
        payload=freeze_json(normalized),
    )
    if manual_review_present:
        return ValidationResult(
            status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
            record=record,
            reason_codes=("manual-review-visual-candidates",),
            details=("one or more candidates require bounded human review",),
        )
    return ValidationResult(status=ValidationStatus.VALID, record=record)


def _plan_record(value: object) -> ValidatedRecord:
    supplied: ValidatedRecord
    if type(value) is ValidationResult:
        if value.status is not ValidationStatus.VALID or value.record is None:
            raise ContractValidationError(
                "asset-candidates-invalid-plan",
                "visual-needs result must be valid and contain a record",
            )
        supplied = value.record
    elif type(value) is ValidatedRecord:
        supplied = value
    else:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan must be validated evidence",
        )

    if supplied.contract_version != VISUAL_NEEDS_CONTRACT_ID:
        raise ContractValidationError(
            "asset-candidates-incompatible-plan",
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
            "asset-candidates-invalid-plan",
            "visual-needs plan fields are not exact",
        )
    validate_stable_id(payload["plan_id"], "visual-needs plan_id")
    if payload["plan_id"] != supplied.record_id:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan identity does not match its validated record",
        )
    validate_revision(supplied.record_revision)
    if sha256_hex(payload) != supplied.fingerprint:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs plan fingerprint does not reconstruct exactly",
        )
    if type(payload["required_roles"]) is not list or type(payload["optional_roles"]) is not list:
        raise ContractValidationError(
            "asset-candidates-invalid-plan",
            "visual-needs roles must be built-in lists",
        )
    for role in [*payload["required_roles"], *payload["optional_roles"]]:
        if (
            type(role) is not dict
            or "role_id" not in role
            or "role_type" not in role
            or "orientation" not in role
        ):
            raise ContractValidationError(
                "asset-candidates-invalid-plan",
                "visual-needs role entries must declare role_id, role_type and orientation",
            )
    return supplied


def _candidate_list(value: object) -> list[object]:
    if type(value) is not list:
        raise ContractValidationError(
            "handoff-wrong-type",
            "visual candidates must be a built-in list",
        )
    if len(value) > MAX_CANDIDATES:
        raise ContractValidationError(
            "capacity-exceeded",
            "visual candidates exceed the 64-candidate bound",
        )
    return value


def _candidate_contract_version(value: object) -> str:
    version = validate_text(
        value,
        "candidate contract_version",
        max_length=64,
    )
    if version not in {V1_CONTRACT_ID, V2_CONTRACT_ID}:
        raise ContractValidationError(
            "handoff-version-unsupported",
            "visual candidate contract version is unsupported",
        )
    return version


def _candidate_entry(
    result: ValidationResult,
    *,
    contract_version: str,
    include_projection: bool = True,
) -> dict[str, Any]:
    if contract_version == V1_CONTRACT_ID:
        if result.record is None:
            return {
                "compatibility_id": None,
                "fingerprint": None,
                "classification": "invalid",
                "reason_codes": list(result.reason_codes),
                "asset_reference": None,
                "library_reference": None,
            }
        payload = result.record.to_dict()
        return {
            "compatibility_id": result.record.record_id,
            "fingerprint": result.record.fingerprint,
            "classification": payload["classification"],
            "reason_codes": list(payload["reason_codes"]),
            "asset_reference": payload["asset_reference"],
            "library_reference": payload["library_reference"],
        }

    if result.record is None:
        return {
            "compatibility_contract_version": None,
            "compatibility_id": None,
            "compatibility_record_revision": None,
            "fingerprint": None,
            "classification": "invalid",
            "reason_codes": list(result.reason_codes),
        }

    payload = result.record.to_dict()
    entry: dict[str, Any] = {
        "compatibility_contract_version": result.record.contract_version,
        "compatibility_id": result.record.record_id,
        "compatibility_record_revision": result.record.record_revision,
        "fingerprint": result.record.fingerprint,
        "classification": payload["classification"],
        "reason_codes": list(payload["reason_codes"]),
    }
    if not include_projection:
        return entry

    entry.update(
        {
            "manifest_reference": payload["manifest_reference"],
            "asset_reference": payload["asset_reference"],
            "library_reference": payload["library_reference"],
            "purpose": payload["purpose"],
            "approved_use": payload["approved_use"],
            "orientation": payload["orientation"],
            "accessibility": payload["accessibility"],
            "freshness": payload["freshness"],
            "matched_asset": payload["matched_asset"],
            "cohesion_profile": payload["cohesion_profile"],
            "authority": payload["authority"],
        }
    )
    return entry


def _plan_mismatch_reasons(
    compatibility: dict[str, Any],
    *,
    governed_roles: dict[str, dict[str, Any]],
    material_type: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Evaluate one candidate against every governed role individually.

    Returns ``(reason codes, matched role ids)``. A role admits the
    candidate only when the candidate's purpose and approved use both name
    the role's type AND the orientation policy accepts the role's own
    orientation. Two roles sharing a ``role_type`` are judged on their own
    terms (#3251): the landscape role admits a landscape candidate even
    when its same-type sibling is portrait.
    """
    reasons: list[str] = []
    matched: list[str] = []
    compatible_types = set(compatibility["purpose"]["role_types"])
    approved_types = set(compatibility["approved_use"]["role_types"])
    orientation = compatibility["orientation"]["orientation"]
    type_matched_any = False
    for role_id in sorted(governed_roles):
        role = governed_roles[role_id]
        role_type = role["role_type"]
        if role_type not in compatible_types or role_type not in approved_types:
            continue
        type_matched_any = True
        role_orientation = role["orientation"]
        if orientation != "flexible" and role_orientation not in {
            orientation,
            "unspecified",
        }:
            continue
        matched.append(role_id)
    if not type_matched_any:
        reasons.append("visual-candidate-role-mismatch")
    elif not matched:
        reasons.append("visual-candidate-orientation-mismatch")
    approved_materials = set(compatibility["approved_use"]["material_types"])
    if material_type not in approved_materials:
        reasons.append("visual-candidate-material-mismatch")
    return tuple(sorted(reasons)), tuple(matched)


def _candidate_set_id(
    *,
    contract_version: str,
    plan: ValidatedRecord,
    source_revision: str,
    eligible: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> str:
    """Derive the transport-independent candidate-set identity.

    The identity binds the compact classification references; each
    reference's fingerprint binds the exact validated compatibility record
    bytes, so the full classification is content-addressed without
    embedding full projections in the hashed identity.
    """
    identity = {
        "contract_version": contract_version,
        "plan_id": plan.record_id,
        "plan_revision": plan.record_revision,
        "plan_fingerprint": plan.fingerprint,
        "source_revision": source_revision,
        "eligible": eligible,
        "rejected": rejected,
        "manual_review": manual_review,
    }
    return validate_stable_id(
        "visual-candidates-" + sha256_hex(identity)[:24],
        "candidate_set_id",
    )
