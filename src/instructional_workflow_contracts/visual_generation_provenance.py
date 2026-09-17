"""Pure provenance bridge from one visual gap through returned-image intake.

This module binds already-validated evidence. It performs no image generation,
provider execution, duplicate detection, routing mutation, external write, or
readiness/approval mutation.
"""

from __future__ import annotations

from typing import Any

from .cohesive_visual_plan import CONTRACT_ID as COHESIVE_VISUAL_PLAN_CONTRACT_ID
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
from .image_intent import (
    IMAGE_INTENT_CONTRACT_ID,
    IMPORTED_ASSET_CONTEXT_CONTRACT_ID,
    validate_image_intent,
    validate_imported_asset_context,
)

GENERATION_HANDOFF_CONTRACT_ID = "curriculum-visual-generation-handoff-v1"
RETURNED_IMAGE_BINDING_CONTRACT_ID = "curriculum-returned-image-binding-v1"
ASSOCIATION_STATES = frozenset(
    {"exact", "teacher-confirmed", "corrected", "manual-review-required"}
)
_AUTHORITY = {
    "execution_authorized": False,
    "external_write_authorized": False,
    "production_authorized": False,
    "publication_authorized": False,
}


def bind_gap_to_image_intent(
    cohesive_visual_plan: ValidatedRecord,
    *,
    brief_id: str,
    missing_visual_role_id: str,
    image_intent: ValidatedRecord,
) -> ValidationResult:
    """Bind one exact ImageGapBrief to one exact validated ImageIntent."""
    try:
        plan = _validated_cohesive_plan(cohesive_visual_plan)
        gap_brief = _find_exact_gap(plan, brief_id, missing_visual_role_id)
        intent = _validated_image_intent(image_intent)

        payload = {
            "contract_version": GENERATION_HANDOFF_CONTRACT_ID,
            "handoff_id": validate_stable_id(
                "visual-generation-handoff-"
                + sha256_hex(
                    {
                        "plan_id": plan.record_id,
                        "plan_fingerprint": plan.fingerprint,
                        "brief_id": gap_brief["brief_id"],
                        "missing_visual_role_id": gap_brief["missing_visual_role_id"],
                        "intent_id": intent.record_id,
                        "intent_fingerprint": intent.fingerprint,
                    }
                )[:24],
                "handoff_id",
            ),
            "source_cohesive_visual_plan": {
                "contract_version": plan.contract_version,
                "plan_id": plan.record_id,
                "record_revision": plan.record_revision,
                "fingerprint": plan.fingerprint,
            },
            "source_gap": {
                "brief_id": gap_brief["brief_id"],
                "missing_visual_role_id": gap_brief["missing_visual_role_id"],
            },
            "image_intent": {
                "contract_version": intent.contract_version,
                "intent_id": intent.record_id,
                "record_revision": intent.record_revision,
                "fingerprint": intent.fingerprint,
            },
            "association_state": "exact",
            "authority": dict(_AUTHORITY),
        }
        return _record(payload, GENERATION_HANDOFF_CONTRACT_ID, payload["handoff_id"])
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("visual-generation-provenance-invalid", sanitize_detail(str(exc)))


def bind_returned_image_intake(
    generation_handoff: ValidatedRecord,
    *,
    imported_asset_context: ValidatedRecord,
    intake_id: str,
    association_state: str = "exact",
    prior_generation_handoff_id: str | None = None,
) -> ValidationResult:
    """Associate one returned intake with one exact generation handoff.

    ``intake_id`` is caller-supplied evidence from the existing visual-asset
    intake owner. Filename, prompt text, provider/model claims, source notes, and
    image similarity are deliberately excluded from association identity.
    """
    try:
        handoff = _validated_generation_handoff(generation_handoff)
        context = _validated_imported_context(imported_asset_context)
        intake = validate_stable_id(intake_id, "intake_id")
        if association_state not in ASSOCIATION_STATES:
            raise ContractValidationError(
                "visual-generation-association-invalid",
                "association_state is unsupported",
            )
        prior = None
        if prior_generation_handoff_id is not None:
            prior = validate_stable_id(prior_generation_handoff_id, "prior_generation_handoff_id")
        if association_state == "corrected" and prior is None:
            raise ContractValidationError(
                "visual-generation-association-review-required",
                "corrected association must preserve the prior generation handoff",
            )
        if association_state != "corrected" and prior is not None:
            raise ContractValidationError(
                "visual-generation-association-invalid",
                "prior generation handoff is allowed only for corrected associations",
            )

        payload = {
            "contract_version": RETURNED_IMAGE_BINDING_CONTRACT_ID,
            "binding_id": validate_stable_id(
                "returned-image-binding-"
                + sha256_hex(
                    {
                        "generation_handoff_id": handoff.record_id,
                        "generation_handoff_fingerprint": handoff.fingerprint,
                        "imported_asset_context_id": context.record_id,
                        "imported_asset_context_fingerprint": context.fingerprint,
                        "intake_id": intake,
                        "association_state": association_state,
                        "prior_generation_handoff_id": prior,
                    }
                )[:24],
                "binding_id",
            ),
            "generation_handoff": {
                "contract_version": handoff.contract_version,
                "handoff_id": handoff.record_id,
                "record_revision": handoff.record_revision,
                "fingerprint": handoff.fingerprint,
            },
            "imported_asset_context": {
                "contract_version": context.contract_version,
                "context_id": context.record_id,
                "record_revision": context.record_revision,
                "fingerprint": context.fingerprint,
            },
            "intake_id": intake,
            "association_state": association_state,
            "prior_generation_handoff_id": prior,
            "authority": dict(_AUTHORITY),
        }
        status = (
            ValidationStatus.MANUAL_REVIEW_REQUIRED
            if association_state == "manual-review-required"
            else ValidationStatus.VALID
        )
        result = _record(
            payload,
            RETURNED_IMAGE_BINDING_CONTRACT_ID,
            payload["binding_id"],
            status=status,
        )
        if status is ValidationStatus.MANUAL_REVIEW_REQUIRED and result.record is not None:
            return ValidationResult(
                status=status,
                record=result.record,
                reason_codes=("visual-generation-association-review-required",),
                details=("returned image association requires bounded human review",),
            )
        return result
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid_result("visual-generation-provenance-invalid", sanitize_detail(str(exc)))


def project_routing_provenance(
    generation_handoff: ValidatedRecord,
    returned_image_binding: ValidatedRecord,
) -> dict[str, Any]:
    """Project bounded provenance evidence for the existing #957 routing boundary."""
    handoff = _validated_generation_handoff(generation_handoff)
    binding = _validated_returned_binding(returned_image_binding)
    data = binding.to_dict()
    if data["generation_handoff"]["handoff_id"] != handoff.record_id:
        raise ValueError("returned image binding does not reference the supplied generation handoff")
    if data["generation_handoff"]["fingerprint"] != handoff.fingerprint:
        raise ValueError("returned image binding generation-handoff fingerprint is stale or mismatched")
    handoff_data = handoff.to_dict()
    return {
        "generation_handoff_id": handoff.record_id,
        "source_plan_id": handoff_data["source_cohesive_visual_plan"]["plan_id"],
        "source_plan_fingerprint": handoff_data["source_cohesive_visual_plan"]["fingerprint"],
        "brief_id": handoff_data["source_gap"]["brief_id"],
        "missing_visual_role_id": handoff_data["source_gap"]["missing_visual_role_id"],
        "intent_id": handoff_data["image_intent"]["intent_id"],
        "intent_fingerprint": handoff_data["image_intent"]["fingerprint"],
        "intake_id": data["intake_id"],
        "association_state": data["association_state"],
        "prior_generation_handoff_id": data["prior_generation_handoff_id"],
        "authority": dict(_AUTHORITY),
    }


def _validated_cohesive_plan(value: object) -> ValidatedRecord:
    if type(value) is not ValidatedRecord:
        raise ContractValidationError(
            "visual-generation-plan-invalid", "cohesive visual plan must be validated evidence"
        )
    if value.contract_version != COHESIVE_VISUAL_PLAN_CONTRACT_ID:
        raise ContractValidationError(
            "visual-generation-plan-incompatible", "cohesive visual plan contract is incompatible"
        )
    payload = value.to_dict()
    if payload.get("contract_version") != COHESIVE_VISUAL_PLAN_CONTRACT_ID:
        raise ContractValidationError("identity-invalid", "cohesive visual plan payload version is invalid")
    if payload.get("cohesive_visual_plan_id") != value.record_id:
        raise ContractValidationError("identity-invalid", "cohesive visual plan ID does not match its record")
    if sha256_hex(payload) != value.fingerprint:
        raise ContractValidationError("identity-invalid", "cohesive visual plan fingerprint does not reconstruct")
    if type(payload.get("image_gap_briefs")) is not list:
        raise ContractValidationError("visual-generation-plan-invalid", "cohesive visual plan gaps are invalid")
    return value


def _find_exact_gap(plan: ValidatedRecord, brief_id: str, role_id: str) -> dict[str, Any]:
    brief = validate_stable_id(brief_id, "brief_id")
    role = validate_stable_id(role_id, "missing_visual_role_id")
    matches = [
        item
        for item in plan.to_dict()["image_gap_briefs"]
        if type(item) is dict and item.get("brief_id") == brief
    ]
    if len(matches) != 1:
        raise ContractValidationError(
            "visual-generation-gap-invalid", "brief_id does not identify one exact source gap"
        )
    match = matches[0]
    if match.get("missing_visual_role_id") != role:
        raise ContractValidationError(
            "identity-invalid", "missing visual role does not match the source gap"
        )
    return match


def _validated_image_intent(value: object) -> ValidatedRecord:
    if type(value) is not ValidatedRecord or value.contract_version != IMAGE_INTENT_CONTRACT_ID:
        raise ContractValidationError(
            "visual-generation-intent-invalid", "image intent must be validated ImageIntent evidence"
        )
    rebuilt = validate_image_intent(value.to_dict())
    if rebuilt.status is not ValidationStatus.VALID or rebuilt.record is None:
        raise ContractValidationError("visual-generation-intent-invalid", "image intent payload is invalid")
    if (
        rebuilt.record.record_id != value.record_id
        or rebuilt.record.record_revision != value.record_revision
        or rebuilt.record.fingerprint != value.fingerprint
    ):
        raise ContractValidationError("identity-invalid", "image intent identity or fingerprint is stale")
    return value


def _validated_imported_context(value: object) -> ValidatedRecord:
    if type(value) is not ValidatedRecord or value.contract_version != IMPORTED_ASSET_CONTEXT_CONTRACT_ID:
        raise ContractValidationError(
            "visual-generation-import-context-invalid",
            "imported asset context must be validated ImportedAssetContext evidence",
        )
    rebuilt = validate_imported_asset_context(value.to_dict())
    if rebuilt.status is not ValidationStatus.VALID or rebuilt.record is None:
        raise ContractValidationError(
            "visual-generation-import-context-invalid", "imported asset context payload is invalid"
        )
    if rebuilt.record.record_id != value.record_id or rebuilt.record.fingerprint != value.fingerprint:
        raise ContractValidationError("identity-invalid", "imported asset context identity is stale")
    return value


def _validated_generation_handoff(value: object) -> ValidatedRecord:
    return _validated_own_record(value, GENERATION_HANDOFF_CONTRACT_ID, "handoff_id")


def _validated_returned_binding(value: object) -> ValidatedRecord:
    return _validated_own_record(value, RETURNED_IMAGE_BINDING_CONTRACT_ID, "binding_id")


def _validated_own_record(value: object, contract_id: str, id_field: str) -> ValidatedRecord:
    if type(value) is not ValidatedRecord or value.contract_version != contract_id:
        raise ContractValidationError("visual-generation-provenance-invalid", "validated provenance evidence is required")
    payload = value.to_dict()
    if payload.get("contract_version") != contract_id or payload.get(id_field) != value.record_id:
        raise ContractValidationError("identity-invalid", "provenance record identity is invalid")
    if sha256_hex(payload) != value.fingerprint:
        raise ContractValidationError("identity-invalid", "provenance record fingerprint does not reconstruct")
    if payload.get("authority") != _AUTHORITY:
        raise ContractValidationError("authority-invalid", "provenance authority must remain false")
    return value


def _record(
    payload: dict[str, Any],
    contract_id: str,
    record_id: str,
    *,
    status: ValidationStatus = ValidationStatus.VALID,
) -> ValidationResult:
    normalized = validate_and_normalize_json(payload, max_bytes=MAX_RESULT_BYTES)
    if type(normalized) is not dict or canonical_size(normalized) > MAX_RESULT_BYTES:
        raise ContractValidationError("handoff-oversized", "visual generation provenance exceeds result-size bound")
    record = ValidatedRecord(
        contract_version=contract_id,
        record_id=record_id,
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(normalized),
        payload=freeze_json(normalized),
    )
    return ValidationResult(status=status, record=record)
