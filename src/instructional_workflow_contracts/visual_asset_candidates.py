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
MAX_CANDIDATES = 32
MAX_SOURCE_REVISION_LENGTH = 256


def filter_approved_visual_candidates(
    visual_needs_plan: object,
    candidates: object,
    *,
    source_revision: object,
    contract_version: object = CONTRACT_ID,
) -> ValidationResult:
    """Return bounded eligible, rejected, and manual-review candidate groups."""
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
        required_roles = {
            item["role_type"]: item
            for item in plan_payload["required_roles"]
        }
        optional_roles = {
            item["role_type"]: item
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

            reasons = _plan_mismatch_reasons(
                payload,
                governed_roles=governed_roles,
                material_type=plan_payload["material_type"],
            )
            if reasons:
                entry["classification"] = "hard-rejection"
                entry["reason_codes"] = list(reasons)
                rejected.append(entry)
            else:
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

        payload = {
            "contract_version": selected_contract_version,
            "candidate_set_id": _candidate_set_id(
                contract_version=selected_contract_version,
                plan=plan,
                source_revision=revision,
                eligible=eligible,
                rejected=rejected,
                manual_review=manual_review,
            ),
            "source_revision": revision,
            "visual_needs_plan": {
                "contract_version": plan.contract_version,
                "plan_id": plan.record_id,
                "record_revision": plan.record_revision,
                "fingerprint": plan.fingerprint,
            },
            "maximum_candidate_count": MAX_CANDIDATES,
            "candidate_count": len(raw_candidates),
            "eligible": eligible,
            "rejected": rejected,
            "manual_review": manual_review,
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
                "side_effects_performed": False,
            },
        }
        normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
        if type(normalized) is not dict:
            raise ContractValidationError(
                "asset-candidates-invalid",
                "visual candidate result must be a built-in mapping",
            )
        if canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized",
                "visual candidate result exceeds the shared result-size bound",
            )
        record = ValidatedRecord(
            contract_version=selected_contract_version,
            record_id=normalized["candidate_set_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )
        if manual_review:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=("manual-review-visual-candidates",),
                details=("one or more candidates require bounded human review",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("asset-candidates-invalid", sanitize_detail(str(exc)))


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
        if type(role) is not dict or "role_type" not in role or "orientation" not in role:
            raise ContractValidationError(
                "asset-candidates-invalid-plan",
                "visual-needs role entries must declare role_type and orientation",
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
            "handoff-oversized",
            "visual candidates exceed the 32-candidate bound",
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
) -> tuple[str, ...]:
    reasons: list[str] = []
    compatible_roles = set(compatibility["purpose"]["role_types"])
    approved_roles = set(compatibility["approved_use"]["role_types"])
    matched_roles = compatible_roles & approved_roles & set(governed_roles)
    if not matched_roles:
        reasons.append("visual-candidate-role-mismatch")
    approved_materials = set(compatibility["approved_use"]["material_types"])
    if material_type not in approved_materials:
        reasons.append("visual-candidate-material-mismatch")
    orientation = compatibility["orientation"]["orientation"]
    if matched_roles and orientation != "flexible":
        if not any(
            governed_roles[role]["orientation"] in {orientation, "unspecified"}
            for role in matched_roles
        ):
            reasons.append("visual-candidate-orientation-mismatch")
    return tuple(sorted(reasons))


def _candidate_set_id(
    *,
    contract_version: str,
    plan: ValidatedRecord,
    source_revision: str,
    eligible: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> str:
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
