"""#4026: source-anchored Notion Writer relevance, not live lesson applicability.

All evidence is synthetic. Never use these tests to assert that LL-10 is
eligible, selected, or authorized for Notion/GitHub mutations.
"""
from dataclasses import replace

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeCandidate,
    CodingKnowledgeRequest,
    KnowledgeCurrentness,
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import (
    SELECTION_BASIS_VALUES,
    describe_selection_basis,
)
from agent_memory_context_manager.lesson_preflight import LessonRecordEvidence


REVISION = "2026-11-15T00:41:00.000Z"
SOURCE = ("https://github.com/Blummer92/agent-os/issues/4026",)
GUIDANCE = "After a Notion write, use an independent readback to verify the persisted revision."
HINTS = ("Notion writer", "persistence readback", "failure receipts")


def request(**changes):
    fields = dict(
        task_reference="PR #3988 Notion Writer readback repair",
        ecosystem_hints=("Python", "Notion"),
        language_hints=("Python",),
        capability_keywords=HINTS,
        target_path_hints=("scripts/agent_os_notion_lessons_write/runner.py",),
        specialized_knowledge_required=True,
    )
    fields.update(changes)
    return CodingKnowledgeRequest(**fields)


def candidate(identity="LL-TEST", **changes):
    fields = dict(
        knowledge_id=identity,
        source_system="notion-lessons-learned",
        source_revision=REVISION,
        currentness=KnowledgeCurrentness.CURRENT,
        name="Notion writer persistence readback",
        ecosystem="python",
        library_name=None,
        capability_kind="quality-assurance",
        keywords=("Notion",),
        use_when=(GUIDANCE,),
        canonical_github_refs=SOURCE,
        evidence_refs=(),
    )
    fields.update(changes)
    return CodingKnowledgeCandidate(**fields)


def test_exact_mechanism_match_requires_lesson_owned_title_guidance_and_controlled_tag():
    result = select_coding_knowledge(request(), (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.knowledge_refs == ("LL-TEST",)
    assert result.selected[0].reason_codes == ("notion-writer-readback-text-match",)
    assert result.canonical_github_refs == SOURCE


@pytest.mark.parametrize("hints", [
    (), ("Notion writer",), ("persistence readback",),
    ("Notion writer", "persistence readback"),
    ("Notion writer", "failure receipts"),
    ("testing",),
])
def test_partial_or_generic_request_hints_cannot_select(hints):
    result = select_coding_knowledge(request(capability_keywords=hints), (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()


@pytest.mark.parametrize("changes", [
    {"source_system": "repository"},
    {"keywords": ("Dashboard",)},
    {"ecosystem": "typescript"},
    {"name": "Workspace navigation"},
    {"name": "Notion dashboard layout"},
    {"use_when": ("A readback of a GitHub workflow proves the workflow finished.",)},
    {"use_when": ("A Notion workspace can display a writer's notes.",)},
    {"use_when": ("After a Notion write, trust the immediate response.",)},
    {"use_when": ("Unrelated Notion writer readback instructions.",)},
    {"use_when": ("After a Notion write, never use readback to verify persisted state.",)},
    {"use_when": ("After a Notion write, do not use readback to verify persisted state.",)},
    {"use_when": ("A Notion writer should not use independent readback to verify persisted changes.",)},
    {"use_when": ("A Notion writer must not use readback to verify persisted changes.",)},
    {"use_when": ("A Notion writer should not verify persisted changes with readback.",)},
    {"use_when": ("A Notion writer shouldn't use readback to verify persisted changes.",)},
    {"use_when": ("A Notion writer mustn't use readback to verify persisted changes.",)},
    {"use_when": ("A Notion writer can't use readback to verify persisted changes.",)},
    {"use_when": ("A Notion writer cannot use readback to verify persisted changes.",)},
    {"use_when": ("A Notion writer verifies persisted changes without readback.",)},
    {"use_when": ("A Notion writer should skip readback when verifying persisted changes.",)},
    {"use_when": ("A Notion writer is prohibited from using readback to verify persisted changes.",)},
])
def test_unrelated_or_incomplete_lesson_owned_mechanism_fails_closed(changes):
    result = select_coding_knowledge(request(), (candidate(**changes),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()


def test_existing_generic_notion_keyword_remains_generic_not_special():
    # Pre-existing CKR2 generic keyword matching is not changed by this patch.
    # It may itself be semantically weak; #4026 / #4054 own that policy.
    result = select_coding_knowledge(
        request(capability_keywords=("Notion",)), (candidate(),)
    )
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].reason_codes == ("ecosystem-capability-match",)


def test_task_prose_and_known_reference_alone_cannot_create_a_match():
    req = request(
        capability_keywords=(),
        known_knowledge_refs=("LL-10",),
        task_reference="Notion writer persistence readback and failure receipts",
    )
    result = select_coding_knowledge(req, (candidate("LL-10"),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.knowledge_refs == ()


@pytest.mark.parametrize("change", [
    {"currentness": KnowledgeCurrentness.STALE},
    {"currentness": KnowledgeCurrentness.UNVERIFIABLE},
    {"authority_conflict": True},
])
def test_stale_unverifiable_or_conflicting_provenance_still_blocks(change):
    result = select_coding_knowledge(request(), (candidate(**change),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.selected == ()


def test_missing_canonical_source_never_becomes_sufficient():
    result = select_coding_knowledge(
        request(canonical_rule_refs=SOURCE),
        (candidate(canonical_github_refs=()),),
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_duplicate_conflicting_revision_blocks_before_relevance():
    good = candidate()
    conflicting = replace(good, source_revision="2026-11-16T00:00:00.000Z")
    result = select_coding_knowledge(request(), (good, conflicting))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-identity-conflict",)


def test_distinct_candidate_budget_precedes_matching():
    result = select_coding_knowledge(
        request(), tuple(candidate(f"LL-{i}") for i in range(6))
    )
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("candidate-budget-exceeded",)


def test_selection_basis_exposes_a_generic_relevance_hypothesis_not_human_gold():
    lesson = LessonRecordEvidence(
        lesson_id="LL-TEST",
        source_revision=REVISION,
        title="Notion writer persistence readback",
        ecosystem="python",
        capability_kind="quality-assurance",
        status="Applied",
        surface_before_work=True,
        currentness=KnowledgeCurrentness.CURRENT,
        what_to_do_next_time=GUIDANCE,
        guardrail="Only use independent Notion write readback when the bound revision matches.",
        canonical_github_refs=SOURCE,
        evidence_refs=(),
        keywords=("Notion",),
    )
    result = describe_selection_basis(request(), [lesson], identity_route=False)
    assert (result.basis, result.best_bucket, result.tied_identities) == (
        "generic-unique", 2, 1
    )
    assert len(SELECTION_BASIS_VALUES) == 8


def test_positive_and_negative_cannot_be_promoted_from_metadata_only():
    metadata_only = candidate(
        name="Notion metadata configuration",
        use_when=("Tag Notion records after a quality-assurance test.",),
    )
    result = select_coding_knowledge(request(), (metadata_only,))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.knowledge_refs == ()


def test_permutation_of_distinct_matching_lessons_is_deterministic():
    choices = tuple(candidate(f"LL-{i}") for i in range(3))
    first = select_coding_knowledge(request(), choices)
    second = select_coding_knowledge(request(), tuple(reversed(choices)))
    assert first.to_json() == second.to_json()
    assert first.selected_count == 3
