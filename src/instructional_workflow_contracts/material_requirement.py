"""Pure MaterialRequirement validation built on the CW5A core."""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_reason_codes,
    canonical_size,
    canonical_strings,
    freeze_json,
    invalid_result,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_sha256,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

V1_CONTRACT_ID = "curriculum-material-requirement-v1"
V2_CONTRACT_ID = "curriculum-material-requirement-v2"

# Backward-compatible public alias. Existing consumers remain bound to v1
# until they explicitly adopt v2.
CONTRACT_ID = V1_CONTRACT_ID

HANDOFF_CONTRACT_ID = "curriculum-workflow-handoff-v1"
MAX_INPUT_BYTES = 48 * 1024
MAX_RESULT_BYTES = 12 * 1024
MAX_ASSETS = 32
MAX_TEMPLATES = 8
MAX_REFERENCES = 64
MAX_REQUIRED_SECTIONS = 32
MAX_BLOCKERS = 32
MAX_REASONS = 32
MAX_DOMAIN_ITEMS = 32
MAX_VISUAL_ROLES = 8

SUPPORTED_ARTIFACT_TYPES = frozenset(
    {
        "slide-deck", "worksheet", "guided-notes", "handout", "rubric",
        "assessment", "exit-ticket", "teacher-guide", "teacher-modeling-package",
        "image-library", "exemplar-set", "critique-set", "portfolio-material",
        "unsupported-manual-review",
    }
)
SUPPORTED_AUDIENCES = frozenset({"students", "teachers", "students-and-teachers"})
COMPLETENESS_STATES = frozenset(
    {
        "draft", "incomplete", "blocked", "manual-review-required",
        "ready-for-planning", "ready-for-approved-production-request", "superseded",
    }
)
CANONICAL_OWNERS = frozenset(
    {
        "agent-orchestrator", "unit-alignment-agent", "teacher-modeling-coach",
        "instructional-materials-coach", "qa-test-agent",
    }
)
CLEARED_STATES = frozenset(
    {"confirmed", "cleared-internal", "licensed", "public-domain", "permission-documented"}
)
DESTINATION_CLASSES = frozenset(
    {"approved-google-drive-folder", "local-reference", "manual-review"}
)
IDENTITY_FIELDS = frozenset(
    {
        "contract_version", "requirement_id", "record_revision", "course_ref",
        "unit_ref", "lesson_ref", "created_at", "created_by",
        "source_fingerprint",
    }
)

V1_TOP_LEVEL_FIELDS = frozenset(
    {
        "identity", "artifact", "instructional", "handoff_reference",
        "learning_evidence", "modeling", "requirements", "assets", "templates",
        "destination", "ai_review", "provenance", "prohibited_data",
        "completeness", "authority",
    }
)

V2_TOP_LEVEL_FIELDS = frozenset(
    set(V1_TOP_LEVEL_FIELDS) | {"visual_direction"}
)

# Backward-compatible alias for current v1 consumers.
TOP_LEVEL_FIELDS = V1_TOP_LEVEL_FIELDS

VISUAL_DECISIONS = frozenset(
    {"unspecified", "no-visuals", "visuals-required"}
)
VISUAL_REQUIREMENT_STATES = frozenset({"required", "optional"})
VISUAL_ROLE_TYPES = frozenset(
    {
        "teacher-model",
        "worked-example",
        "non-example",
        "process-sequence",
        "comparison",
        "annotated-evidence",
        "navigation-orientation",
        "accessibility-support",
        "repeated-reference",
        "critique-exemplar",
    }
)
VISUAL_PLACEMENTS = frozenset(
    {
        "whole-material",
        "section",
        "page",
        "slide",
        "prompt-adjacent",
        "example-adjacent",
        "teacher-only",
        "student-facing",
    }
)
VISUAL_ORIENTATIONS = frozenset(
    {"unspecified", "portrait", "landscape", "square", "wide", "tall"}
)
VISUAL_ROLE_FIELDS = frozenset(
    {
        "role_type",
        "requirement_state",
        "instructional_purpose",
        "intended_placement",
        "orientation",
    }
)

REF_FIELDS = frozenset(
    {"stable_id", "owner", "contract_version", "record_revision", "fingerprint"}
)


# Order-significance declaration for canonicalization.
#
# Every list canonicalized by _canonicalize_material_requirement is
# order-insensitive (set-like) EXCEPT instructional.required_sections, which
# carries teaching order and is therefore order-significant: it is validated
# and preserved exactly as supplied, and fingerprinted stably in that order.
# Fingerprints are always computed and verified over the canonical
# representation (normalize -> canonicalize -> verify), following the
# curriculum-handoff positive control.
ORDER_SIGNIFICANT_LISTS = frozenset({"instructional.required_sections"})


def _sorted_by_key(values: list[Any], name: str, key: str) -> list[Any]:
    """Sort validated mappings by a required key, failing closed on malformed items."""
    checked: list[dict[str, Any]] = []
    for item in values:
        mapping = _mapping(item, name)
        if key not in mapping:
            raise ContractValidationError(
                "handoff-invalid", f"{name} is missing {key}"
            )
        checked.append(mapping)
    return sorted(checked, key=lambda entry: entry[key])


def _ordered_text_list(value: object, name: str, maximum: int) -> list[str]:
    """Validate a text list whose order is semantically significant.

    Same checks as canonical_strings (sequence, bound, text items, non-empty,
    no duplicates) but the supplied order is preserved: teaching order is part
    of the record's meaning and must survive the round trip.
    """
    items = _list(value, name)
    if len(items) > maximum:
        raise ContractValidationError(
            "handoff-oversized", f"{name} exceeds its collection bound"
        )
    checked = [_text(item) for item in items]
    if not checked:
        raise ContractValidationError("handoff-invalid", f"{name} cannot be empty")
    if len(set(checked)) != len(checked):
        raise ContractValidationError("handoff-duplicate", f"{name} contains duplicates")
    return checked


def _canonicalize_material_requirement(data: dict[str, Any]) -> dict[str, Any]:
    """Bring normalized input into canonical list order (in place).

    Order-insensitive (set-like) lists are sorted; instructional.required_sections
    is order-significant and is preserved exactly as supplied. Must run BEFORE
    any fingerprint is computed or verified so that fingerprints always cover
    the canonical representation. Containers that are absent are skipped; the
    validator always runs this after structural checks, so every container
    below is present on the validator path.
    """
    instructional = data.get("instructional")
    if type(instructional) is dict and "required_sections" in instructional:
        instructional["required_sections"] = _ordered_text_list(
            instructional["required_sections"],
            "required sections",
            MAX_REQUIRED_SECTIONS,
        )
    requirements = data.get("requirements")
    if type(requirements) is dict:
        refs = requirements.get("vocabulary_references")
        if type(refs) is list:
            requirements["vocabulary_references"] = _sorted_by_key(
                refs, "vocabulary reference", "stable_id"
            )
        for key in (
            "accessibility_requirements",
            "content_requirements",
            "classroom_use_requirements",
        ):
            if key in requirements:
                requirements[key] = list(
                    _text_list(requirements[key], key, MAX_DOMAIN_ITEMS)
                )
    assets = data.get("assets")
    if type(assets) is list:
        data["assets"] = _sorted_by_key(assets, "asset", "asset_id")
    templates = data.get("templates")
    if type(templates) is list:
        data["templates"] = _sorted_by_key(templates, "template", "template_id")
    completeness = data.get("completeness")
    if type(completeness) is dict:
        if "blockers" in completeness:
            completeness["blockers"] = list(
                canonical_reason_codes(completeness["blockers"], MAX_BLOCKERS)
            )
        if "reason_codes" in completeness:
            completeness["reason_codes"] = list(
                canonical_reason_codes(completeness["reason_codes"], MAX_REASONS)
            )
    visual_direction = data.get("visual_direction")
    if type(visual_direction) is dict and "roles" in visual_direction:
        visual_direction["roles"] = _visual_direction(
            _mapping(visual_direction, "visual_direction")
        )
    return data


def material_requirement_source_fingerprint(value: object) -> str:
    """Fingerprint supplied evidence while excluding evidence-only fields.

    The fingerprint covers the CANONICAL representation: order-insensitive
    lists are canonicalized before hashing, so a producer signing a valid
    non-canonically-ordered input and a validator re-checking the stored
    record compute the same value.
    """
    normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
    if type(normalized) is not dict or type(normalized.get("identity")) is not dict:
        raise ContractValidationError("handoff-wrong-type", "identity must be a built-in mapping")
    try:
        canonical = _canonicalize_material_requirement(normalized)
    except ContractValidationError:
        # Best-effort canonicalization: the validator independently rejects
        # invalid inputs on their own merits, so their fingerprint value is
        # immaterial. Valid inputs always canonicalize, keeping their
        # fingerprints canonical and round-trip stable.
        canonical = normalized
    payload = dict(canonical)
    identity = dict(canonical["identity"])
    identity.pop("source_fingerprint", None)
    identity.pop("created_at", None)
    payload["identity"] = identity
    return sha256_hex(payload)


def validate_material_requirement(value: object) -> ValidationResult:
    """Validate and reconstruct one bounded MaterialRequirement record."""
    try:
        data = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        if type(data) is not dict:
            raise ContractValidationError("handoff-wrong-type", "requirement must be a mapping")
        if "identity" not in data:
            raise ContractValidationError(
                "material-missing-required-field",
                "requirement is incomplete",
            )

        identity = _mapping(data["identity"], "identity")
        _fields(identity, IDENTITY_FIELDS, "identity")
        contract_version = validate_version(identity["contract_version"])

        if contract_version == V1_CONTRACT_ID:
            top_level_fields = V1_TOP_LEVEL_FIELDS
        elif contract_version == V2_CONTRACT_ID:
            top_level_fields = V2_TOP_LEVEL_FIELDS
        else:
            raise ContractValidationError(
                "material-contract-version-unsupported",
                "unsupported version",
            )

        _fields(data, top_level_fields, "requirement")
        groups = {
            name: _mapping(data[name], name)
            for name in top_level_fields - {"assets", "templates"}
        }
        assets = _list(data["assets"], "assets")
        templates = _list(data["templates"], "templates")

        _identity(groups["identity"], contract_version)
        _artifact(groups["artifact"])
        _instructional(groups["instructional"])
        _handoff(groups["handoff_reference"])
        _learning(groups["learning_evidence"])
        _modeling(groups["modeling"])
        ref_count = _requirements(groups["requirements"])
        ref_count += _assets(assets) + _templates(templates) + 7
        if ref_count > MAX_REFERENCES:
            raise ContractValidationError("handoff-oversized", "references exceed bound")
        _destination(groups["destination"])
        _ai_review(groups["ai_review"])
        _provenance(groups["provenance"])
        _all_false(groups["prohibited_data"], "material-prohibited-data")
        _completeness(groups["completeness"])
        _all_false(groups["authority"], "authority-invalid")

        # Canonicalize BEFORE the source fingerprint is verified. Fingerprints
        # are computed and verified over the canonical representation, so a
        # valid record's own serialized form (record.to_dict()) re-validates.
        _canonicalize_material_requirement(data)
        _verify_source_fingerprint(groups["identity"], data)

        if canonical_size(data) > MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "result exceeds 12 KiB")
        identity = groups["identity"]
        record = ValidatedRecord(
            contract_version=identity["contract_version"],
            record_id=identity["requirement_id"],
            record_revision=identity["record_revision"],
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(data),
            payload=freeze_json(data),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return invalid_result(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return invalid_result("material-invalid", sanitize_detail(str(exc)))


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a mapping")
    return value


def _list(value: object, name: str) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a list")
    return value


def _fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    actual = set(value)
    if expected - actual:
        raise ContractValidationError("material-missing-required-field", f"{name} is incomplete")
    if actual - expected:
        raise ContractValidationError("material-unknown-field", f"{name} has unknown fields")


def _text(value: object) -> str:
    return validate_text(value, "material value")


def _text_list(value: object, name: str, maximum: int) -> tuple[str, ...]:
    return canonical_strings(
        value, name=name, maximum=maximum, validator=_text, allow_empty=False
    )


def _identity(
    value: dict[str, Any],
    expected_contract_id: str,
) -> None:
    _fields(value, IDENTITY_FIELDS, "identity")
    if validate_version(value["contract_version"]) != expected_contract_id:
        raise ContractValidationError(
            "material-contract-version-unsupported",
            "unsupported version",
        )
    for key in ("requirement_id", "course_ref", "unit_ref", "lesson_ref"):
        validate_stable_id(value[key], key)
    validate_revision(value["record_revision"])
    validate_timestamp(value["created_at"], "created_at")
    if value["created_by"] != "instructional-materials-coach":
        raise ContractValidationError("material-missing-owner-evidence", "wrong creator owner")
    validate_sha256(value["source_fingerprint"], "source_fingerprint")


def _verify_source_fingerprint(value: dict[str, Any], full: dict[str, Any]) -> None:
    """Verify the supplied source fingerprint against the canonical record.

    Must run AFTER _canonicalize_material_requirement: the fingerprint covers
    the canonical representation, so verifying it against raw input rejects
    the record's own serialized form on revalidation.
    """
    if value["source_fingerprint"] != material_requirement_source_fingerprint(full):
        raise ContractValidationError("material-incompatible-fingerprint", "fingerprint mismatch")


def _artifact(value: dict[str, Any]) -> None:
    _fields(value, frozenset({"artifact_type", "subject_metadata"}), "artifact")
    if validate_text(value["artifact_type"], "artifact_type", max_length=64) not in SUPPORTED_ARTIFACT_TYPES:
        raise ContractValidationError("material-unsupported-artifact-type", "unsupported artifact")
    validate_text(value["subject_metadata"], "subject_metadata")


def _instructional(value: dict[str, Any]) -> None:
    _fields(value, frozenset({"purpose", "audience", "required_sections"}), "instructional")
    validate_text(value["purpose"], "purpose")
    if validate_text(value["audience"], "audience", max_length=64) not in SUPPORTED_AUDIENCES:
        raise ContractValidationError("material-invalid-audience", "unsupported audience")
    # required_sections is order-significant (teaching order): validate without sorting.
    _ordered_text_list(value["required_sections"], "required sections", MAX_REQUIRED_SECTIONS)


def _visual_role_sort_key(value: dict[str, Any]) -> tuple[object, ...]:
    return (
        0 if value["requirement_state"] == "required" else 1,
        value["role_type"],
        value["intended_placement"],
        value["orientation"],
        value["instructional_purpose"],
    )


def _visual_role_semantic_key(
    value: dict[str, Any],
) -> tuple[object, ...]:
    return (
        value["role_type"],
        value["instructional_purpose"],
        value["intended_placement"],
        value["orientation"],
    )


def _visual_direction(value: dict[str, Any]) -> list[dict[str, Any]]:
    _fields(
        value,
        frozenset({"decision", "maximum_visual_count", "roles"}),
        "visual_direction",
    )

    decision = validate_text(
        value["decision"],
        "visual decision",
        max_length=64,
    )
    if decision not in VISUAL_DECISIONS:
        raise ContractValidationError(
            "material-invalid-visual-direction",
            "unsupported visual decision",
        )

    maximum = value["maximum_visual_count"]
    if type(maximum) is not int:
        raise ContractValidationError(
            "handoff-wrong-type",
            "maximum_visual_count must be an integer",
        )
    if maximum < 0 or maximum > MAX_VISUAL_ROLES:
        raise ContractValidationError(
            "material-invalid-visual-direction",
            "maximum_visual_count is outside the supported range",
        )

    roles = _list(value["roles"], "visual roles")
    if len(roles) > MAX_VISUAL_ROLES or len(roles) > maximum:
        raise ContractValidationError(
            "material-invalid-visual-direction",
            "visual role count exceeds the supported maximum",
        )

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()

    for raw in roles:
        role = _mapping(raw, "visual role")
        _fields(role, VISUAL_ROLE_FIELDS, "visual role")

        role_type = validate_text(
            role["role_type"],
            "visual role type",
            max_length=64,
        )
        if role_type not in VISUAL_ROLE_TYPES:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "unsupported visual role type",
            )

        requirement_state = validate_text(
            role["requirement_state"],
            "visual requirement state",
            max_length=64,
        )
        if requirement_state not in VISUAL_REQUIREMENT_STATES:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "unsupported visual requirement state",
            )

        purpose = validate_text(
            role["instructional_purpose"],
            "visual instructional purpose",
        )

        placement = validate_text(
            role["intended_placement"],
            "visual intended placement",
            max_length=64,
        )
        if placement not in VISUAL_PLACEMENTS:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "unsupported visual placement",
            )

        orientation = validate_text(
            role["orientation"],
            "visual orientation",
            max_length=64,
        )
        if orientation not in VISUAL_ORIENTATIONS:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "unsupported visual orientation",
            )

        normalized_role = {
            "role_type": role_type,
            "requirement_state": requirement_state,
            "instructional_purpose": purpose,
            "intended_placement": placement,
            "orientation": orientation,
        }
        semantic_key = _visual_role_semantic_key(normalized_role)
        if semantic_key in seen:
            raise ContractValidationError(
                "material-duplicate-visual-role",
                "duplicate visual role",
            )
        seen.add(semantic_key)
        normalized.append(normalized_role)

    if decision == "no-visuals":
        if maximum != 0 or normalized:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "no-visuals requires zero roles and zero maximum",
            )

    if decision == "unspecified":
        if maximum != 0 or normalized:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "unspecified requires zero roles and zero maximum",
            )

    if decision == "visuals-required":
        if maximum < 1:
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "visuals-required needs a positive maximum",
            )
        if not any(
            role["requirement_state"] == "required"
            for role in normalized
        ):
            raise ContractValidationError(
                "material-invalid-visual-direction",
                "visuals-required needs at least one required role",
            )

    return sorted(normalized, key=_visual_role_sort_key)


def _handoff(value: dict[str, Any]) -> None:
    _fields(
        value,
        frozenset({"handoff_id", "contract_version", "record_revision", "fingerprint"}),
        "handoff_reference",
    )
    validate_stable_id(value["handoff_id"], "handoff_id")
    if validate_version(value["contract_version"]) != HANDOFF_CONTRACT_ID:
        raise ContractValidationError("material-incompatible-handoff", "incompatible handoff")
    validate_revision(value["record_revision"])
    validate_sha256(value["fingerprint"], "handoff fingerprint")


def _reference(value: object, name: str, owner: str | None = None) -> None:
    ref = _mapping(value, name)
    _fields(ref, REF_FIELDS, name)
    validate_stable_id(ref["stable_id"], f"{name} stable_id")
    actual_owner = validate_stable_id(ref["owner"], f"{name} owner")
    if actual_owner not in CANONICAL_OWNERS or (owner is not None and actual_owner != owner):
        raise ContractValidationError("material-missing-owner-evidence", f"{name} owner conflict")
    validate_version(ref["contract_version"])
    validate_revision(ref["record_revision"])
    validate_sha256(ref["fingerprint"], f"{name} fingerprint")


def _learning(value: dict[str, Any]) -> None:
    keys = frozenset(
        {"learning_objective_ref", "success_criteria_ref", "evidence_target_ref", "alignment_owner"}
    )
    _fields(value, keys, "learning_evidence")
    if value["alignment_owner"] != "unit-alignment-agent":
        raise ContractValidationError("material-missing-owner-evidence", "alignment owner conflict")
    for key in keys - {"alignment_owner"}:
        _reference(value[key], key, "unit-alignment-agent")


def _modeling(value: dict[str, Any]) -> None:
    keys = frozenset({"modeling_readiness_ref", "materials_extract_ref", "modeling_owner"})
    _fields(value, keys, "modeling")
    if value["modeling_owner"] != "teacher-modeling-coach":
        raise ContractValidationError("material-missing-owner-evidence", "modeling owner conflict")
    for key in keys - {"modeling_owner"}:
        _reference(value[key], key, "teacher-modeling-coach")


def _requirements(value: dict[str, Any]) -> int:
    keys = frozenset(
        {
            "vocabulary_references", "accessibility_requirements",
            "content_requirements", "classroom_use_requirements",
        }
    )
    _fields(value, keys, "requirements")
    refs = _list(value["vocabulary_references"], "vocabulary_references")
    if len(refs) > MAX_REFERENCES:
        raise ContractValidationError("handoff-oversized", "too many references")
    seen: set[str] = set()
    for ref in refs:
        _reference(ref, "vocabulary reference")
        stable_id = ref["stable_id"]
        if stable_id in seen:
            raise ContractValidationError("material-duplicate-reference", "duplicate reference")
        seen.add(stable_id)
    for key in keys - {"vocabulary_references"}:
        _text_list(value[key], key, MAX_DOMAIN_ITEMS)
    return len(refs)


def _assets(values: list[Any]) -> int:
    if len(values) > MAX_ASSETS:
        raise ContractValidationError("handoff-oversized", "too many assets")
    seen: set[str] = set()
    fields = frozenset(
        {"asset_id", "stable_ref", "access_state", "permission_state", "provenance_state"}
    )
    for raw in values:
        value = _mapping(raw, "asset")
        _fields(value, fields, "asset")
        asset_id = validate_stable_id(value["asset_id"], "asset_id")
        if asset_id in seen:
            raise ContractValidationError("material-duplicate-asset", "duplicate asset")
        seen.add(asset_id)
        validate_stable_id(value["stable_ref"], "asset stable_ref")
        if value["access_state"] != "verified":
            raise ContractValidationError("material-unverified-asset", "unverified asset")
        if value["permission_state"] not in CLEARED_STATES:
            raise ContractValidationError("material-permission-incomplete", "asset permission")
        if value["provenance_state"] not in CLEARED_STATES:
            raise ContractValidationError("material-provenance-incomplete", "asset provenance")
    return len(values)


def _templates(values: list[Any]) -> int:
    if len(values) > MAX_TEMPLATES:
        raise ContractValidationError("handoff-oversized", "too many templates")
    seen: set[str] = set()
    fields = frozenset({"template_id", "stable_ref", "access_state", "permission_state"})
    for raw in values:
        value = _mapping(raw, "template")
        _fields(value, fields, "template")
        template_id = validate_stable_id(value["template_id"], "template_id")
        if template_id in seen:
            raise ContractValidationError("material-duplicate-template", "duplicate template")
        seen.add(template_id)
        validate_stable_id(value["stable_ref"], "template stable_ref")
        if value["access_state"] != "verified":
            raise ContractValidationError("material-unverified-template", "unverified template")
        if value["permission_state"] not in CLEARED_STATES:
            raise ContractValidationError("material-permission-incomplete", "template permission")
    return len(values)


def _destination(value: dict[str, Any]) -> None:
    _fields(
        value,
        frozenset({"destination_id", "destination_class", "verification_state", "exact_reference"}),
        "destination",
    )
    validate_stable_id(value["destination_id"], "destination_id")
    if value["destination_class"] not in DESTINATION_CLASSES or value["verification_state"] != "verified":
        raise ContractValidationError("material-ambiguous-destination", "ambiguous destination")
    validate_text(value["exact_reference"], "destination exact_reference")


def _ai_review(value: dict[str, Any]) -> None:
    bools = {
        "ai_assisted_generation_permitted", "accessibility_review_required",
        "nondiscrimination_review_required",
    }
    _fields(value, frozenset(bools | {"human_review_owner"}), "ai_review")
    if any(type(value[key]) is not bool for key in bools):
        raise ContractValidationError("handoff-wrong-type", "AI review flags must be booleans")
    if validate_stable_id(value["human_review_owner"], "human_review_owner") not in CANONICAL_OWNERS:
        raise ContractValidationError("material-ai-review-owner-missing", "unsupported reviewer")


def _provenance(value: dict[str, Any]) -> None:
    states = {
        "provenance_state", "copyright_state", "license_state", "asset_permission_state"
    }
    _fields(value, frozenset(states | {"citation_expectations"}), "provenance")
    validate_text(value["citation_expectations"], "citation_expectations")
    if any(value[key] not in CLEARED_STATES for key in states):
        raise ContractValidationError("material-provenance-incomplete", "provenance incomplete")


def _all_false(value: dict[str, Any], reason: str) -> None:
    expected = (
        frozenset(
            {
                "student_identifying_data", "protected_attributes",
                "raw_student_work", "permanent_learner_profile",
            }
        )
        if reason == "material-prohibited-data"
        else frozenset(
            {
                "execution_authorized", "external_write_authorized",
                "production_authorized", "publication_authorized", "side_effects_performed",
            }
        )
    )
    _fields(value, expected, "protected boundary")
    if any(type(item) is not bool or item is not False for item in value.values()):
        raise ContractValidationError(reason, "all boundary values must be false")


def _completeness(value: dict[str, Any]) -> None:
    _fields(value, frozenset({"state", "blockers", "reason_codes"}), "completeness")
    state = validate_text(value["state"], "completeness state", max_length=64)
    if state not in COMPLETENESS_STATES:
        raise ContractValidationError("material-invalid-completeness-state", "bad state")
    blockers = canonical_reason_codes(value["blockers"], MAX_BLOCKERS)
    reasons = canonical_reason_codes(value["reason_codes"], MAX_REASONS)
    if state == "blocked" and not blockers:
        raise ContractValidationError("material-incomplete", "blocked state needs blockers")
    if state in {"incomplete", "manual-review-required"} and not reasons:
        raise ContractValidationError("material-incomplete", "state needs reasons")
    if state.startswith("ready-") and blockers:
        raise ContractValidationError("material-incomplete", "ready state has blockers")
