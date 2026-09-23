import json

import pytest

from agent_memory_context_manager import (
    CodingKnowledgeCandidate,
    ExistingLesson,
    FailureKind,
    FailureObservation,
    KnowledgeCurrentness,
    LessonDisposition,
    MAX_EXISTING_LESSONS,
    evaluate_coding_failure,
)


def observation(**overrides):
    data = dict(
        source_reference="issue:#1352/run:1",
        failure_kind=FailureKind.CODE_DEFECT,
        failure_signature="route decision accepted stale authorization",
        ecosystem="python",
        capability_kind="authorization-routing",
        library_name=None,
        lesson_summary="Recheck authorization currentness before routing",
        what_happened="A stale authorization result was reused after the execution head changed.",
        what_to_do_next_time="Reacquire authorization evidence after an exact-head change.",
        guardrail="Never reuse head-bound authorization evidence after the head advances.",
        learning_type="Testing lesson",
        severity="High",
        owner_agent="GitHub Service Agent",
        canonical_github_refs=("01_Shared_Standards/github/safe-implementation-lane.md",),
        evidence_refs=("issue:#1352/test:authorization-currentness",),
        future_use_hints=("authorization", "routing"),
        currentness=KnowledgeCurrentness.CURRENT,
        reusable_rule=True,
        authority_conflict=False,
    )
    data.update(overrides)
    return FailureObservation(**data)


def existing_from(
    obs,
    *,
    recurrence_count=2,
    guardrail=None,
    next_time=None,
    knowledge_id=None,
    currentness=KnowledgeCurrentness.CURRENT,
    authority_conflict=False,
):
    guardrail = guardrail or obs.guardrail
    next_time = next_time or obs.what_to_do_next_time
    probe = ExistingLesson(
        knowledge_id="placeholder",
        failure_kind=obs.failure_kind,
        failure_signature=obs.failure_signature,
        ecosystem=obs.ecosystem,
        capability_kind=obs.capability_kind,
        library_name=obs.library_name,
        lesson_summary=obs.lesson_summary,
        what_to_do_next_time=next_time,
        guardrail=guardrail,
        recurrence_count=recurrence_count,
        currentness=currentness,
        canonical_github_refs=obs.canonical_github_refs,
        evidence_refs=("issue:#1200/pr:1201",),
        authority_conflict=authority_conflict,
    )
    return ExistingLesson(
        knowledge_id=knowledge_id or probe.computed_knowledge_id(),
        failure_kind=probe.failure_kind,
        failure_signature=probe.failure_signature,
        ecosystem=probe.ecosystem,
        capability_kind=probe.capability_kind,
        library_name=probe.library_name,
        lesson_summary=probe.lesson_summary,
        what_to_do_next_time=probe.what_to_do_next_time,
        guardrail=probe.guardrail,
        recurrence_count=probe.recurrence_count,
        currentness=probe.currentness,
        canonical_github_refs=probe.canonical_github_refs,
        evidence_refs=probe.evidence_refs,
        authority_conflict=probe.authority_conflict,
    )


def test_reusable_failure_creates_deterministic_candidate():
    result = evaluate_coding_failure(observation())
    assert result.disposition is LessonDisposition.REUSABLE_NEW
    assert result.lesson_identity.startswith("lesson:sha256:")
    assert result.proposal.operation == "create"


def test_trivial_error_is_non_reusable():
    result = evaluate_coding_failure(observation(failure_kind=FailureKind.TRIVIAL))
    assert result.disposition is LessonDisposition.NON_REUSABLE
    assert result.proposal is None


def test_transient_environment_failure_is_not_durable():
    result = evaluate_coding_failure(
        observation(failure_kind=FailureKind.TRANSIENT_ENVIRONMENT)
    )
    assert result.disposition is LessonDisposition.NON_REUSABLE


def test_flaky_infrastructure_noise_is_not_durable():
    result = evaluate_coding_failure(
        observation(failure_kind=FailureKind.FLAKY_INFRASTRUCTURE)
    )
    assert result.disposition is LessonDisposition.NON_REUSABLE


def test_reusable_human_correction_produces_candidate_with_provenance():
    result = evaluate_coding_failure(
        observation(failure_kind=FailureKind.HUMAN_CORRECTION)
    )
    assert result.disposition is LessonDisposition.REUSABLE_NEW
    assert result.proposal.source_reference == "issue:#1352/run:1"
    assert result.proposal.evidence_refs == (
        "issue:#1352/test:authorization-currentness",
    )


def test_known_identity_becomes_recurrence_without_duplicate_create():
    obs = observation()
    result = evaluate_coding_failure(obs, (existing_from(obs, recurrence_count=3),))
    assert result.disposition is LessonDisposition.REUSABLE_RECURRENCE
    assert result.proposal.operation == "increment-recurrence"
    assert result.proposal.proposed_recurrence_count == 4


def test_materially_different_guardrail_stays_distinct():
    obs = observation()
    existing = existing_from(
        obs, guardrail="Always pin authorization to the issue number."
    )
    result = evaluate_coding_failure(obs, (existing,))
    assert result.disposition is LessonDisposition.REUSABLE_NEW
    assert result.reason_codes == ("new-materially-distinct-lesson",)


def test_stored_identity_conflict_fails_closed():
    obs = observation()
    valid = existing_from(obs)
    conflicting = ExistingLesson(
        knowledge_id=valid.knowledge_id,
        failure_kind=valid.failure_kind,
        failure_signature=valid.failure_signature,
        ecosystem=valid.ecosystem,
        capability_kind=valid.capability_kind,
        library_name=valid.library_name,
        lesson_summary=valid.lesson_summary,
        what_to_do_next_time=valid.what_to_do_next_time,
        guardrail="Different guardrail that changes the computed identity.",
        recurrence_count=1,
        currentness=valid.currentness,
        canonical_github_refs=valid.canonical_github_refs,
        evidence_refs=valid.evidence_refs,
    )
    result = evaluate_coding_failure(obs, (conflicting,))
    assert result.disposition is LessonDisposition.MANUAL_REVIEW
    assert result.reason_codes == ("existing-identity-conflict",)


def test_multiple_related_variants_are_ambiguous():
    obs = observation()
    one = existing_from(obs, guardrail="Guardrail one")
    two = existing_from(obs, guardrail="Guardrail two")
    result = evaluate_coding_failure(obs, (one, two))
    assert result.disposition is LessonDisposition.MANUAL_REVIEW
    assert result.reason_codes == ("ambiguous-related-lessons",)


def test_missing_reusable_guidance_is_insufficient():
    result = evaluate_coding_failure(observation(guardrail=None))
    assert result.disposition is LessonDisposition.INSUFFICIENT_EVIDENCE


def test_stale_source_evidence_cannot_surface():
    result = evaluate_coding_failure(
        observation(currentness=KnowledgeCurrentness.STALE)
    )
    assert result.disposition is LessonDisposition.MANUAL_REVIEW
    assert result.to_coding_knowledge_candidate() is None


def test_github_authority_conflict_wins():
    result = evaluate_coding_failure(observation(authority_conflict=True))
    assert result.disposition is LessonDisposition.MANUAL_REVIEW
    assert result.reason_codes == ("canonical-authority-conflict",)


def test_publication_proposal_preserves_refs():
    result = evaluate_coding_failure(observation())
    assert result.proposal.canonical_github_refs == (
        "01_Shared_Standards/github/safe-implementation-lane.md",
    )
    assert result.proposal.evidence_refs == (
        "issue:#1352/test:authorization-currentness",
    )


def test_publication_proposal_is_authority_false_and_side_effect_free():
    result = evaluate_coding_failure(observation())
    proposal = result.proposal
    assert proposal.authority_created is False
    assert proposal.side_effects_performed is False
    assert proposal.notion_write_performed is False
    assert proposal.github_write_performed is False
    assert proposal.publication_authorized is False
    assert result.publication_authorized is False


def test_identical_inputs_are_byte_deterministic():
    one = evaluate_coding_failure(observation()).to_json()
    two = evaluate_coding_failure(observation()).to_json()
    assert one == two
    assert json.loads(one)["disposition"] == "reusable-new"


def test_oversized_existing_lesson_collection_fails_closed():
    obs = observation()
    entries = tuple(
        existing_from(obs, guardrail=f"guardrail {index}")
        for index in range(MAX_EXISTING_LESSONS + 1)
    )
    result = evaluate_coding_failure(obs, entries)
    assert result.disposition is LessonDisposition.MANUAL_REVIEW
    assert result.reason_codes == ("existing-lesson-budget-exceeded",)


def test_raw_mapping_cannot_enter_observation_contract():
    with pytest.raises(TypeError):
        evaluate_coding_failure({"raw_log": "..."})


def test_unknown_executable_payload_field_is_rejected():
    obs = observation()
    values = {name: getattr(obs, name) for name in obs.__dataclass_fields__}
    values["raw_test_body"] = "def test_x(): pass"
    with pytest.raises(TypeError):
        FailureObservation(**values)


def test_current_qualified_lesson_projects_to_ckr2_candidate():
    result = evaluate_coding_failure(observation())
    candidate = result.to_coding_knowledge_candidate()
    assert isinstance(candidate, CodingKnowledgeCandidate)
    assert candidate.knowledge_id == result.lesson_identity
    assert candidate.source_system == "lesson-publication-proposal"
    assert candidate.currentness is KnowledgeCurrentness.CURRENT
    assert candidate.capability_kind == "authorization-routing"


def test_no_future_use_hints_does_not_surface():
    result = evaluate_coding_failure(observation(future_use_hints=()))
    assert result.disposition is LessonDisposition.REUSABLE_NEW
    assert result.proposal.surface_before_work is False
    assert result.to_coding_knowledge_candidate() is None


def test_non_reusable_result_never_projects_to_ckr2():
    result = evaluate_coding_failure(observation(failure_kind=FailureKind.ONE_OFF))
    assert result.to_coding_knowledge_candidate() is None


def test_existing_stale_recurrence_fails_closed():
    obs = observation()
    result = evaluate_coding_failure(
        obs,
        (existing_from(obs, currentness=KnowledgeCurrentness.STALE),),
    )
    assert result.disposition is LessonDisposition.MANUAL_REVIEW
    assert result.to_coding_knowledge_candidate() is None


def test_missing_canonical_ref_is_insufficient():
    result = evaluate_coding_failure(observation(canonical_github_refs=()))
    assert result.disposition is LessonDisposition.INSUFFICIENT_EVIDENCE


def test_missing_evidence_ref_is_insufficient():
    result = evaluate_coding_failure(observation(evidence_refs=()))
    assert result.disposition is LessonDisposition.INSUFFICIENT_EVIDENCE


def test_reusable_flag_false_prevents_persistence():
    result = evaluate_coding_failure(observation(reusable_rule=False))
    assert result.disposition is LessonDisposition.NON_REUSABLE


def test_already_canonical_failure_is_not_duplicated_as_memory():
    result = evaluate_coding_failure(
        observation(failure_kind=FailureKind.ALREADY_CANONICAL)
    )
    assert result.disposition is LessonDisposition.NON_REUSABLE


def test_multiline_raw_log_like_detail_is_rejected():
    with pytest.raises(ValueError):
        observation(what_happened="Traceback (most recent call last):\nline 2")


def test_authority_flags_cannot_be_injected_into_result():
    result = evaluate_coding_failure(observation())
    with pytest.raises(TypeError):
        type(result)(
            disposition=result.disposition,
            reason_codes=result.reason_codes,
            lesson_identity=result.lesson_identity,
            core_identity=result.core_identity,
            proposal=result.proposal,
            authority_created=True,
        )
