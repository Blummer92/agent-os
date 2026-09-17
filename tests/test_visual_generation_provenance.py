from dataclasses import replace

from instructional_workflow_contracts.common import (
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    ValidationStatus,
    freeze_json,
    sha256_hex,
)
from instructional_workflow_contracts.image_intent import (
    validate_image_intent,
    validate_imported_asset_context,
)
from instructional_workflow_contracts.visual_generation_provenance import (
    bind_gap_to_image_intent,
    bind_returned_image_intake,
    project_routing_provenance,
)


def _cohesive_plan(*, role_id: str = "role-weak-rule-of-thirds") -> ValidatedRecord:
    gap = {
        "brief_id": "image-gap-weak-rule-thirds",
        "missing_visual_role_id": role_id,
        "missing_visual_role_type": "non-example",
    }
    payload = {
        "contract_version": "curriculum-cohesive-visual-plan-v1",
        "cohesive_visual_plan_id": "cohesive-plan-photography-foundations",
        "image_gap_briefs": [gap],
    }
    return ValidatedRecord(
        contract_version=payload["contract_version"],
        record_id=payload["cohesive_visual_plan_id"],
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(payload),
        payload=freeze_json(payload),
    )


def _intent(*, intent_id: str = "intent-weak-rule-of-thirds", composition: str = "subject centered to demonstrate a weak rule-of-thirds composition") -> ValidatedRecord:
    result = validate_image_intent(
        {
            "identity": {
                "contract_version": "curriculum-image-intent-v1",
                "intent_id": intent_id,
                "asset_id": None,
                "concept": "Weak Rule of Thirds Example",
                "purpose": "show a composition non-example for Photography Foundations",
            },
            "scene": {
                "subject": "one everyday classroom object",
                "action": None,
                "environment": "a simple classroom setting",
            },
            "visual_direction": {
                "composition": composition,
                "viewpoint": "eye level",
                "look": "natural photographic classroom example",
            },
            "control": {
                "must_show": ["clear centered focal subject"],
                "avoid": ["rule-of-thirds placement"],
                "creative_freedom": [],
            },
            "output": {
                "orientation": "landscape",
                "aspect_target": "16:9",
                "add_later": [],
            },
            "library_handoff": {
                "unit_lesson": "Photography Foundations / Elements & Composition",
                "asset_role": "Weak Rule of Thirds Example",
                "intended_reuse": ["composition non-example"],
                "candidate_status": None,
                "review_notes": None,
            },
        }
    )
    assert result.status is ValidationStatus.VALID and result.record is not None
    return result.record


def _imported_context(*, filename: str = "returned.png", prompt: str | None = "teacher copied prompt") -> ValidatedRecord:
    result = validate_imported_asset_context(
        {
            "contract_version": "curriculum-imported-asset-context-v1",
            "context_id": "import-context-returned-rule-thirds",
            "source_mode": "upload",
            "provider_claim": "unknown",
            "prompt_claim": prompt,
            "model_claim": None,
            "generated_at_claim": None,
            "original_filename": filename,
            "source_note": "teacher-returned image",
        }
    )
    assert result.status is ValidationStatus.VALID and result.record is not None
    return result.record


def test_gap_to_intent_binding_is_deterministic_and_prompt_prose_is_not_identity() -> None:
    plan = _cohesive_plan()
    intent = _intent()
    first = bind_gap_to_image_intent(
        plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=intent,
    )
    second = bind_gap_to_image_intent(
        plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=intent,
    )
    assert first.status is second.status is ValidationStatus.VALID
    assert first.record is not None and second.record is not None
    assert first.record.record_id == second.record.record_id
    assert first.record.fingerprint == second.record.fingerprint
    assert "prompt" not in repr(first.record.to_dict()).lower()


def test_wrong_plan_gap_role_or_intent_fingerprint_fails_closed() -> None:
    plan = _cohesive_plan()
    intent = _intent()
    wrong_role = bind_gap_to_image_intent(
        plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-other",
        image_intent=intent,
    )
    assert wrong_role.status is ValidationStatus.INVALID

    stale_intent = replace(intent, fingerprint="0" * 64)
    stale = bind_gap_to_image_intent(
        plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=stale_intent,
    )
    assert stale.status is ValidationStatus.INVALID

    stale_plan = replace(plan, fingerprint="f" * 64)
    bad_plan = bind_gap_to_image_intent(
        stale_plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=intent,
    )
    assert bad_plan.status is ValidationStatus.INVALID


def test_different_gap_or_intent_changes_binding_identity() -> None:
    first_plan = _cohesive_plan()
    second_plan = _cohesive_plan(role_id="role-weak-rule-of-thirds-alt")
    first = bind_gap_to_image_intent(
        first_plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=_intent(),
    )
    second = bind_gap_to_image_intent(
        second_plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds-alt",
        image_intent=_intent(intent_id="intent-weak-rule-of-thirds-alt"),
    )
    assert first.record is not None and second.record is not None
    assert first.record.record_id != second.record.record_id


def test_returned_intake_binds_exactly_without_filename_or_prompt_identity() -> None:
    handoff = bind_gap_to_image_intent(
        _cohesive_plan(),
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=_intent(),
    ).record
    assert handoff is not None
    context = _imported_context(filename="anything.png", prompt="arbitrary claim")
    binding = bind_returned_image_intake(
        handoff,
        imported_asset_context=context,
        intake_id="intake-photography-rule-thirds",
    )
    assert binding.status is ValidationStatus.VALID and binding.record is not None
    payload = binding.record.to_dict()
    assert payload["intake_id"] == "intake-photography-rule-thirds"
    assert "original_filename" not in repr(payload)
    assert "prompt_claim" not in repr(payload)
    projection = project_routing_provenance(handoff, binding.record)
    assert projection["brief_id"] == "image-gap-weak-rule-thirds"
    assert projection["intent_id"] == "intent-weak-rule-of-thirds"
    assert projection["intake_id"] == "intake-photography-rule-thirds"
    assert not any(projection["authority"].values())


def test_teacher_correction_preserves_prior_association_and_ambiguous_case_reviews() -> None:
    handoff = bind_gap_to_image_intent(
        _cohesive_plan(),
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=_intent(),
    ).record
    assert handoff is not None
    context = _imported_context()
    missing_prior = bind_returned_image_intake(
        handoff,
        imported_asset_context=context,
        intake_id="intake-photography-rule-thirds",
        association_state="corrected",
    )
    assert missing_prior.status is ValidationStatus.INVALID

    corrected = bind_returned_image_intake(
        handoff,
        imported_asset_context=context,
        intake_id="intake-photography-rule-thirds",
        association_state="corrected",
        prior_generation_handoff_id="visual-generation-handoff-prior",
    )
    assert corrected.status is ValidationStatus.VALID and corrected.record is not None
    assert corrected.record.to_dict()["prior_generation_handoff_id"] == "visual-generation-handoff-prior"

    review = bind_returned_image_intake(
        handoff,
        imported_asset_context=context,
        intake_id="intake-photography-rule-thirds",
        association_state="manual-review-required",
    )
    assert review.status is ValidationStatus.MANUAL_REVIEW_REQUIRED


def test_composition_remains_image_intent_owned_and_authority_is_false() -> None:
    plan = _cohesive_plan()
    intent = _intent(composition="deliberately weak centered composition")
    handoff = bind_gap_to_image_intent(
        plan,
        brief_id="image-gap-weak-rule-thirds",
        missing_visual_role_id="role-weak-rule-of-thirds",
        image_intent=intent,
    )
    assert handoff.status is ValidationStatus.VALID and handoff.record is not None
    payload = handoff.record.to_dict()
    assert "composition" not in repr(payload)
    assert not any(payload["authority"].values())
