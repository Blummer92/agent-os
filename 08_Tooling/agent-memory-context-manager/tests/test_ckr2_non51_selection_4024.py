"""#4024: LL-51 selection negative/positive controls on the production CKR11 path.

The LL-51 fixture mirrors source-adjudicated fields captured on 2026-11-20
(source: #1362 and the frozen PR #4067 QA archive). It is still an offline
snapshot, not a live Notion read or independently human-adjudicated gold.
No fixture asserts that broad keyword selection means task applicability.
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
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

SOURCE = "https://github.com/Blummer92/agent-os/issues/1362"
REVISION = "2026-11-15T02:52:00.000Z"
TITLE = (
    "Failed repair attempts must re-enter CKR6 Lessons Learned preflight "
    "before another repair hypothesis"
)
GUIDANCE = (
    "Every failed implementation or repair attempt is a mandatory re-entry trigger: "
    "preserve the failed hypothesis and durable checkpoint, record any side defect, "
    "rerun CKR6 material-use planning, consume only bounded relevant Lessons Learned, "
    "record consumed/not-material/unavailable, reacquire GitHub truth, then form the "
    "next hypothesis. Continue the branch/PR lineage unless proven unusable. "
    "GitHub code, tests, governance, and exact-head evidence are authoritative; "
    "Notion Lessons Learned remain advisory."
)
GUARDRAIL = (
    "After a governed coding or PR repair attempt remains red, do not begin another "
    "repair hypothesis or repository mutation until CKR6 material-use evaluation "
    "has been rerun, applicable Lessons Learned have been consumed or explicitly "
    "classified not-material/unavailable, and the failed hypothesis is preserved "
    "in the diagnostic state."
)
PACKAGING_TASK = (
    "Repair an isolated offline wheelhouse that omitted the navigation-registry "
    "distribution, preserving dependency closure and import provenance."
)
PACKAGING_HINTS = (
    "offline Python wheelhouse", "navigation registry package", "isolated pip installation",
)
MUTATION_TASK = "Re-enter CKR6 after a failed mutation-boundary repair attempt."


def request(task=PACKAGING_TASK, **changes):
    fields = dict(
        task_reference=task,
        ecosystem_hints=("agent-os",),
        language_hints=("python",),
        capability_keywords=PACKAGING_HINTS,
        target_path_hints=("08_Tooling/agent-os-navigation-registry",),
        specialized_knowledge_required=True,
    )
    fields.update(changes)
    return CodingKnowledgeRequest(**fields)


def ll51_candidate(**changes):
    fields = dict(
        knowledge_id="LL-51", source_system="notion-lessons-learned",
        source_revision=REVISION, currentness=KnowledgeCurrentness.CURRENT,
        name=TITLE, ecosystem="python", library_name=None,
        capability_kind="failure-avoidance", keywords=(),
        use_when=(GUIDANCE, GUARDRAIL),
        canonical_github_refs=(SOURCE,),
    )
    fields.update(changes)
    return CodingKnowledgeCandidate(**fields)


def testing_candidate():
    # Real LL-50 metadata; it explicitly prefers ordinary pytest for exact,
    # deterministic regressions. Used as an example of generic false sufficiency.
    return CodingKnowledgeCandidate(
        knowledge_id="LL-50", source_system="notion-lessons-learned",
        source_revision="2026-11-15T00:45:00.000Z",
        currentness=KnowledgeCurrentness.CURRENT,
        name="Use Hypothesis selectively for property-based testing and debugging",
        ecosystem="python", library_name=None, capability_kind="testing",
        use_when=("Prefer ordinary pytest for exact closed vocabularies and known deterministic regressions.",),
        canonical_github_refs=("https://github.com/Blummer92/agent-os/issues/1138",),
    )


def rich(value, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": value}]}


def ll51_row(*, source=SOURCE, revision=REVISION):
    return {
        "object": "page", "id": "fixture-51", "url": "https://www.notion.so/fixture-51",
        "last_edited_time": revision,
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": 51}},
            "Lesson Learned": rich(TITLE, "title"),
            "Status": {"type": "select", "select": {"name": "Needs follow-up"}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": {"name": "Testing"}},
            "Learning Type": {"type": "select", "select": {"name": "Mistake"}},
            "Applies To": {"type": "multi_select", "multi_select": []},
            "Source Link": {"type": "url", "url": source},
            "Guardrail": rich(GUARDRAIL),
            "What To Do Next Time": rich(GUIDANCE),
        },
    }


def reader(rows):
    return lambda _query: {"results": list(rows), "has_more": False, "next_cursor": None}


def ckr6_request(**changes):
    return request(
        task=MUTATION_TASK, capability_keywords=("ckr6 mutation boundary",),
        target_path_hints=(), **changes,
    )


def test_real_ll51_metadata_is_not_generic_testing():
    candidate = ll51_candidate()
    assert candidate.capability_kind == "failure-avoidance"
    assert candidate.name == TITLE and candidate.canonical_github_refs == (SOURCE,)
    assert ll51_row()["properties"]["Learning Type"]["select"]["name"] == "Mistake"


def test_unrelated_packaging_does_not_select_real_ll51():
    result = select_coding_knowledge(request(), (ll51_candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()
    assert result.reason_codes == ("no-relevant-candidate",)


def test_unrelated_packaging_through_production_retrieval_path():
    result = orchestrate_lesson_retrieval(request(), execute_read=reader([ll51_row()]))
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["observed_rows"] >= 1


@pytest.mark.parametrize("extra_path", [
    "docs/meeting-notes.md", "src/teacher-os/lesson-plan.py",
])
def test_irrelevant_path_does_not_select_ll51(extra_path):
    req = request(target_path_hints=("08_Tooling/agent-os-navigation-registry", extra_path))
    assert select_coding_knowledge(req, (ll51_candidate(),)).selected == ()


def test_explicit_ckr6_mutation_hint_selects_real_ll51():
    result = select_coding_knowledge(ckr6_request(), (ll51_candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert tuple(item.candidate.knowledge_id for item in result.selected) == ("LL-51",)
    assert result.selected[0].reason_codes == ("verified-ckr6-mutation-context-match",)
    assert result.selected[0].candidate.source_revision == REVISION


def test_explicit_ckr6_positive_uses_production_retrieval_path():
    result = orchestrate_lesson_retrieval(
        ckr6_request(), execute_read=reader([ll51_row()])
    )
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-51",)
    assert SOURCE in result.canonical_github_refs
    assert result.candidate_count <= 5 and result.selected_count <= 3


def test_m12_free_text_mutation_cannot_activate_ckr6_rule():
    # Mutation M12 in independent #4067 QA made the CKR6 special case trigger
    # on the plain word "mutation" in task_reference without the explicit
    # authorized capability hint. This must remain a no-match.
    req = request(
        task="Check mutation parsing in an unrelated Python package",
        capability_keywords=("testing",), target_path_hints=(),
    )
    result = select_coding_knowledge(req, (ll51_candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()
    assert result.reason_codes == ("no-relevant-candidate",)


def test_real_ll51_is_not_selected_by_generic_testing_hint():
    req = request(capability_keywords=("testing",), ecosystem_hints=("python",))
    result = select_coding_knowledge(req, (ll51_candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.selected == ()


def test_generic_testing_can_still_make_unrelated_lesson_sufficient():
    # Known open #4026 issue. This does not falsely identify LL-51 as testing.
    req = request(capability_keywords=("testing",), ecosystem_hints=("python",))
    result = select_coding_knowledge(req, (testing_candidate(),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert tuple(item.candidate.knowledge_id for item in result.selected) == ("LL-50",)


@pytest.mark.parametrize("overrides,reason", [
    ({"currentness": KnowledgeCurrentness.STALE}, "stale-relevant-candidate"),
    ({"currentness": KnowledgeCurrentness.UNVERIFIABLE, "canonical_github_refs": ()},
     "unverifiable-relevant-candidate"),
    ({"authority_conflict": True}, "canonical-authority-conflict"),
])
def test_relevant_currentness_and_conflicts_fail_closed(overrides, reason):
    result = select_coding_knowledge(ckr6_request(), (ll51_candidate(**overrides),))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.selected == ()
    assert result.reason_codes == (reason,)


def test_current_ll51_without_primary_source_is_insufficient():
    result = select_coding_knowledge(
        ckr6_request(), (ll51_candidate(canonical_github_refs=()),)
    )
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("canonical-reference-missing",)


def test_production_path_missing_source_cannot_select_ll51():
    result = orchestrate_lesson_retrieval(
        ckr6_request(), execute_read=reader([ll51_row(source=None)])
    )
    assert "LL-51" not in result.selected_lesson_ids
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT


def test_conflicting_duplicate_revision_fails_closed():
    original = ll51_candidate()
    conflicting = replace(original, source_revision="2026-11-16T00:00:00.000Z")
    result = select_coding_knowledge(ckr6_request(), (original, conflicting))
    assert result.sufficiency_status is SufficiencyStatus.MANUAL_REVIEW
    assert result.reason_codes == ("duplicate-identity-conflict",)
    assert result.selected == ()


@pytest.mark.parametrize("bad", [
    {"last_edited_time": None}, {"properties": None}, {"object": "database"},
])
def test_malformed_provider_row_production_path_fails_closed(bad):
    row = ll51_row()
    row.update(bad)
    result = orchestrate_lesson_retrieval(ckr6_request(), execute_read=reader([row]))
    assert "LL-51" not in result.selected_lesson_ids
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT


def test_production_path_rejects_incomplete_cursor_with_diagnostics():
    def incomplete(_query):
        return {"results": [ll51_row()], "has_more": True, "next_cursor": None}
    result = orchestrate_lesson_retrieval(ckr6_request(), execute_read=incomplete)
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ()
    assert result.retrieval_diagnostics["incomplete_reason_code"] == "missing-cursor"


def test_production_path_forwards_padded_opaque_cursor_verbatim():
    cursor = "  cursor-opaque-Ω  "
    calls = []
    def read(query):
        value = query.get("start_cursor")
        calls.append(value)
        if value is None:
            return {"results": [], "has_more": True, "next_cursor": cursor}
        assert value == cursor
        return {"results": [ll51_row()], "has_more": False, "next_cursor": None}
    result = orchestrate_lesson_retrieval(ckr6_request(), execute_read=read)
    assert calls == [None, cursor]
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-51",)


def test_positive_negative_order_independence():
    pool = (ll51_candidate(), testing_candidate())
    for req in (request(), ckr6_request()):
        first = select_coding_knowledge(req, pool)
        second = select_coding_knowledge(req, pool[::-1])
        assert tuple(x.candidate.knowledge_id for x in first.selected) == tuple(
            x.candidate.knowledge_id for x in second.selected
        )
        assert first.sufficiency_status == second.sufficiency_status
