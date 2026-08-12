from instructional_workflow_contracts.image_intent import (
    IMAGE_INTENT_CONTRACT_ID,
    IMPORTED_ASSET_CONTEXT_CONTRACT_ID,
    assemble_gemini_manual_prompt,
    validate_image_intent,
    validate_imported_asset_context,
)
from instructional_workflow_contracts.common import (
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    ValidationStatus,
    freeze_json,
)


def _leading_lines_intent() -> dict:
    return {
        "identity": {
            "contract_version": IMAGE_INTENT_CONTRACT_ID,
            "intent_id": "image-intent:photo-leading-lines-001",
            "asset_id": "PHOTO-COMP-LINES-001",
            "concept": "Leading Lines",
            "purpose": "how lines can guide the viewer toward a clear subject",
        },
        "scene": {
            "subject": "one clearly visible student subject",
            "action": "standing naturally near the end of a walkway",
            "environment": "a believable school or public environment",
        },
        "visual_direction": {
            "composition": "strong directional lines that converge toward the subject",
            "viewpoint": "student eye-level",
            "look": "realistic natural daylight photography",
        },
        "control": {
            "must_show": [
                "a single dominant subject",
                "visible lines that clearly guide the eye toward the subject",
            ],
            "avoid": [
                "surreal architecture",
                "lines that lead away from the subject",
            ],
            "creative_freedom": [
                "the exact school or public setting",
                "the subject's clothing and pose",
            ],
        },
        "output": {
            "orientation": "landscape",
            "aspect_target": "3:2",
            "add_later": ["subtle line traces or arrows if instructional cueing is needed"],
        },
        "library_handoff": {
            "unit_lesson": "Photography Foundations / Elements & Composition",
            "asset_role": "Instructional photographic example",
            "intended_reuse": ["challenge cards", "slides", "modeling", "critique"],
            "candidate_status": "needs governed review",
            "review_notes": "Preserve a clean master.",
        },
    }


def _frame_within_frame_intent() -> dict:
    return {
        "identity": {
            "contract_version": IMAGE_INTENT_CONTRACT_ID,
            "intent_id": "image-intent:photo-frame-001",
            "asset_id": None,
            "concept": "Frame Within a Frame",
            "purpose": "how foreground elements can frame and emphasize the main subject",
        },
        "scene": {
            "subject": "one person clearly visible through a doorway or window opening",
            "action": None,
            "environment": "an ordinary school or community setting",
        },
        "visual_direction": {
            "composition": "a natural architectural opening surrounding the subject",
            "viewpoint": "straight-on or slight three-quarter student viewpoint",
            "look": "believable documentary-style photography",
        },
        "control": {
            "must_show": [
                "the framing element around the subject",
                "clear separation between the frame and subject",
            ],
            "avoid": ["decorative borders added in software"],
            "creative_freedom": ["exact doorway, window, arch, or foreground opening"],
        },
        "output": {
            "orientation": "portrait",
            "aspect_target": "4:5",
            "add_later": [],
        },
        "library_handoff": {
            "unit_lesson": "Photography Foundations / Elements & Composition",
            "asset_role": "Instructional photographic example",
            "intended_reuse": ["slides", "critique"],
            "candidate_status": "needs governed review",
            "review_notes": None,
        },
    }


def test_two_photography_composition_fixtures_validate() -> None:
    for fixture in (_leading_lines_intent(), _frame_within_frame_intent()):
        result = validate_image_intent(fixture)
        assert result.status is ValidationStatus.VALID
        assert result.record is not None
        assert result.record.contract_version == IMAGE_INTENT_CONTRACT_ID
        assert result.authority.execution_authorized is False
        assert result.authority.external_write_authorized is False


def test_gemini_prompt_is_deterministic_and_excludes_library_metadata() -> None:
    result = validate_image_intent(_leading_lines_intent())
    assert result.record is not None

    first = assemble_gemini_manual_prompt(result.record)
    second = assemble_gemini_manual_prompt(result.record)

    assert first == second
    assert "Leading Lines" in first
    assert "Must visibly include:" in first
    assert "Avoid:" in first
    assert "add them later" in first
    assert "Photography Foundations" not in first
    assert "challenge cards" not in first
    assert "needs governed review" not in first


def test_prompt_omits_empty_optional_sections() -> None:
    result = validate_image_intent(_frame_within_frame_intent())
    assert result.record is not None

    prompt = assemble_gemini_manual_prompt(result.record)

    assert "Frame Within a Frame" in prompt
    assert "add them later" not in prompt


def test_prompt_rejects_malformed_validated_record_payload() -> None:
    malformed = ValidatedRecord(
        contract_version=IMAGE_INTENT_CONTRACT_ID,
        record_id="image-intent:malformed-001",
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint="0" * 64,
        payload=freeze_json({"identity": {"contract_version": IMAGE_INTENT_CONTRACT_ID}}),
    )

    try:
        assemble_gemini_manual_prompt(malformed)
    except ValueError as exc:
        assert str(exc) == "intent payload must be a valid ImageIntent"
    else:
        raise AssertionError("malformed ImageIntent record must fail closed")


def test_imported_asset_context_preserves_unknown_claims() -> None:
    context = {
        "contract_version": IMPORTED_ASSET_CONTEXT_CONTRACT_ID,
        "context_id": "imported-asset:001",
        "source_mode": "upload",
        "provider_claim": "unknown",
        "prompt_claim": None,
        "model_claim": None,
        "generated_at_claim": None,
        "original_filename": "IMG_1024.png",
        "source_note": "Teacher supplied the file without generation history.",
    }

    result = validate_imported_asset_context(context)

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["provider_claim"] == "unknown"
    assert payload["prompt_claim"] is None
    assert payload["model_claim"] is None
    assert payload["generated_at_claim"] is None


def test_imported_asset_context_treats_provider_as_claim_not_authority() -> None:
    context = {
        "contract_version": IMPORTED_ASSET_CONTEXT_CONTRACT_ID,
        "context_id": "imported-asset:002",
        "source_mode": "import",
        "provider_claim": "gemini",
        "prompt_claim": "A supplied prompt claim",
        "model_claim": "supplied-model-name",
        "generated_at_claim": "2026-08-11",
        "original_filename": "candidate.png",
        "source_note": None,
    }

    result = validate_imported_asset_context(context)

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    assert result.record.authority.execution_authorized is False
    assert result.record.authority.publication_authorized is False


def test_image_intent_rejects_unknown_fields_and_missing_must_show() -> None:
    intent = _leading_lines_intent()
    intent["provider_prompt"] = "should not be canonical"
    invalid = validate_image_intent(intent)
    assert invalid.status is ValidationStatus.INVALID
    assert "handoff-unknown-field" in invalid.reason_codes

    intent = _leading_lines_intent()
    intent["control"]["must_show"] = []
    invalid = validate_image_intent(intent)
    assert invalid.status is ValidationStatus.INVALID


def test_invalid_provider_claim_fails_closed() -> None:
    context = {
        "contract_version": IMPORTED_ASSET_CONTEXT_CONTRACT_ID,
        "context_id": "imported-asset:003",
        "source_mode": "upload",
        "provider_claim": "probably-gemini",
        "prompt_claim": None,
        "model_claim": None,
        "generated_at_claim": None,
        "original_filename": None,
        "source_note": None,
    }

    result = validate_imported_asset_context(context)
    assert result.status is ValidationStatus.INVALID
