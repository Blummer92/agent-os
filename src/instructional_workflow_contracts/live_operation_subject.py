"""Pure typed live-operation subject for governed instructional production."""
from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    AuthorityEvidence,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_bounded_list,
    validate_exact_fields,
    validate_revision,
    validate_sha256,
    validate_stable_id,
    validate_text,
    validate_version,
)
from .material_requirement import V2_CONTRACT_ID, validate_material_requirement

CONTRACT_ID = "instructional-materials-live-operation-subject-v1"
SUBJECT_ID_PREFIX = "instructional-live-operation-subject:"
MAX_EVIDENCE_IDS = 32
MAX_INPUT_BYTES = 64 * 1024

_TOP_LEVEL_FIELDS = frozenset(
    {
        "contract_version",
        "source",
        "material_requirement",
        "workspace",
        "operation",
        "gate_evidence_ids",
        "visual_reuse_evidence_ids",
        "authority",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {
        "approval_authorized",
        "execution_authorized",
        "external_write_authorized",
        "production_authorized",
        "publication_authorized",
        "side_effects_performed",
    }
)


def validate_live_operation_subject(value: object) -> ValidationResult:
    """Validate one exact approval-semantic live-operation subject without I/O."""
    try:
        data = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        if type(data) is not dict:
            raise ContractValidationError("handoff-wrong-type", "live-operation subject must be a mapping")
        validate_exact_fields(data, _TOP_LEVEL_FIELDS, "live-operation subject")
        if validate_version(data["contract_version"]) != CONTRACT_ID:
            raise ContractValidationError("handoff-version-unsupported", "unsupported live-operation subject version")

        source = _mapping(data["source"], "source")
        validate_exact_fields(source, frozenset({"stable_id", "revision", "content_fingerprint"}), "source")
        validate_stable_id(source["stable_id"], "source stable_id")
        validate_revision(source["revision"])
        validate_sha256(source["content_fingerprint"], "source content_fingerprint")

        requirement_binding = _mapping(data["material_requirement"], "material_requirement")
        validate_exact_fields(
            requirement_binding,
            frozenset({"contract_version", "requirement_id", "record_revision", "record_fingerprint", "record"}),
            "material_requirement",
        )
        requirement_result = validate_material_requirement(requirement_binding["record"])
        if requirement_result.status is not ValidationStatus.VALID or requirement_result.record is None:
            raise ContractValidationError("material-invalid", "MaterialRequirement is not valid")
        requirement = requirement_result.record
        expected = (
            validate_version(requirement_binding["contract_version"]),
            validate_stable_id(requirement_binding["requirement_id"], "requirement_id"),
            validate_revision(requirement_binding["record_revision"]),
            validate_sha256(requirement_binding["record_fingerprint"], "record_fingerprint"),
        )
        observed = (
            requirement.contract_version,
            requirement.record_id,
            requirement.record_revision,
            requirement.fingerprint,
        )
        if expected != observed:
            raise ContractValidationError("material-incompatible-fingerprint", "MaterialRequirement binding does not match validated record")

        workspace = _mapping(data["workspace"], "workspace")
        validate_exact_fields(
            workspace,
            frozenset({"slides_template_id", "docs_template_id", "target_folder_id"}),
            "workspace",
        )
        for key in sorted(workspace):
            validate_stable_id(workspace[key], key)

        operation = _mapping(data["operation"], "operation")
        validate_exact_fields(
            operation,
            frozenset({"idempotency_key", "slides_name", "docs_name", "operation_shape_fingerprint"}),
            "operation",
        )
        validate_stable_id(operation["idempotency_key"], "idempotency_key")
        validate_text(operation["slides_name"], "slides_name")
        validate_text(operation["docs_name"], "docs_name")
        validate_sha256(operation["operation_shape_fingerprint"], "operation_shape_fingerprint")

        data["gate_evidence_ids"] = list(_evidence_ids(data["gate_evidence_ids"], "gate_evidence_ids", required=True))
        data["visual_reuse_evidence_ids"] = list(
            _evidence_ids(data["visual_reuse_evidence_ids"], "visual_reuse_evidence_ids", required=False)
        )
        requirement_payload = requirement.to_dict()
        visual_direction = requirement_payload.get("visual_direction")
        if (
            requirement.contract_version == V2_CONTRACT_ID
            and type(visual_direction) is dict
            and visual_direction.get("decision") == "visuals-required"
            and not data["visual_reuse_evidence_ids"]
        ):
            raise ContractValidationError("material-missing-required-field", "visual/reuse evidence is required by MaterialRequirement")

        authority = _mapping(data["authority"], "authority")
        validate_exact_fields(authority, _AUTHORITY_FIELDS, "authority")
        if any(value is not False for value in authority.values()):
            raise ContractValidationError("authority-invalid", "live-operation subject cannot grant authority")

        semantic_payload = dict(data)
        subject_id = SUBJECT_ID_PREFIX + sha256_hex(semantic_payload)
        record_payload = dict(data)
        record_payload["subject_id"] = subject_id
        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id=subject_id,
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(record_payload),
            payload=freeze_json(record_payload),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(exc.reason_code,),
            details=(exc.detail,),
        )
    except (TypeError, ValueError) as exc:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=("handoff-invalid",),
            details=(sanitize_detail(str(exc)),),
        )


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a mapping")
    return value


def _evidence_ids(value: object, name: str, *, required: bool) -> tuple[str, ...]:
    items = validate_bounded_list(value, name, MAX_EVIDENCE_IDS)
    validated = tuple(validate_stable_id(item, name) for item in items)
    if required and not validated:
        raise ContractValidationError("handoff-invalid", f"{name} must not be empty")
    if len(set(validated)) != len(validated):
        raise ContractValidationError("identity-duplicate", f"{name} contains duplicates")
    return tuple(sorted(validated))


__all__ = [
    "CONTRACT_ID",
    "SUBJECT_ID_PREFIX",
    "validate_live_operation_subject",
    "AuthorityEvidence",
]
