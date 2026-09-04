from instructional_workflow_contracts.visual_asset_picker import (
    AssetCandidate,
    AssetPickerIntent,
    merge_asset_picker_intent,
    resolve_visual_asset_picker,
)


def candidate(asset_id: str, **overrides):
    values = dict(asset_id=asset_id, source_reference=f"notion:{asset_id}", eligible=True, review_status="approved")
    values.update(overrides)
    return AssetCandidate(**values)


def test_underspecified_request_defaults_to_reuse_first_without_generation():
    result = resolve_visual_asset_picker(AssetPickerIntent(), [candidate("asset-a", unit_match=True)])
    assert result.source_preference == "reuse-first"
    assert result.generation_allowed is False
    assert result.selected_references[0].asset_id == "asset-a"


def test_reuse_only_hard_constraint_overrides_earlier_generation_permission():
    merged = merge_asset_picker_intent(
        AssetPickerIntent(source_preference="reuse-first", generation_allowed=True),
        AssetPickerIntent(source_preference="reuse-only", generation_allowed=False),
    )
    result = resolve_visual_asset_picker(merged, [])
    assert (result.source_preference, result.generation_allowed, result.outcome, result.create_new_handoff_allowed) == ("reuse-only", False, "visual-gap", False)


def test_ranking_prioritizes_instructional_relevance_before_recency():
    older_match = candidate("asset-match", unit_match=True, concept_match=True, role_match=True, recency_rank=1)
    newer_weak = candidate("asset-new", recency_rank=99)
    result = resolve_visual_asset_picker(AssetPickerIntent(), [newer_weak, older_match])
    assert result.recommended_asset_ids[0] == "asset-match"


def test_candidate_first_ambiguity_returns_real_candidates_not_abstract_question():
    intent = AssetPickerIntent(source_preference="explicit-existing", selection_authority="teacher-select")
    result = resolve_visual_asset_picker(intent, [candidate("old-a"), candidate("old-b")])
    assert result.outcome == "candidate-choice-required"
    assert set(result.recommended_asset_ids) == {"old-a", "old-b"}
    assert result.selected_references == ()


def test_needs_review_candidate_never_enters_selected_references():
    result = resolve_visual_asset_picker(AssetPickerIntent(), [candidate("review-a", review_status="needs-review")])
    assert result.outcome == "visual-gap"
    assert result.needs_review_asset_ids == ("review-a",)
    assert result.selected_references == ()


def test_library_failure_does_not_silently_enable_generation():
    result = resolve_visual_asset_picker(
        AssetPickerIntent(source_preference="reuse-first", generation_allowed=True), [], library_available=False
    )
    assert result.outcome == "library-unavailable"
    assert result.create_new_handoff_allowed is False


def test_selected_identity_and_source_are_preserved_for_downstream_materials():
    chosen = candidate("asset-a", source_reference="notion:page-123", unit_match=True)
    result = resolve_visual_asset_picker(AssetPickerIntent(), [chosen], selected_asset_ids=("asset-a",))
    reference = result.selected_references[0]
    assert (reference.asset_id, reference.source_reference, reference.review_status) == ("asset-a", "notion:page-123", "approved")


def test_selected_asset_becoming_unavailable_returns_to_picker_resolution():
    result = resolve_visual_asset_picker(AssetPickerIntent(), [candidate("asset-a")], selected_asset_ids=("missing-asset",))
    assert result.outcome == "selection-invalidated"


def test_explicit_requested_asset_scope_does_not_substitute_another_asset():
    intent = AssetPickerIntent(source_preference="explicit-existing", requested_asset_ids=("wanted",))
    result = resolve_visual_asset_picker(intent, [candidate("other", unit_match=True)])
    assert result.outcome == "visual-gap"
