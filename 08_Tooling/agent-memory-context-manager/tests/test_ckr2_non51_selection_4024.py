"""#4024: tests-only, synthetic CKR2 LL-51 relevance controls.

These are selector contracts on an immutable fixture, not live Notion,
independent human relevance labels, or permission to merge/activate lessons.
The unrelated packaging request never contains CKR6/mutation vocabulary.
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
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus

SOURCE = "https://github.com/Blummer92/agent-os/issues/4024"
REVISION = "2026-11-15T02:52:00.000Z"
PACKAGING_TASK = (
    "Repair an isolated offline wheelhouse that omitted the navigation-registry "
    "distribution, preserving dependency closure and import provenance."
)
PACKAGING_HINTS = (
    "offline Python wheelhouse",
    "navigation registry package",
    "isolated pip installation",
)
MUTATION_TASK = "Investigate the CKR6 mutation boundary and exact-head admission."


def request(task=PACKAGING_TASK, **overrides):
    values = dict(
        task_reference=task,
        ecosystem_hints=("agent-os",),
        language_hints=("python",),
        capability_keywords=PACKAGING_HINTS,
        target_path_hints=("08_Tooling/agent-os-navigation-registry",),
        specialized_knowledge_required=True,
    )
    values.update(overrides)
    return CodingKnowledgeRequest(**values)


def candidate(lesson_id="LL-51", **overrides):
    values = dict(
        knowledge_id=lesson_id,
        source_system="notion-lessons-learned",
        source_revision=REVISION,
        currentness=KnowledgeCurrentness.CURRENT,
        name="CKR6 mutation boundary must fail closed",
        ecosystem="python",
        library_name=None,
        capability_kind="testing",
        keywords=(),
        use_when=("Revalidate CKR6 mutation boundary admission on the exact head.",),
        canonical_github_refs=(SOURCE,),
    )
    values.update(overrides)
    return CodingKnowledgeCandidate(**values)


def _rich(value, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": value}]}


def row(lesson_id=51, *, source=SOURCE, revision=REVISION,
        status="Applied", surface=True, title="CKR6 mutation boundary must fail closed",
        guidance="Revalidate CKR6 mutation boundary admission on the exact head."):
    return {
        "object": "page",
        "id": f"fixture-{lesson_id}",
        "url": f"https://www.notion.so/fixture-{lesson_id}",
        "last_edited_time": revision,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": lesson_id}},
            "Lesson Learned": _rich(title, "title"),
            "Status": {"type": "select", "select": {"name": status}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": surface},
            "Area": {"type": "select", "select": {"name": "Testing"}},
            "Learning Type": {"type": "select", "select": {"name": "Testing lesson"}},
            "Applies To": {"type": "multi_select", "multi_select": []},
            "Source Link": {"type": "url", "url": source},
            "Guardrail": _rich("Do not bypass currentness or provenance."),
            "What To Do Next Time": _rich(guidance),
        },
    }


def reader(rows, *, pages=None):
    def read(query):
        if pages is not None:
            return pages[query.get("start_cursor")]
        return {"results": list(rows), "has_more": False, "next_cursor": None}
    return read


def test_unrelated_packaging_request_does_not_select_ll51():
    result = select_coding_knowledge(request(), (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()
    assert result.reason_codes == ("no-relevant-candidate",)


def test_unrelated_packaging_bridge_returns_no_relevant_signal():
    result = orchestrate_lesson_activation(request(), execute_read=reader([row()]))
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert "no-relevant-candidate" in result.selection_reason_codes
    assert result.selected_count == 0
    assert not result.notion_write_performed and not result.github_write_performed


@pytest.mark.parametrize("irrelevant_path", [
    "docs/meeting-notes.md",
    "src/teacher-os/lesson-plan.py",
])
def test_irrelevant_path_does_not_change_negative_selection(irrelevant_path):
    original = select_coding_knowledge(request(), (candidate(),))
    altered = select_coding_knowledge(
        request(target_path_hints=("08_Tooling/agent-os-navigation-registry", irrelevant_path)),
        (candidate(),),
    )
    assert original.selected == altered.selected == ()
    assert original.sufficiency_status == altered.sufficiency_status


def test_relevant_mutation_boundary_selects_current_ll51():
    req = request(
        task=MUTATION_TASK,
        capability_keywords=("ckr6 mutation boundary",),
        target_path_hints=(),
    )
    result = select_coding_knowledge(req, (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert tuple(x.candidate.knowledge_id for x in result.selected) == ("LL-51",)
    assert result.selected[0].reason_codes == ("verified-ckr6-mutation-context-match",)
    assert result.selected[0].candidate.source_revision == REVISION


def test_relevant_mutation_boundary_bridge_preserves_provenance():
    req = request(
        task=MUTATION_TASK,
        capability_keywords=("ckr6 mutation boundary",),
        target_path_hints=(),
    )
    result = orchestrate_lesson_activation(req, execute_read=reader([row()]))
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-51",)
    assert SOURCE in result.canonical_github_refs
    assert result.candidate_count <= 5 and result.selected_count <= 3


@pytest.mark.parametrize("override,expected", [
    ({"currentness": KnowledgeCurrentness.STALE}, "stale-relevant-candidate"),
    ({"currentness": KnowledgeCurrentness.UNVERIFIABLE, "canonical_github_refs": ()},
     "unverifiable-relevant-candidate"),
    ({"authority_conflict": True}, "canonical-authority-conflict"),
])
def test_relevant_candidate_provenance_fail_closed(override, expected):
    req = request(task=MUTATION_TASK, capability_keywords=("ckr6 mutation boundary",))
    result = select_coding_knowledge(req, (candidate(**override),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.selected == ()
    assert result.reason_codes == (expected,)


def test_conflicting_duplicate_revision_fails_closed():
    req = request(task=MUTATION_TASK, capability_keywords=("ckr6 mutation boundary",))
    original = candidate()
    conflicting = replace(original, source_revision="2026-11-16T00:00:00.000Z")
    result = select_coding_knowledge(req, (original, conflicting))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-identity-conflict",)
    assert result.selected == ()


@pytest.mark.parametrize("malformation", [
    {"last_edited_time": None},
    {"properties": None},
    {"object": "database"},
])
def test_malformed_provider_row_never_selects_ll51(malformation):
    damaged = row()
    damaged.update(malformation)
    req = request(task=MUTATION_TASK, capability_keywords=("ckr6 mutation boundary",))
    result = orchestrate_lesson_activation(req, execute_read=reader([damaged]))
    assert "LL-51" not in result.selected_lesson_ids
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT


def test_incomplete_pagination_cannot_return_partial_positive():
    req = request(task=MUTATION_TASK, capability_keywords=("ckr6 mutation boundary",))
    def incomplete(_query):
        return {"results": [row()], "has_more": True, "next_cursor": None}
    with pytest.raises(Exception, match="cursor"):
        orchestrate_lesson_activation(req, execute_read=incomplete)


def test_unrelated_generic_testing_hint_is_not_evidence_of_applicability():
    # Deliberately characterize a known limitation without changing the
    # production selector or asserting a policy that has not been approved.
    req = request(capability_keywords=("testing",), ecosystem_hints=("python",))
    result = select_coding_knowledge(req, (candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert tuple(x.candidate.knowledge_id for x in result.selected) == ("LL-51",)
    # This is a negative relevance finding, NOT a positive accuracy verdict.


def test_negative_and_positive_selection_are_order_invariant():
    unrelated = request()
    relevant = request(task=MUTATION_TASK, capability_keywords=("ckr6 mutation boundary",))
    pool = (candidate(), candidate("LL-10", name="Other unrelated testing lesson"))
    for req in (unrelated, relevant):
        forward = select_coding_knowledge(req, pool)
        backward = select_coding_knowledge(req, pool[::-1])
        assert tuple(x.candidate.knowledge_id for x in forward.selected) == tuple(
            x.candidate.knowledge_id for x in backward.selected
        )
        assert forward.sufficiency_status == backward.sufficiency_status
