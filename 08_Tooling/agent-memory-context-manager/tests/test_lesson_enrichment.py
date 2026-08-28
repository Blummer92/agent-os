from agent_memory_context_manager.coding_knowledge_selection import KnowledgeCurrentness
from agent_memory_context_manager.lesson_enrichment import (
    CurrentLessonEvidence, EvidenceEffect, LessonEnrichmentDisposition,
    RelatedGitHubEvidence, evaluate_lesson_enrichment,
)


def lesson(**overrides):
    values = dict(
        lesson_id="lesson:one", source_revision="pr:1", title="Validate exact head",
        ecosystem="python", capability_kind="validation", what_happened="A stale head was trusted.",
        what_to_do_next_time="Validate the exact current head.", guardrail="Bind evidence to the current SHA.",
        canonical_github_refs=("issue:1",), evidence_refs=("pr:1",), origin_refs=("issue:1",),
        keywords=("validation", "exact-head"), currentness=KnowledgeCurrentness.CURRENT,
    )
    values.update(overrides)
    return CurrentLessonEvidence(**values)


def evidence(effect, **overrides):
    values = dict(reference="pr:2", effect=effect, canonical_github_refs=("issue:2",), evidence_refs=("pr:2",))
    values.update(overrides)
    return RelatedGitHubEvidence(**values)


def test_confirming_evidence_preserves_guidance_and_adds_provenance():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.CONFIRMS),))
    assert result.disposition is LessonEnrichmentDisposition.UNCHANGED
    assert result.proposal.what_to_do_next_time == "Validate the exact current head."
    assert result.proposal.canonical_github_refs == ("issue:1", "issue:2")
    assert result.proposal.new_supporting_refs == ("pr:2",)


def test_root_cause_enriches_existing_lesson():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.IMPROVES_ROOT_CAUSE, revised_what_happened="The status belonged to an obsolete SHA."),))
    assert result.disposition is LessonEnrichmentDisposition.ENRICH_EXISTING
    assert result.proposal.what_happened == "The status belonged to an obsolete SHA."


def test_new_guardrail_enriches_existing_lesson():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.ADDS_GUARDRAIL, revised_guardrail="Require exact-head status and branch currency."),))
    assert result.disposition is LessonEnrichmentDisposition.ENRICH_EXISTING
    assert result.proposal.guardrail == "Require exact-head status and branch currency."


def test_compatible_lessons_consolidate_and_reduce_retrieval_records():
    other = lesson(lesson_id="lesson:two", source_revision="pr:3", canonical_github_refs=("issue:3",), evidence_refs=("pr:3",), origin_refs=("issue:3",))
    result = evaluate_lesson_enrichment(lesson(), (), (other,))
    assert result.disposition is LessonEnrichmentDisposition.CONSOLIDATE_COMPATIBLE
    assert result.lessons_consolidated == 1
    assert result.estimated_retrieval_records_before == 2
    assert result.after_current_synthesis_count == 1
    assert result.proposal.consolidated_from == ("lesson:two",)
    assert result.proposal.origin_refs == ("issue:1", "issue:3")


def test_different_guardrail_remains_distinct():
    other = lesson(lesson_id="lesson:two", guardrail="Always rerun everything.")
    result = evaluate_lesson_enrichment(lesson(), (), (other,))
    assert result.disposition is LessonEnrichmentDisposition.DISTINCT_LESSON


def test_explicit_distinct_cause_remains_distinct():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.DISTINCT_CAUSE),))
    assert result.disposition is LessonEnrichmentDisposition.DISTINCT_LESSON


def test_supersession_marks_old_synthesis_stale_and_preserves_identity():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.SUPERSEDES),))
    assert result.disposition is LessonEnrichmentDisposition.SUPERSEDE_EXISTING
    assert result.proposal.currentness is KnowledgeCurrentness.STALE
    assert result.proposal.surface_before_work is False
    assert result.proposal.supersedes == ("lesson:one",)


def test_contradictory_evidence_routes_to_manual_review():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.CONTRADICTS),))
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW
    assert result.manual_review_count == 1


def test_incidental_relation_is_insufficient():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.INCIDENTAL),))
    assert result.disposition is LessonEnrichmentDisposition.INSUFFICIENT_EVIDENCE


def test_no_new_evidence_is_unchanged_without_proposal():
    result = evaluate_lesson_enrichment(lesson(), ())
    assert result.disposition is LessonEnrichmentDisposition.UNCHANGED
    assert result.proposal is None


def test_authority_conflict_fails_closed():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.CONFIRMS, authority_conflict=True),))
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW


def test_stale_base_lesson_fails_closed():
    result = evaluate_lesson_enrichment(lesson(currentness=KnowledgeCurrentness.STALE), (evidence(EvidenceEffect.CONFIRMS),))
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW


def test_mixed_supersession_and_rewrite_fails_closed():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.SUPERSEDES), evidence(EvidenceEffect.ADDS_GUARDRAIL, reference="pr:3")))
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW


def test_consolidation_with_material_rewrite_fails_closed():
    other = lesson(lesson_id="lesson:two")
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.ADDS_GUARDRAIL),), (other,))
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW


def test_evidence_budget_fails_closed():
    items = tuple(evidence(EvidenceEffect.CONFIRMS, reference=f"pr:{i}") for i in range(9))
    result = evaluate_lesson_enrichment(lesson(), items)
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW


def test_reference_budget_fails_closed():
    base = lesson(canonical_github_refs=tuple(f"issue:{i}" for i in range(20)))
    result = evaluate_lesson_enrichment(base, (evidence(EvidenceEffect.CONFIRMS, canonical_github_refs=("issue:new",)),))
    assert result.disposition is LessonEnrichmentDisposition.MANUAL_REVIEW


def test_revision_is_non_authorizing_and_side_effect_free():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.CONFIRMS),))
    proposal = result.proposal
    assert proposal.authority_created is False
    assert proposal.side_effects_performed is False
    assert proposal.notion_write_performed is False
    assert proposal.github_external_mutation_performed is False
    assert proposal.publication_or_revision_authorized is False


def test_current_synthesis_projects_into_existing_ckr6_record_type():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.ADDS_GUARDRAIL, revised_guardrail="Check exact-head and branch currency."),))
    record = result.proposal.to_lesson_record_evidence()
    assert record.lesson_id == "lesson:one"
    assert record.status == "Applied"
    assert record.guardrail == "Check exact-head and branch currency."
    assert record.canonical_github_refs == ("issue:1", "issue:2")


def test_superseded_synthesis_projects_as_non_surfaceable_stale_record():
    result = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.SUPERSEDES),))
    record = result.proposal.to_lesson_record_evidence()
    assert record.currentness is KnowledgeCurrentness.STALE
    assert record.surface_before_work is False


def test_identical_inputs_are_deterministic():
    first = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.CONFIRMS),))
    second = evaluate_lesson_enrichment(lesson(), (evidence(EvidenceEffect.CONFIRMS),))
    assert first == second
    assert first.proposal.to_dict() == second.proposal.to_dict()
