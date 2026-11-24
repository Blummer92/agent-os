"""LL-95 discovery regression: catalog text and a synthetic candidate pool."""
from copy import deepcopy
from dataclasses import replace

import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    CodingKnowledgeRequest, KnowledgeCurrentness, SufficiencyStatus, select_coding_knowledge,
)
from agent_memory_context_manager.lesson_activation_bridge import _as_selection_candidate, normalize_lesson_row
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import orchestrate_lesson_retrieval

TITLE = "Preserve explicitly requested library coverage within lesson-ranking ties"
GUIDANCE = (
    "Within the same relevance bucket, preserve the widest coverage of explicitly "
    "requested libraries before truncating. Keep the existing deterministic order "
    "when coverage is equal."
)
GUARDRAIL = (
    "Never promote a lower relevance bucket or bypass provenance to gain coverage. "
    "Keep the existing candidate and selection limits. If reordering changes which "
    "lesson IDs make the cutoff, replay the original shortlist in its original order. "
    "Keep any prior refusal unless missing required-library coverage was the only reason."
)
REVISION = "2026-11-24T20:31:00.000Z"
TASKS = (
    ("Find why a tied shortlist drops the only result for a requested library.",
     ("lesson-selection", "library coverage")),
    ("Fix leap-day rounding in the school calendar.", ("date arithmetic", "calendar week rollover")),
    ("Fix a library coverage report that drops test files.", ("coverage reporting", "library coverage")),
    ("Fix lesson selection for expired records.", ("lesson-selection", "revision checking")),
)


def row(number=95, *, title=TITLE, guidance=GUIDANCE, surface=True):
    def rich(value, kind="rich_text"):
        return {"type": kind, kind: [{"plain_text": value}]}

    def selected(value):
        return {"type": "select", "select": {"name": value}}

    return {
        "object": "page", "id": f"fixture-{number}", "last_edited_time": REVISION,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": rich(title, "title"),
            "Status": selected("New"),
            "Surface Before Work?": {"type": "checkbox", "checkbox": surface},
            "Area": selected("Governance"),
            "Learning Type": selected("Testing lesson"),
            "Applies To": {"type": "multi_select", "multi_select": []},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/4026"},
            "What To Do Next Time": rich(guidance),
            "Guardrail": rich(GUARDRAIL),
        },
    }


def request(case=0, *, testing=False):
    task, hints = TASKS[case]
    return CodingKnowledgeRequest(
        task_reference=task, ecosystem_hints=("agent-os",), language_hints=("Python",),
        capability_keywords=(("testing",) if testing else ()) + hints,
        specialized_knowledge_required=True,
    )


def replay(req, population):
    return orchestrate_lesson_retrieval(
        req, execute_read=lambda _: {"results": population, "has_more": False, "next_cursor": None},
    )


@pytest.mark.parametrize("testing", [False, True])
@pytest.mark.parametrize("case", range(len(TASKS)))
def test_matched_requests_through_ckr11(case, testing):
    population = [
        row(i, title="Generic testing recommendation", guidance="Test failure behavior.")
        for i in range(1, 88)
    ] + [row()]
    result = replay(request(case, testing=testing), population)
    if case == 0:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.selected_lesson_ids == ("LL-95",)
        assert result.selection.selected[0].candidate.source_revision == REVISION
        assert result.retrieval_diagnostics["selection_basis"] == "rule-library-tie-coverage"
    else:
        assert "LL-95" not in result.selected_lesson_ids
        if testing:
            assert result.selection_reason_codes == ("generic-relevance-unverified",)


@pytest.mark.parametrize("case", [1, 2, 3])
def test_generic_testing_cannot_surface_mechanism_lesson_even_when_alone(case):
    assert replay(request(case, testing=True), [row()]).selected_lesson_ids == ()


@pytest.mark.parametrize(("title", "guidance"), [
    ("Preserve explicitly requested library coverage in a calendar report", GUIDANCE),
    ("Do not preserve explicitly requested library coverage within lesson-ranking ties", GUIDANCE),
    (TITLE, "Within the same relevance bucket, never preserve coverage before truncating."),
    (TITLE, "Within the same relevance bucket, preserve coverage of requested libraries "
            "before truncating only if that reduces library coverage."),
    (TITLE, "Quote the title and run all library coverage tests."),
    (TITLE, GUIDANCE + " Actually, never preserve coverage."),
])
def test_title_and_affirmative_guidance_are_required_even_with_testing(title, guidance):
    assert replay(request(testing=True), [row(title=title, guidance=guidance)]).selected_lesson_ids == ()


def test_identity_and_exact_spelling_are_not_required():
    result = replay(request(), [row(
        70, title="Maintain coverage for requested libraries within lesson ranking ties",
        guidance="Within a relevance bucket, maintain coverage across requested libraries "
                 "before cutting the shortlist.",
    )])
    assert result.selected_lesson_ids == ("LL-70",)
    assert result.authority_created is False


def test_natural_prose_alone_does_not_qualify_a_lesson():
    req = replace(request(), capability_keywords=())
    assert replay(req, [row()]).selected_lesson_ids == ()


def test_existing_generic_selection_for_unrelated_lesson_is_preserved():
    result = replay(request(1, testing=True), [
        row(11, title="Test calendar boundaries", guidance="Check the calendar week."),
    ])
    assert result.selected_lesson_ids == ("LL-11",)


def test_generic_ambiguity_is_not_overridden_for_independent_signals():
    others = []
    for i in range(1, 5):
        item = row(i, title="Other mechanism", guidance="Test shortlist behavior.")
        item["properties"]["Applies To"]["multi_select"] = [{"name": "lesson-selection"}]
        others.append(item)
    result = replay(request(testing=True), [*others, row()])
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selection_reason_codes == ("generic-relevance-unverified",)


def test_currentness_source_conflict_and_activation_holds():
    ordinary = row()
    missing_source = deepcopy(ordinary)
    missing_source["properties"]["Source Link"]["url"] = None
    result = replay(request(), [missing_source])
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes == ("unverifiable-relevant-candidate",)
    assert replay(request(), [row(surface=False)]).selected_lesson_ids == ()

    duplicate = deepcopy(ordinary)
    duplicate["last_edited_time"] = "2026-11-23T20:31:00.000Z"
    conflict = replay(request(), [ordinary, duplicate])
    assert conflict.selected_lesson_ids == ()
    assert conflict.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW

    candidate = _as_selection_candidate(normalize_lesson_row(ordinary))
    for changed in (
        replace(candidate, currentness=KnowledgeCurrentness.STALE),
        replace(candidate, authority_conflict=True),
    ):
        result = select_coding_knowledge(request(), (changed,))
        assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
        assert not result.selected


def test_known_id_does_not_admit_an_unrelated_lesson():
    req = replace(request(1, testing=True), known_knowledge_refs=("LL-95",))
    assert replay(req, [row()]).selected_lesson_ids == ()


def test_lookalike_from_another_source_does_not_get_mechanism_match():
    candidate = _as_selection_candidate(normalize_lesson_row(row()))
    result = select_coding_knowledge(
        request(testing=True), (replace(candidate, source_system="local-notes"),),
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert not result.selected
