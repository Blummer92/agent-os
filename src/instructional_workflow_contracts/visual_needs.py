"""Pure deterministic visual-needs planning from MaterialRequirement evidence."""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_RESULT_BYTES as SHARED_MAX_RESULT_BYTES,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    canonical_strings,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_stable_id,
    validate_text,
)
from .material_requirement import (
    MAX_DOMAIN_ITEMS,
    MAX_VISUAL_ROLES,
    SUPPORTED_ARTIFACT_TYPES,
    V1_CONTRACT_ID,
    V2_CONTRACT_ID,
    validate_material_requirement,
)

CONTRACT_ID = "curriculum-visual-needs-plan-v1"
MAX_RESULT_BYTES = 16 * 1024
OUTCOMES = frozenset(
    {"no-visual-needed", "visuals-required", "manual-review-required"}
)
SUPPORTED_MATERIAL_TYPES = frozenset(
    set(SUPPORTED_ARTIFACT_TYPES) - {"unsupported-manual-review"}
)

_MANUAL_V1 = "manual-review-material-requirement-v1"
_MANUAL_UNSPECIFIED = "manual-review-visual-direction-unspecified"
_MANUAL_UNSUPPORTED_MATERIAL = "manual-review-unsupported-material-type"


def plan_visual_needs(requirement: object) -> ValidationResult:
    """Return one bounded advisory visual-needs plan from validated evidence."""
    try:
        source = _validated_requirement(requirement)
        source_payload = source.to_dict()
        artifact = _mapping(source_payload.get("artifact"), "artifact")
        material_type = validate_text(
            artifact.get("artifact_type"),
            "artifact_type",
            max_length=64,
        )

        requirements = _mapping(source_payload.get("requirements"), "requirements")
        accessibility = canonical_strings(
            requirements.get("accessibility_requirements"),
            name="accessibility requirements",
            maximum=MAX_DOMAIN_ITEMS,
            validator=lambda item: validate_text(item, "accessibility requirement"),
            allow_empty=True,
        )

        outcome = "manual-review-required"
        source_decision: str | None = None
        maximum_visual_count = 0
        normalized_roles: list[dict[str, Any]] = []
        reason_codes: tuple[str, ...] = ()
        visual_direction: dict[str, Any] | None = None

        if source.contract_version == V2_CONTRACT_ID:
            visual_direction = _mapping(
                source_payload.get("visual_direction"),
                "visual_direction",
            )
            source_decision = validate_text(
                visual_direction.get("decision"),
                "visual decision",
                max_length=64,
            )

        if material_type not in SUPPORTED_MATERIAL_TYPES:
            reason_codes = (_MANUAL_UNSUPPORTED_MATERIAL,)
        elif source.contract_version == V1_CONTRACT_ID:
            reason_codes = (_MANUAL_V1,)
        elif source.contract_version == V2_CONTRACT_ID:
            assert visual_direction is not None
            maximum_visual_count = _visual_count(
                visual_direction.get("maximum_visual_count")
            )
            normalized_roles = _roles(
                visual_direction.get("roles"),
                source_fingerprint=source.fingerprint,
            )

            if source_decision == "unspecified":
                reason_codes = (_MANUAL_UNSPECIFIED,)
            elif source_decision == "no-visuals":
                outcome = "no-visual-needed"
            elif source_decision == "visuals-required":
                outcome = "visuals-required"
            else:
                raise ContractValidationError(
                    "material-visual-needs-incompatible-upstream",
                    "validated visual decision is unsupported",
                )
        else:
            raise ContractValidationError(
                "material-visual-needs-incompatible-upstream",
                "MaterialRequirement contract version is incompatible",
            )

        if outcome not in OUTCOMES:
            raise ContractValidationError(
                "material-visual-needs-invalid",
                "planner produced an unsupported outcome",
            )

        required_roles = [
            role for role in normalized_roles if role["requirement_state"] == "required"
        ]
        optional_roles = [
            role for role in normalized_roles if role["requirement_state"] == "optional"
        ]
        if outcome == "no-visual-needed" and (required_roles or optional_roles):
            raise ContractValidationError(
                "material-visual-needs-incompatible-upstream",
                "no-visual decision contains visual roles",
            )
        if outcome == "visuals-required" and not required_roles:
            raise ContractValidationError(
                "material-visual-needs-incompatible-upstream",
                "visuals-required decision has no required role",
            )
        if len(required_roles) + len(optional_roles) > maximum_visual_count:
            raise ContractValidationError(
                "material-visual-needs-incompatible-upstream",
                "visual roles exceed the governed visual-count ceiling",
            )

        payload = {
            "contract_version": CONTRACT_ID,
            "plan_id": _plan_id(
                source=source,
                material_type=material_type,
                outcome=outcome,
                source_decision=source_decision,
                maximum_visual_count=maximum_visual_count,
                roles=normalized_roles,
                accessibility=accessibility,
                reason_codes=reason_codes,
            ),
            "source_requirement": {
                "requirement_id": source.record_id,
                "record_revision": source.record_revision,
                "contract_version": source.contract_version,
                "fingerprint": source.fingerprint,
            },
            "material_type": material_type,
            "outcome": outcome,
            "source_visual_decision": source_decision,
            "required_roles": required_roles,
            "optional_roles": optional_roles,
            "accessibility_requirements": list(accessibility),
            "cognitive_load_ceiling": maximum_visual_count,
            "maximum_visual_count": maximum_visual_count,
            "manual_review_required": outcome == "manual-review-required",
            "reason_codes": list(reason_codes),
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
                "side_effects_performed": False,
            },
        }
        normalized_payload = validate_and_normalize_json(
            payload,
            max_bytes=MAX_RESULT_BYTES,
        )
        if type(normalized_payload) is not dict:
            raise ContractValidationError(
                "material-visual-needs-invalid",
                "planner output must be a built-in mapping",
            )
        result_size = canonical_size(normalized_payload)
        if result_size > MAX_RESULT_BYTES or result_size > SHARED_MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized",
                "visual-needs plan exceeds the shared result-size bound",
            )

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=normalized_payload["plan_id"],
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized_payload),
            payload=freeze_json(normalized_payload),
        )
        if outcome == "manual-review-required":
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=reason_codes,
                details=("governed evidence requires bounded human review",),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("material-visual-needs-invalid", sanitize_detail(str(exc)))


def _validated_requirement(value: object) -> ValidatedRecord:
    supplied: ValidatedRecord | None = None
    if type(value) is ValidationResult:
        if value.status is not ValidationStatus.VALID or value.record is None:
            raise ContractValidationError(
                "material-visual-needs-invalid-upstream",
                "MaterialRequirement validation result must be valid",
            )
        supplied = value.record
        validation = validate_material_requirement(supplied.to_dict())
    elif type(value) is ValidatedRecord:
        supplied = value
        validation = validate_material_requirement(supplied.to_dict())
    else:
        validation = validate_material_requirement(value)

    if validation.status is not ValidationStatus.VALID or validation.record is None:
        raise ContractValidationError(
            "material-visual-needs-invalid-upstream",
            "MaterialRequirement must be structurally valid",
        )
    record = validation.record
    if record.contract_version not in {V1_CONTRACT_ID, V2_CONTRACT_ID}:
        raise ContractValidationError(
            "material-visual-needs-incompatible-upstream",
            "MaterialRequirement contract version is incompatible",
        )
    if supplied is not None and (
        supplied.contract_version != record.contract_version
        or supplied.record_id != record.record_id
        or supplied.record_revision != record.record_revision
        or supplied.fingerprint != record.fingerprint
    ):
        raise ContractValidationError(
            "material-visual-needs-incompatible-upstream",
            "validated MaterialRequirement evidence does not reconstruct exactly",
        )
    return record


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError(
            "handoff-wrong-type",
            f"{name} must be a built-in mapping",
        )
    return value


def _visual_count(value: object) -> int:
    if type(value) is not int or value < 0 or value > MAX_VISUAL_ROLES:
        raise ContractValidationError(
            "material-visual-needs-incompatible-upstream",
            "maximum_visual_count is outside the governed bound",
        )
    return value


def _roles(value: object, *, source_fingerprint: str) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise ContractValidationError(
            "handoff-wrong-type",
            "visual roles must be a built-in list",
        )
    if len(value) > MAX_VISUAL_ROLES:
        raise ContractValidationError(
            "handoff-oversized",
            "visual roles exceed the eight-role bound",
        )
    roles: list[dict[str, Any]] = []
    for raw in value:
        role = _mapping(raw, "visual role")
        requirement_state = validate_text(
            role.get("requirement_state"),
            "visual requirement state",
            max_length=64,
        )
        if requirement_state not in {"required", "optional"}:
            raise ContractValidationError(
                "material-visual-needs-incompatible-upstream",
                "visual requirement state is unsupported",
            )
        normalized = {
            "role_type": validate_text(
                role.get("role_type"),
                "visual role type",
                max_length=64,
            ),
            "requirement_state": requirement_state,
            "instructional_purpose": validate_text(
                role.get("instructional_purpose"),
                "visual instructional purpose",
            ),
            "intended_placement": validate_text(
                role.get("intended_placement"),
                "visual intended placement",
                max_length=64,
            ),
            "orientation": validate_text(
                role.get("orientation"),
                "visual orientation",
                max_length=64,
            ),
            "accessibility_reference": "requirements.accessibility_requirements",
        }
        normalized["role_id"] = _role_id(
            source_fingerprint=source_fingerprint,
            role=normalized,
        )
        validate_stable_id(normalized["role_id"], "visual role_id")
        roles.append(normalized)
    return roles


def _role_id(*, source_fingerprint: str, role: dict[str, Any]) -> str:
    identity = {
        "planner_contract": CONTRACT_ID,
        "source_requirement_fingerprint": source_fingerprint,
        "role_type": role["role_type"],
        "requirement_state": role["requirement_state"],
        "instructional_purpose": role["instructional_purpose"],
        "intended_placement": role["intended_placement"],
        "orientation": role["orientation"],
    }
    return "visual-role-" + sha256_hex(identity)[:24]


def _plan_id(
    *,
    source: ValidatedRecord,
    material_type: str,
    outcome: str,
    source_decision: str | None,
    maximum_visual_count: int,
    roles: list[dict[str, Any]],
    accessibility: tuple[str, ...],
    reason_codes: tuple[str, ...],
) -> str:
    identity = {
        "planner_contract": CONTRACT_ID,
        "source_requirement_id": source.record_id,
        "source_requirement_revision": source.record_revision,
        "source_requirement_contract_version": source.contract_version,
        "source_requirement_fingerprint": source.fingerprint,
        "material_type": material_type,
        "outcome": outcome,
        "source_visual_decision": source_decision,
        "maximum_visual_count": maximum_visual_count,
        "roles": roles,
        "accessibility_requirements": list(accessibility),
        "reason_codes": list(reason_codes),
    }
    plan_id = "visual-needs-plan-" + sha256_hex(identity)[:24]
    return validate_stable_id(plan_id, "visual-needs plan_id")


def _invalid(reason: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason,),
        details=(sanitize_detail(detail),),
    )
