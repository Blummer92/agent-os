"""Pure validator for the curriculum workflow handoff contract."""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_BLOCKERS,
    MAX_DEPENDENCY_KEYS,
    MAX_REFERENCES,
    MAX_REASONS,
    MAX_RESULT_BYTES,
    AuthorityEvidence,
    ContractReference,
    ContractValidationError,
    FrozenObject,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_json_bytes,
    canonical_reason_codes,
    canonical_size,
    canonical_strings,
    freeze_json,
    resolve_status,
    sanitize_detail,
    sha256_hex,
    validate_algorithm,
    validate_and_normalize_json,
    validate_dependency_key,
    validate_revision,
    validate_sha256,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

CONTRACT_ID = "curriculum-workflow-handoff-v1"

TOP_LEVEL_FIELDS = frozenset(
    {
        "identity",
        "source_evidence",
        "learning_alignment",
        "readiness",
        "authority",
        "reuse",
        "routing",
        "dependencies",
        "stage_payload",
        "audit",
    }
)

CANONICAL_OWNERS = frozenset(
    {
        "agent-orchestrator",
        "unit-alignment-agent",
        "teacher-modeling-coach",
        "instructional-materials-coach",
        "qa-test-agent",
    }
)

DEPRECATED_FIELD_ALIASES = frozenset(
    {"schema_version", "status", "ready", "approved", "authorized"}
)

ORDER_INSENSITIVE_FIELDS = frozenset(
    {
        "blockers",
        "reason_codes",
        "manual_review_reasons",
        "required_handoff_artifacts",
        "permitted_destination_classes",
        "unsupported_capability_findings",
        "dependency_keys",
        "changed_dependency_keys",
        "impacted_output_refs",
        "unmapped_dependency_keys",
        "candidate_references",
        "selected_references",
        "rejected_candidates",
        "references",
    }
)

_ALLOWED_DEPENDENCY_NAMESPACES = frozenset(
    {
        "agent-orchestrator",
        "unit-alignment",
        "teacher-modeling",
        "instructional-materials",
        "qa",
        "source",
        "identity",
        "ownership",
        "readiness",
        "authority",
        "handoff",
        "dependency",
        "routing",
        "manual-review",
        "material",
        "artifact",
        "asset",
        "template",
        "destination",
        "quality",
        "reuse",
        "impact",
        "lp",
        "scheduler",
    }
)

_STAGE_FIELDS = {
    "agent-orchestrator": frozenset(
        {"request_summary", "constraints", "references", "blockers", "ready_for_alignment"}
    ),
    "unit-alignment-agent": frozenset(
        {
            "standards_map",
            "learning_objective",
            "success_criteria",
            "essential_questions",
            "evidence_target",
            "prerequisites",
            "accessibility_constraints",
            "alignment_evidence",
            "pacing_evidence",
            "blockers",
            "ready_for_modeling",
        }
    ),
    "teacher-modeling-coach": frozenset(
        {
            "immediate_student_task",
            "key_modeling_moments",
            "teacher_says_does",
            "student_does_notices",
            "observable_check_evidence",
            "likely_confusion",
            "support_move",
            "materials_extract",
            "blockers",
            "ready_for_materials",
        }
    ),
    "instructional-materials-coach": frozenset(
        {
            "material_requirement_refs",
            "artifact_manifest_refs",
            "reuse_impact_refs",
            "template_asset_destination_refs",
            "material_quality_evidence",
            "blockers",
            "next_owner",
        }
    ),
    "qa-test-agent": frozenset(
        {
            "validation_target",
            "contract_versions",
            "schema_conformance",
            "failed_quality_rows",
            "evidence_references",
            "tested_input_fingerprint",
            "remaining_risks",
            "recommendation",
        }
    ),
}


def validate_curriculum_handoff(value: object) -> ValidationResult:
    """Validate, normalize, and reconstruct one bounded handoff envelope."""

    try:
        normalized = validate_and_normalize_json(value)
        if type(normalized) is not dict:
            raise ContractValidationError("handoff-wrong-type", "handoff must be a built-in mapping")
        _reject_deprecated_aliases(normalized)
        _require_exact_fields(normalized, TOP_LEVEL_FIELDS, "handoff")

        identity = _group(normalized, "identity")
        source = _group(normalized, "source_evidence")
        alignment = _group(normalized, "learning_alignment")
        readiness = _group(normalized, "readiness")
        authority = _group(normalized, "authority")
        reuse = _group(normalized, "reuse")
        routing = _group(normalized, "routing")
        dependencies = _group(normalized, "dependencies")
        stage = _group(normalized, "stage_payload")
        audit = _group(normalized, "audit")

        _validate_identity(identity)
        _validate_source(source)
        _validate_alignment(alignment)
        _validate_readiness(readiness)
        _validate_authority(authority)
        _validate_reuse(reuse)
        _validate_routing(routing)
        _validate_dependencies(dependencies)
        _validate_stage(stage)
        _validate_audit(audit)
        _validate_ownership(source, alignment, routing, stage)

        normalized = _normalize_semantic_sets(normalized)
        _verify_dependency_fingerprint(normalized["dependencies"])
        if canonical_size(normalized) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized", "normalized handoff exceeds the result-size bound"
            )

        record = ValidatedRecord(
            contract_version=identity["contract_version"],
            record_id=identity["handoff_id"],
            record_revision=identity["record_revision"],
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(normalized),
            payload=freeze_json(normalized),
        )

        reason_codes = tuple(routing["reason_codes"])
        blockers = tuple(routing["blockers"])
        manual_review = bool(routing["manual_review_reasons"]) or dependencies[
            "human_review_required"
        ]
        stale = source["evidence_status"] == "stale"
        status = resolve_status(
            reason_codes,
            blockers,
            stale=stale,
            manual_review=manual_review,
        )
        return ValidationResult(
            status=status,
            record=record,
            reason_codes=reason_codes,
            blockers=blockers,
            details=(),
        )
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("handoff-invalid", sanitize_detail(str(exc)))


def _invalid(reason_code: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason_code,),
        details=(sanitize_detail(detail),),
    )


def _group(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload[name]
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    return value


def _require_exact_fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise ContractValidationError("handoff-invalid", f"{name} is missing required fields")
    if unknown:
        raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")


def _reject_deprecated_aliases(value: Any) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if key in DEPRECATED_FIELD_ALIASES:
                raise ContractValidationError(
                    "handoff-unknown-field", "handoff uses a retired generic field alias"
                )
            _reject_deprecated_aliases(item)
    elif type(value) is list:
        for item in value:
            _reject_deprecated_aliases(item)


def _validate_identity(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset(
            {
                "contract_version",
                "handoff_id",
                "record_revision",
                "request_id",
                "course_ref",
                "unit_ref",
                "lesson_ref",
            }
        ),
        "identity",
    )
    if validate_version(value["contract_version"]) != CONTRACT_ID:
        raise ContractValidationError(
            "handoff-version-unsupported", "contract_version is unsupported"
        )
    for key in ("handoff_id", "request_id", "course_ref", "unit_ref", "lesson_ref"):
        validate_stable_id(value[key], key)
    validate_revision(value["record_revision"])


def _validate_source(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset(
            {
                "source_record_identity",
                "canonical_source",
                "working_source",
                "exact_location",
                "source_confidence",
                "evidence_status",
                "freshness_checked_at",
                "fingerprint_algorithm",
                "source_fingerprint",
                "produced_by",
                "created_at",
            }
        ),
        "source_evidence",
    )
    validate_stable_id(value["source_record_identity"], "source_record_identity")
    validate_stable_id(value["canonical_source"], "canonical_source")
    validate_stable_id(value["working_source"], "working_source")
    validate_text(value["exact_location"], "exact_location")
    if value["source_confidence"] not in {"low", "medium", "high"}:
        raise ContractValidationError("source-invalid", "source_confidence is unsupported")
    if value["evidence_status"] not in {
        "confirmed",
        "provisional",
        "conflicting",
        "unavailable",
        "stale",
    }:
        raise ContractValidationError("source-invalid", "evidence_status is unsupported")
    validate_timestamp(value["freshness_checked_at"], "freshness_checked_at")
    if validate_algorithm(value["fingerprint_algorithm"]) != FINGERPRINT_ALGORITHM:
        raise ContractValidationError("handoff-invalid", "fingerprint algorithm is unsupported")
    validate_sha256(value["source_fingerprint"], "source_fingerprint")
    _validate_owner(value["produced_by"], "produced_by")
    validate_timestamp(value["created_at"], "created_at")


def _validate_alignment(value: dict[str, Any]) -> None:
    _require_exact_fields(value, frozenset({"owner", "references"}), "learning_alignment")
    if value["owner"] != "unit-alignment-agent":
        raise ContractValidationError(
            "ownership-owner-conflict", "learning_alignment has a conflicting owner"
        )
    _validate_references(value["references"], "learning_alignment references")


def _validate_readiness(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset(
            {
                "unit_readiness",
                "modeling_readiness",
                "materials_readiness",
                "qa_status",
                "teacher_approval",
                "classroom_ready_status",
            }
        ),
        "readiness",
    )
    for key, item in value.items():
        validate_text(item, key, max_length=64)


def _validate_authority(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset(
            {
                "execution_authorized",
                "external_write_authorized",
                "production_authorized",
                "publication_authorized",
            }
        ),
        "authority",
    )
    for key, item in value.items():
        if type(item) is not bool or item is not False:
            raise ContractValidationError(
                "authority-invalid", f"{key} must be the built-in false value"
            )


def _validate_reuse(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset({"candidate_references", "selected_references", "rejected_candidates"}),
        "reuse",
    )
    for key in ("candidate_references", "selected_references", "rejected_candidates"):
        _validate_references(value[key], key)


def _validate_routing(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset(
            {
                "task_owner",
                "mode",
                "next_owner",
                "stop_or_continue",
                "blockers",
                "reason_codes",
                "manual_review_reasons",
                "required_handoff_artifacts",
                "compute_budget_class",
                "permitted_destination_classes",
                "unsupported_capability_findings",
            }
        ),
        "routing",
    )
    _validate_owner(value["task_owner"], "task_owner")
    _validate_owner(value["next_owner"], "next_owner")
    if value["mode"] not in {"Draft", "Gate", "Production"}:
        raise ContractValidationError("routing-invalid", "routing mode is unsupported")
    if value["stop_or_continue"] not in {"stop", "continue"}:
        raise ContractValidationError("routing-invalid", "stop_or_continue is unsupported")
    canonical_reason_codes(value["blockers"], MAX_BLOCKERS)
    canonical_reason_codes(value["reason_codes"], MAX_REASONS)
    manual = canonical_reason_codes(value["manual_review_reasons"], MAX_REASONS)
    if any(not item.startswith("manual-review-") for item in manual):
        raise ContractValidationError(
            "routing-invalid", "manual-review reasons must use the manual-review namespace"
        )
    canonical_strings(
        value["required_handoff_artifacts"],
        name="required_handoff_artifacts",
        maximum=MAX_REFERENCES,
        validator=lambda item: validate_stable_id(item, "required handoff artifact"),
    )
    validate_text(value["compute_budget_class"], "compute_budget_class", max_length=64)
    canonical_strings(
        value["permitted_destination_classes"],
        name="permitted_destination_classes",
        maximum=MAX_REFERENCES,
        validator=lambda item: validate_stable_id(item, "destination class"),
    )
    canonical_strings(
        value["unsupported_capability_findings"],
        name="unsupported_capability_findings",
        maximum=MAX_REASONS,
        validator=lambda item: validate_text(item, "unsupported capability finding"),
    )


def _validate_dependencies(value: dict[str, Any]) -> None:
    _require_exact_fields(
        value,
        frozenset(
            {
                "dependency_keys",
                "dependency_values",
                "dependency_fingerprint",
                "upstream_contract_ref",
                "upstream_record_revision",
                "upstream_change_detected",
                "changed_dependency_keys",
                "impacted_output_refs",
                "unmapped_dependency_keys",
                "revalidation_scope",
                "confidence",
                "human_review_required",
            }
        ),
        "dependencies",
    )
    keys = canonical_strings(
        value["dependency_keys"],
        name="dependency_keys",
        maximum=MAX_DEPENDENCY_KEYS,
        validator=_validate_owned_dependency_key,
    )
    if type(value["dependency_values"]) is not dict:
        raise ContractValidationError(
            "dependency-wrong-type", "dependency_values must be a built-in mapping"
        )
    if set(value["dependency_values"]) != set(keys):
        raise ContractValidationError(
            "dependency-invalid", "dependency_values must match dependency_keys exactly"
        )
    validate_sha256(value["dependency_fingerprint"], "dependency_fingerprint")
    validate_stable_id(value["upstream_contract_ref"], "upstream_contract_ref")
    validate_revision(value["upstream_record_revision"])
    if type(value["upstream_change_detected"]) is not bool:
        raise ContractValidationError(
            "dependency-wrong-type", "upstream_change_detected must be a built-in boolean"
        )
    for name in ("changed_dependency_keys", "unmapped_dependency_keys"):
        canonical_strings(
            value[name],
            name=name,
            maximum=MAX_DEPENDENCY_KEYS,
            validator=_validate_owned_dependency_key,
        )
    canonical_strings(
        value["impacted_output_refs"],
        name="impacted_output_refs",
        maximum=MAX_REFERENCES,
        validator=lambda item: validate_stable_id(item, "impacted output reference"),
    )
    validate_text(value["revalidation_scope"], "revalidation_scope")
    if value["confidence"] not in {"low", "medium", "high"}:
        raise ContractValidationError("dependency-invalid", "dependency confidence is unsupported")
    if type(value["human_review_required"]) is not bool:
        raise ContractValidationError(
            "dependency-wrong-type", "human_review_required must be a built-in boolean"
        )


def _validate_stage(value: dict[str, Any]) -> None:
    _require_exact_fields(value, frozenset({"owner", "payload"}), "stage_payload")
    owner = _validate_owner(value["owner"], "stage payload owner")
    payload = value["payload"]
    if type(payload) is not dict:
        raise ContractValidationError("handoff-wrong-type", "stage payload must be a built-in mapping")
    unknown = set(payload) - _STAGE_FIELDS[owner]
    if unknown:
        raise ContractValidationError(
            "ownership-owner-conflict", "stage payload contains fields owned by another stage"
        )


def _validate_audit(value: dict[str, Any]) -> None:
    _require_exact_fields(value, frozenset({"entries"}), "audit")
    entries = value["entries"]
    if type(entries) is not list:
        raise ContractValidationError("handoff-wrong-type", "audit entries must be a built-in list")
    if len(entries) > MAX_REFERENCES:
        raise ContractValidationError("handoff-oversized", "audit entries exceed the collection bound")
    for entry in entries:
        if type(entry) is not dict:
            raise ContractValidationError("handoff-wrong-type", "audit entry must be a built-in mapping")
        _require_exact_fields(
            entry,
            frozenset({"owner", "action", "created_at", "record_revision"}),
            "audit entry",
        )
        _validate_owner(entry["owner"], "audit owner")
        validate_stable_id(entry["action"], "audit action")
        validate_timestamp(entry["created_at"], "audit created_at")
        validate_revision(entry["record_revision"])


def _validate_ownership(
    source: dict[str, Any],
    alignment: dict[str, Any],
    routing: dict[str, Any],
    stage: dict[str, Any],
) -> None:
    owner = stage["owner"]
    if source["produced_by"] != owner or routing["task_owner"] != owner:
        raise ContractValidationError(
            "ownership-owner-conflict", "producer, task owner, and stage payload owner must match"
        )
    if alignment["owner"] != "unit-alignment-agent":
        raise ContractValidationError(
            "ownership-owner-conflict", "learning-alignment ownership is invalid"
        )


def _validate_owner(value: object, name: str) -> str:
    owner = validate_stable_id(value, name)
    if owner not in CANONICAL_OWNERS:
        raise ContractValidationError("ownership-owner-conflict", f"{name} is not canonical")
    return owner


def _validate_owned_dependency_key(value: object) -> str:
    key = validate_dependency_key(value)
    namespace = key.split(".", 1)[0]
    if namespace not in _ALLOWED_DEPENDENCY_NAMESPACES:
        raise ContractValidationError("dependency-invalid", "dependency key has no canonical owner")
    return key


def _validate_references(value: object, name: str) -> tuple[ContractReference, ...]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > MAX_REFERENCES:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds the reference bound")
    references: list[ContractReference] = []
    identities: set[tuple[str, str]] = set()
    for item in value:
        if type(item) is not dict:
            raise ContractValidationError("handoff-wrong-type", f"{name} entries must be mappings")
        _require_exact_fields(
            item,
            frozenset({"system", "stable_id", "exact_location", "verification_evidence"}),
            "reference",
        )
        reference = ContractReference(
            system=item["system"],
            stable_id=item["stable_id"],
            exact_location=item["exact_location"],
            verification_evidence=item["verification_evidence"],
        )
        identity = (reference.system, reference.stable_id)
        if identity in identities:
            raise ContractValidationError("identity-duplicate", f"{name} contains duplicate references")
        identities.add(identity)
        references.append(reference)
    return tuple(sorted(references, key=lambda item: (item.system, item.stable_id, item.exact_location)))


def _normalize_semantic_sets(value: dict[str, Any]) -> dict[str, Any]:
    def visit(item: Any, field_name: str | None = None) -> Any:
        if type(item) is dict:
            return {key: visit(item[key], key) for key in sorted(item)}
        if type(item) is list:
            normalized_items = [visit(element) for element in item]
            if field_name in ORDER_INSENSITIVE_FIELDS:
                encoded = [(canonical_json_bytes(element), element) for element in normalized_items]
                if len({key for key, _ in encoded}) != len(encoded):
                    raise ContractValidationError(
                        "handoff-duplicate", f"{field_name} contains duplicate values"
                    )
                return [element for _, element in sorted(encoded, key=lambda pair: pair[0])]
            return normalized_items
        return item

    normalized = visit(value)
    if type(normalized) is not dict:
        raise TypeError("normalized handoff must remain a mapping")
    return normalized


def _verify_dependency_fingerprint(value: dict[str, Any]) -> None:
    expected = sha256_hex(
        {
            "dependency_keys": value["dependency_keys"],
            "dependency_values": value["dependency_values"],
        }
    )
    if value["dependency_fingerprint"] != expected:
        raise ContractValidationError(
            "dependency-invalid", "dependency_fingerprint does not match consumed dependencies"
        )


__all__ = [
    "CANONICAL_OWNERS",
    "CONTRACT_ID",
    "DEPRECATED_FIELD_ALIASES",
    "ORDER_INSENSITIVE_FIELDS",
    "TOP_LEVEL_FIELDS",
    "validate_curriculum_handoff",
    "AuthorityEvidence",
    "ValidationResult",
    "ValidationStatus",
]
