from visual_asset_routing import (
    DestinationContext,
    RoutingState,
    SemanticObservation,
    TeacherAction,
    apply_teacher_action,
    recommend_route,
)


def _observation(**overrides):
    values = dict(concept="Leading Lines", canonical_unit="Photography Foundations", instructional_role="Composition example", provenance="advisory-model-observation")
    values.update(overrides)
    return SemanticObservation(**values)


def _destination(**overrides):
    values = dict(drive_destination_ref="drive-folder:photography-assets", notion_destination_ref="notion-datasource:visual-asset-library", current=True)
    values.update(overrides)
    return DestinationContext(**values)


def _plan(**overrides):
    values = dict(intake_reference="intake:abc123", duplicate_disposition="NO_DUPLICATE_FOUND", existing_identity=None, observation=_observation(), destination=_destination())
    values.update(overrides)
    return recommend_route(**values)


def test_recommendation_is_deterministic_and_authority_false():
    first = _plan()
    assert first == _plan()
    assert first.state is RoutingState.RECOMMENDED
    assert first.allowed_actions == (TeacherAction.ADD, TeacherAction.CHANGE, TeacherAction.SKIP)
    assert not first.execution_authorized and not first.external_write_authorized
    assert not first.approval_authorized and not first.classroom_readiness_authorized and not first.production_authorized


def test_add_confirms_and_terminal_plan_stays_terminal():
    confirmed = apply_teacher_action(_plan(), TeacherAction.ADD)
    assert confirmed.state is RoutingState.CONFIRMED and confirmed.teacher_confirmed
    assert apply_teacher_action(confirmed, TeacherAction.REVIEW) == confirmed


def test_skip_is_terminal_no_write():
    skipped = apply_teacher_action(_plan(), TeacherAction.SKIP)
    assert skipped.state is RoutingState.SKIPPED and skipped.allowed_actions == ()
    assert apply_teacher_action(skipped, TeacherAction.REVIEW) == skipped


def test_change_preserves_advisory_and_recomputes_normal_route():
    original = _plan()
    correction = _observation(concept="Rule of Thirds", instructional_role="Composition comparison", provenance="teacher-confirmed")
    changed = apply_teacher_action(original, TeacherAction.CHANGE, correction=correction)
    assert changed.concept == "Rule of Thirds"
    assert changed.prior_advisory_concept == "Leading Lines"
    assert changed.semantic_provenance == "teacher-confirmed" and changed.teacher_confirmed
    assert changed.state is RoutingState.RECOMMENDED


def test_change_does_not_bypass_stale_destination():
    stale = _plan(destination=_destination(current=False))
    changed = apply_teacher_action(stale, TeacherAction.CHANGE, correction=_observation(concept="Rule of Thirds"))
    assert changed.state is RoutingState.DESTINATION_STALE
    assert TeacherAction.ADD not in changed.allowed_actions


def test_change_does_not_bypass_near_duplicate_restriction():
    near = _plan(duplicate_disposition="POSSIBLE_NEAR_DUPLICATE", existing_identity="asset:candidate")
    changed = apply_teacher_action(near, TeacherAction.KEEP_NEW)
    assert changed.state is RoutingState.CONFIRMED
    assert changed.reason_codes == ("routing-keep-new-selected",)


def test_exact_and_normalized_duplicates_use_existing_or_review():
    for disposition in ("EXACT_EXISTING", "NORMALIZED_EXISTING"):
        result = _plan(duplicate_disposition=disposition, existing_identity="asset:existing")
        assert result.allowed_actions == (TeacherAction.USE_EXISTING, TeacherAction.REVIEW)
        selected = apply_teacher_action(result, TeacherAction.USE_EXISTING)
        assert selected.state is RoutingState.CONFIRMED
        assert selected.reason_codes == ("routing-use-existing-selected",)
        assert not selected.execution_authorized


def test_exact_duplicate_without_identity_fails_closed():
    result = _plan(duplicate_disposition="EXACT_EXISTING")
    assert result.state is RoutingState.REVIEW_REQUIRED
    assert TeacherAction.USE_EXISTING not in result.allowed_actions


def test_near_duplicate_without_identity_never_exposes_use_existing():
    result = _plan(duplicate_disposition="POSSIBLE_NEAR_DUPLICATE")
    assert result.allowed_actions == (TeacherAction.KEEP_NEW, TeacherAction.REVIEW)


def test_near_duplicate_with_identity_exposes_bounded_choices():
    result = _plan(duplicate_disposition="POSSIBLE_NEAR_DUPLICATE", existing_identity="asset:candidate")
    assert result.allowed_actions == (TeacherAction.USE_EXISTING, TeacherAction.KEEP_NEW, TeacherAction.REVIEW)
    assert TeacherAction.ADD not in result.allowed_actions


def test_duplicate_manual_review_and_invalid_block_add():
    for disposition in ("MANUAL_REVIEW_REQUIRED", "INVALID"):
        result = _plan(duplicate_disposition=disposition)
        assert result.state is RoutingState.REVIEW_REQUIRED
        assert TeacherAction.ADD not in result.allowed_actions


def test_unhashable_or_unsupported_duplicate_evidence_fails_closed():
    for disposition in ([], {}, "UNKNOWN"):
        result = _plan(duplicate_disposition=disposition)
        assert result.state is RoutingState.REVIEW_REQUIRED
        assert TeacherAction.ADD not in result.allowed_actions


def test_ambiguity_privacy_and_destination_fail_closed():
    ambiguous = _plan(observation=_observation(canonical_unit=None, ambiguous=True))
    privacy = _plan(observation=_observation(privacy_or_provenance_concern=True))
    assert ambiguous.state is RoutingState.AMBIGUOUS
    assert privacy.state is RoutingState.REVIEW_REQUIRED
    for destination in (_destination(current=False), _destination(drive_destination_ref=None), _destination(notion_destination_ref=None)):
        assert _plan(destination=destination).state is RoutingState.DESTINATION_STALE


def test_malformed_and_oversized_evidence_fails_closed():
    assert _plan(intake_reference="").state is RoutingState.REVIEW_REQUIRED
    assert _plan(observation=_observation(concept="x" * 257)).state is RoutingState.REVIEW_REQUIRED


def test_no_identity_or_destination_is_invented_and_inputs_immutable():
    observation = _observation()
    destination = _destination(drive_destination_ref=None, notion_destination_ref=None)
    result = _plan(observation=observation, destination=destination)
    assert result.existing_identity is None and result.drive_destination_ref is None and result.notion_destination_ref is None
    assert not hasattr(result, "asset_id")
    assert observation == _observation()
    assert destination == _destination(drive_destination_ref=None, notion_destination_ref=None)
