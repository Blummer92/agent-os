from visual_asset_routing import (
    DestinationContext,
    RoutingState,
    SemanticObservation,
    TeacherAction,
    apply_teacher_action,
    recommend_route,
)


def _observation(**overrides):
    values = dict(
        concept="Leading Lines",
        canonical_unit="Photography Foundations",
        instructional_role="Composition example",
        provenance="advisory-model-observation",
    )
    values.update(overrides)
    return SemanticObservation(**values)


def _destination(**overrides):
    values = dict(
        drive_destination_ref="drive-folder:photography-assets",
        notion_destination_ref="notion-datasource:visual-asset-library",
        current=True,
    )
    values.update(overrides)
    return DestinationContext(**values)


def _plan(**overrides):
    values = dict(
        intake_reference="intake:abc123",
        duplicate_disposition="NO_DUPLICATE_FOUND",
        existing_identity=None,
        observation=_observation(),
        destination=_destination(),
    )
    values.update(overrides)
    return recommend_route(**values)


def test_high_confidence_photography_recommendation_is_deterministic():
    first = _plan()
    second = _plan()
    assert first == second
    assert first.state is RoutingState.RECOMMENDED
    assert first.concept == "Leading Lines"
    assert first.canonical_unit == "Photography Foundations"
    assert first.instructional_role == "Composition example"
    assert first.allowed_actions == (TeacherAction.ADD, TeacherAction.CHANGE, TeacherAction.SKIP)


def test_add_confirms_exact_plan_without_execution_authority():
    original = _plan()
    confirmed = apply_teacher_action(original, TeacherAction.ADD)
    assert confirmed.state is RoutingState.CONFIRMED
    assert confirmed.teacher_confirmed
    assert confirmed.concept == original.concept
    assert not confirmed.execution_authorized
    assert not confirmed.external_write_authorized
    assert not confirmed.approval_authorized
    assert not confirmed.classroom_readiness_authorized
    assert not confirmed.production_authorized


def test_change_preserves_advisory_and_teacher_correction_separately():
    original = _plan()
    correction = _observation(
        concept="Rule of Thirds",
        canonical_unit="Photography Foundations",
        instructional_role="Composition comparison",
        provenance="teacher-confirmed",
    )
    changed = apply_teacher_action(original, TeacherAction.CHANGE, correction=correction)
    assert changed.concept == "Rule of Thirds"
    assert changed.prior_advisory_concept == "Leading Lines"
    assert changed.semantic_provenance == "teacher-confirmed"
    assert changed.teacher_confirmed
    assert changed.state is RoutingState.RECOMMENDED


def test_skip_is_terminal_no_write():
    skipped = apply_teacher_action(_plan(), TeacherAction.SKIP)
    assert skipped.state is RoutingState.SKIPPED
    assert skipped.allowed_actions == ()
    assert not skipped.external_write_authorized


def test_exact_and_normalized_duplicates_use_existing_or_review():
    for disposition in ("EXACT_EXISTING", "NORMALIZED_EXISTING"):
        result = _plan(duplicate_disposition=disposition, existing_identity="asset:existing")
        assert result.state is RoutingState.REVIEW_REQUIRED
        assert result.allowed_actions == (TeacherAction.USE_EXISTING, TeacherAction.REVIEW)


def test_exact_duplicate_without_identity_fails_closed():
    result = _plan(duplicate_disposition="EXACT_EXISTING")
    assert result.state is RoutingState.REVIEW_REQUIRED
    assert "routing-existing-identity-missing" in result.reason_codes


def test_duplicate_manual_review_and_invalid_block_add():
    for disposition in ("MANUAL_REVIEW_REQUIRED", "INVALID"):
        result = _plan(duplicate_disposition=disposition)
        assert result.state is RoutingState.REVIEW_REQUIRED
        assert TeacherAction.ADD not in result.allowed_actions


def test_supplied_near_duplicate_never_silently_adds():
    result = _plan(duplicate_disposition="POSSIBLE_NEAR_DUPLICATE", existing_identity="asset:candidate")
    assert TeacherAction.ADD not in result.allowed_actions
    assert result.allowed_actions == (TeacherAction.USE_EXISTING, TeacherAction.CHANGE, TeacherAction.REVIEW)


def test_ambiguous_unit_or_concept_blocks_add():
    result = _plan(observation=_observation(canonical_unit=None, ambiguous=True))
    assert result.state is RoutingState.AMBIGUOUS
    assert TeacherAction.ADD not in result.allowed_actions


def test_stale_or_missing_destination_blocks_add():
    for destination in (
        _destination(current=False),
        _destination(drive_destination_ref=None),
        _destination(notion_destination_ref=None),
    ):
        result = _plan(destination=destination)
        assert result.state is RoutingState.DESTINATION_STALE
        assert TeacherAction.ADD not in result.allowed_actions


def test_privacy_or_provenance_concern_requires_review():
    result = _plan(observation=_observation(privacy_or_provenance_concern=True))
    assert result.state is RoutingState.REVIEW_REQUIRED
    assert result.allowed_actions == (TeacherAction.REVIEW, TeacherAction.SKIP)


def test_teacher_supplied_context_is_preserved_as_supplied_evidence():
    result = _plan(observation=_observation(provenance="teacher-supplied-context"))
    assert result.semantic_provenance == "teacher-supplied-context"
    assert not result.teacher_confirmed


def test_malformed_and_oversized_evidence_fails_closed():
    malformed = _plan(intake_reference="")
    oversized = _plan(observation=_observation(concept="x" * 257))
    assert malformed.state is RoutingState.REVIEW_REQUIRED
    assert oversized.state is RoutingState.REVIEW_REQUIRED
    assert TeacherAction.ADD not in malformed.allowed_actions
    assert TeacherAction.ADD not in oversized.allowed_actions


def test_no_identity_or_destination_is_invented():
    result = _plan(destination=_destination(drive_destination_ref=None, notion_destination_ref=None))
    assert result.existing_identity is None
    assert result.drive_destination_ref is None
    assert result.notion_destination_ref is None
    assert not hasattr(result, "asset_id")


def test_inputs_are_immutable_and_authority_is_always_false():
    observation = _observation()
    destination = _destination()
    result = recommend_route(
        intake_reference="intake:abc123",
        duplicate_disposition="NO_DUPLICATE_FOUND",
        existing_identity=None,
        observation=observation,
        destination=destination,
    )
    assert observation == _observation()
    assert destination == _destination()
    assert not result.execution_authorized
    assert not result.external_write_authorized
    assert not result.approval_authorized
    assert not result.classroom_readiness_authorized
    assert not result.production_authorized
