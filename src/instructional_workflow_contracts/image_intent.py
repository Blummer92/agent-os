"""Provider-neutral ImageIntent and imported-asset context contracts.

The structured intent is canonical. Provider-ready prompt prose is a deterministic,
human-copyable derivative and never becomes authoritative evidence.
"""

from __future__ import annotations

from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
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
    validate_version,
)

IMAGE_INTENT_CONTRACT_ID = "curriculum-image-intent-v1"
IMPORTED_ASSET_CONTEXT_CONTRACT_ID = "curriculum-imported-asset-context-v1"
MAX_INPUT_BYTES = 32 * 1024
MAX_RESULT_BYTES = 12 * 1024
MAX_LIST_ITEMS = 16

ORIENTATIONS = frozenset({"portrait", "landscape", "square", "wide", "tall", "unspecified"})
SOURCE_MODES = frozenset({"upload", "import"})
PROVIDER_CLAIMS = frozenset({"gemini", "meta", "firefly", "canva", "other", "unknown"})

INTENT_TOP_LEVEL_FIELDS = frozenset(
    {"identity", "scene", "visual_direction", "control", "output", "library_handoff"}
)
IDENTITY_FIELDS = frozenset({"contract_version", "intent_id", "asset_id", "concept", "purpose"})
SCENE_FIELDS = frozenset({"subject", "action", "environment"})
VISUAL_DIRECTION_FIELDS = frozenset({"composition", "viewpoint", "look"})
CONTROL_FIELDS = frozenset({"must_show", "avoid", "creative_freedom"})
OUTPUT_FIELDS = frozenset({"orientation", "aspect_target", "add_later"})
LIBRARY_HANDOFF_FIELDS = frozenset(
    {"unit_lesson", "asset_role", "intended_reuse", "candidate_status", "review_notes"}
)

IMPORTED_CONTEXT_FIELDS = frozenset(
    {
        "contract_version",
        "context_id",
        "source_mode",
        "provider_claim",
        "prompt_claim",
        "model_claim",
        "generated_at_claim",
        "original_filename",
        "source_note",
    }
)


def validate_image_intent(value: object) -> ValidationResult:
    """Validate one bounded provider-neutral ImageIntent."""
    try:
        data = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        if type(data) is not dict:
            raise ContractValidationError("handoff-wrong-type", "image intent must be a built-in mapping")
        _fields(data, INTENT_TOP_LEVEL_FIELDS, "image intent")

        identity = _mapping(data["identity"], "identity")
        scene = _mapping(data["scene"], "scene")
        visual_direction = _mapping(data["visual_direction"], "visual_direction")
        control = _mapping(data["control"], "control")
        output = _mapping(data["output"], "output")
        library_handoff = _mapping(data["library_handoff"], "library_handoff")

        _fields(identity, IDENTITY_FIELDS, "identity")
        _fields(scene, SCENE_FIELDS, "scene")
        _fields(visual_direction, VISUAL_DIRECTION_FIELDS, "visual_direction")
        _fields(control, CONTROL_FIELDS, "control")
        _fields(output, OUTPUT_FIELDS, "output")
        _fields(library_handoff, LIBRARY_HANDOFF_FIELDS, "library_handoff")

        contract_version = validate_version(identity["contract_version"])
        if contract_version != IMAGE_INTENT_CONTRACT_ID:
            raise ContractValidationError(
                "handoff-version-unsupported", "unsupported ImageIntent contract version"
            )
        intent_id = validate_stable_id(identity["intent_id"], "intent_id")
        _optional_stable_id(identity["asset_id"], "asset_id")
        validate_text(identity["concept"], "concept")
        validate_text(identity["purpose"], "purpose")

        validate_text(scene["subject"], "subject")
        _optional_text(scene["action"], "action")
        _optional_text(scene["environment"], "environment")

        validate_text(visual_direction["composition"], "composition")
        validate_text(visual_direction["viewpoint"], "viewpoint")
        validate_text(visual_direction["look"], "look")

        data["control"]["must_show"] = list(
            _text_list(control["must_show"], "must_show", allow_empty=False)
        )
        data["control"]["avoid"] = list(_text_list(control["avoid"], "avoid"))
        data["control"]["creative_freedom"] = list(
            _text_list(control["creative_freedom"], "creative_freedom")
        )

        orientation = validate_text(output["orientation"], "orientation", max_length=32)
        if orientation not in ORIENTATIONS:
            raise ContractValidationError("handoff-invalid", "orientation is unsupported")
        validate_text(output["aspect_target"], "aspect_target", max_length=64)
        data["output"]["add_later"] = list(_text_list(output["add_later"], "add_later"))

        _optional_text(library_handoff["unit_lesson"], "unit_lesson")
        _optional_text(library_handoff["asset_role"], "asset_role")
        data["library_handoff"]["intended_reuse"] = list(
            _text_list(library_handoff["intended_reuse"], "intended_reuse")
        )
        _optional_text(library_handoff["candidate_status"], "candidate_status")
        _optional_text(library_handoff["review_notes"], "review_notes")

        if canonical_size(data) > MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "ImageIntent exceeds result-size bound")

        record = ValidatedRecord(
            contract_version=contract_version,
            record_id=intent_id,
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(data),
            payload=freeze_json(data),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("handoff-invalid", sanitize_detail(str(exc)))


def validate_imported_asset_context(value: object) -> ValidationResult:
    """Validate user-supplied import/generation context without inventing history."""
    try:
        data = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        if type(data) is not dict:
            raise ContractValidationError(
                "handoff-wrong-type", "imported asset context must be a built-in mapping"
            )
        _fields(data, IMPORTED_CONTEXT_FIELDS, "imported asset context")

        contract_version = validate_version(data["contract_version"])
        if contract_version != IMPORTED_ASSET_CONTEXT_CONTRACT_ID:
            raise ContractValidationError(
                "handoff-version-unsupported", "unsupported ImportedAssetContext contract version"
            )
        context_id = validate_stable_id(data["context_id"], "context_id")
        source_mode = validate_text(data["source_mode"], "source_mode", max_length=16)
        if source_mode not in SOURCE_MODES:
            raise ContractValidationError("handoff-invalid", "source_mode is unsupported")
        provider_claim = validate_text(data["provider_claim"], "provider_claim", max_length=32)
        if provider_claim not in PROVIDER_CLAIMS:
            raise ContractValidationError("handoff-invalid", "provider_claim is unsupported")

        for field in (
            "prompt_claim",
            "model_claim",
            "generated_at_claim",
            "original_filename",
            "source_note",
        ):
            _optional_text(data[field], field)

        if canonical_size(data) > MAX_RESULT_BYTES:
            raise ContractValidationError(
                "handoff-oversized", "ImportedAssetContext exceeds result-size bound"
            )

        record = ValidatedRecord(
            contract_version=contract_version,
            record_id=context_id,
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(data),
            payload=freeze_json(data),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return _invalid(exc.reason_code, exc.detail)
    except (TypeError, ValueError) as exc:
        return _invalid("handoff-invalid", sanitize_detail(str(exc)))


def assemble_gemini_manual_prompt(intent: ValidatedRecord) -> str:
    """Render deterministic Gemini-ready prose from a validated ImageIntent.

    The returned text is a convenience derivative. It intentionally excludes all
    library-handoff metadata and carries no approval, provenance, or generation authority.
    """
    if type(intent) is not ValidatedRecord:
        raise TypeError("intent must be a ValidatedRecord")
    if intent.contract_version != IMAGE_INTENT_CONTRACT_ID:
        raise ValueError("intent must use the ImageIntent contract")

    data = intent.to_dict()
    identity = data["identity"]
    scene = data["scene"]
    direction = data["visual_direction"]
    control = data["control"]
    output = data["output"]

    sentence1 = f"Create an instructional image for {identity['concept']}: {scene['subject']}"
    if scene["action"] is not None:
        sentence1 += f" {scene['action']}"
    if scene["environment"] is not None:
        sentence1 += f" in {scene['environment']}"
    sentence1 += f". The image should clearly teach {identity['purpose']}."

    sentences = [
        sentence1,
        (
            f"Use {direction['composition']} composition from {direction['viewpoint']} viewpoint, "
            f"with {direction['look']}."
        ),
        "Must visibly include: " + "; ".join(control["must_show"]) + ".",
    ]
    if control["creative_freedom"]:
        sentences.append("Creative freedom: " + "; ".join(control["creative_freedom"]) + ".")
    if control["avoid"]:
        sentences.append("Avoid: " + "; ".join(control["avoid"]) + ".")
    sentences.append(
        f"Output a {output['orientation']} image targeting {output['aspect_target']}."
    )
    if output["add_later"]:
        sentences.append(
            "Keep the clean master free of these instructional overlays; add them later: "
            + "; ".join(output["add_later"])
            + "."
        )
    return " ".join(sentences)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    return value


def _fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        raise ContractValidationError("handoff-unknown-field", f"{name} fields are not exact")


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return validate_text(value, name)


def _optional_stable_id(value: object, name: str) -> str | None:
    if value is None:
        return None
    return validate_stable_id(value, name)


def _text_list(value: object, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    return canonical_strings(
        value,
        name=name,
        maximum=MAX_LIST_ITEMS,
        validator=lambda item: validate_text(item, name),
        allow_empty=allow_empty,
    )


def _invalid(reason_code: str, detail: str) -> ValidationResult:
    return ValidationResult(
        status=ValidationStatus.INVALID,
        record=None,
        reason_codes=(reason_code,),
        details=(sanitize_detail(detail),),
    )
