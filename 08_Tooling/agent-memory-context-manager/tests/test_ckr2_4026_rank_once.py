"""#4026 rank-once contract, independent of status/abstention policy.

The redacted 35-signature #4068 fixture records 33 competing bucket-2 IDs
from the original CKR6 failure (87 observed Notion rows). It is not gold
applicability truth. Original historical selected IDs LL-50/LL-56/LL-18
remain documented in Draft PR #4068 and issue #4026.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from agent_memory_context_manager import coding_knowledge_selection as cks
from agent_memory_context_manager import lesson_activation_bridge as bridge
from agent_memory_context_manager.lesson_preflight import (
    LessonRetrievalStatus,
    consume_lesson_preflight,
)
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ckr2_4026_33way_rank_signatures.tsv"
CORE = (
    "PR #4067 exact head 5346d30962f0ee0004ed5ab12f9d3dce4b253f57: "
    "validate tests-only CKR2 LL-51 unrelated packaging negative control, "
    "explicit mutation-boundary positive, provenance, pagination, "
    "and mutation-discrimination tests."
)
DISCLAIMER = "No merge, issue closure, or Notion write authorization."
AFFIRMATIVE = "Merge, issue closure, and Notion write are authorized."
REQUEST_TEXT = {
    "original": CORE + " " + DISCLAIMER,
    "without_disclaimer": CORE,
    "disclaimer_only": DISCLAIMER,
    "inverted_disclaimer": CORE + " " + AFFIRMATIVE,
}
EXPECTED_RANK_ONCE = {
    "original": ("LL-50", "LL-18", "LL-9"),
    "without_disclaimer": ("LL-18", "LL-55", "LL-50"),
    "disclaimer_only": ("LL-50", "LL-56", "LL-9"),
    "inverted_disclaimer": ("LL-50", "LL-18", "LL-9"),
}
REF = "https://github.com/Blummer92/agent-os/issues/4026"


def request(kind="original", **extra):
    fields = dict(
        task_reference=REQUEST_TEXT[kind],
        ecosystem_hints=("python",),
        capability_keywords=("testing", "lesson-selection"),
        specialized_knowledge_required=True,
    )
    fields.update(extra)
    return cks.CodingKnowledgeRequest(**fields)


def _rich(value, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": value}]}


def _rows():
    result = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        ident, area, kind, status, source, revision, tokens, applies = line.split("|", 7)
        number = int(ident.split("-")[1])
        result.append({
            "object": "page", "id": f"frozen-{number}",
            "last_edited_time": revision,
            "properties": {
                "Lesson ID": {"type": "unique_id", "unique_id": {
                    "prefix": "LL", "number": number}},
                "Lesson Learned": _rich("Archived candidate signature", "title"),
                "Status": {"type": "select", "select": {"name": status}},
                "Surface Before Work?": {"type": "checkbox", "checkbox": True},
                "Area": {"type": "select", "select": {"name": area}},
                "Learning Type": {"type": "select", "select": {"name": kind}},
                "Applies To": {"type": "multi_select", "multi_select": [
                    {"name": value} for value in applies.split(",") if value
                ]},
                "Source Link": {"type": "url", "url": REF if source == "src" else None},
                "Guardrail": _rich("Masked guidance without extra request terms"),
                "What To Do Next Time": _rich(tokens or "masked guidance"),
            },
        })
    return result


def _read(rows):
    return lambda _query: {
        "results": list(rows), "has_more": False, "next_cursor": None,
    }


def _replay(kind="original", snapshot=None):
    return orchestrate_lesson_retrieval(
        request(kind), execute_read=_read(_rows() if snapshot is None else snapshot)
    )


def _normalized():
    result = [bridge.normalize_lesson_row(item) for item in _rows()]
    assert all(isinstance(item, bridge.LessonRecordEvidence) for item in result)
    return result


@pytest.mark.parametrize("kind", tuple(REQUEST_TEXT))
def test_rank_once_production_snapshot_preserves_original_priority(kind):
    # Sufficiency is historical policy, not evidence that lessons apply.
    result = _replay(kind)
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == EXPECTED_RANK_ONCE[kind]
    assert result.candidate_count == 5
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 33
    assert result.retrieval_diagnostics["selection_basis"] == "generic-tie-lexical-cut"


def test_full_population_scores_are_not_recomputed_after_cut(monkeypatch):
    original = bridge.contextual_tie_scores
    observed = []

    def full_population(request, tied):
        bound = tuple(tied)
        observed.append(len(bound))
        return original(request, bound)

    def forbidden_second_pass(_request, _tied):
        raise AssertionError("Second CKR2 contextual rescore was called")

    monkeypatch.setattr(bridge, "contextual_tie_scores", full_population)
    monkeypatch.setattr(cks, "contextual_tie_scores", forbidden_second_pass)
    result = _replay()
    assert result.selected_lesson_ids == ("LL-50", "LL-18", "LL-9")
    # One 33-way bucket and one separate bucket-1 singleton are scored once.
    assert observed == [33, 1]


def test_full_pool_five_to_three_order_is_a_prefix():
    req = request()
    pool = _normalized()
    bounded, order = bridge._bound_relevant_lessons_with_order(req, pool)
    assert len({item.lesson_id for item in bounded}) == 5
    assert order == ("LL-50", "LL-18", "LL-9", "LL-55", "LL-56")
    preflight = consume_lesson_preflight(req, bounded, _ranked_order=order)
    assert preflight.selected_lesson_ids == order[:3]
    assert preflight.selection_reason_codes == ("knowledge-sufficient",)


def test_standalone_ckr2_keeps_existing_five_way_scoring():
    req = request()
    bounded, order = bridge._bound_relevant_lessons_with_order(req, _normalized())
    assert order[:3] == ("LL-50", "LL-18", "LL-9")
    standalone = cks.select_coding_knowledge(
        req, tuple(bridge._as_selection_candidate(x) for x in bounded)
    )
    assert tuple(item.candidate.knowledge_id for item in standalone.selected) == (
        "LL-50", "LL-56", "LL-18"
    )


def test_snapshot_order_does_not_affect_full_pool_ranking():
    source = _rows()
    for current in (source, source[::-1], source[12:] + source[:12]):
        assert _replay(snapshot=current).selected_lesson_ids == (
            "LL-50", "LL-18", "LL-9"
        )


@pytest.mark.parametrize("rank_order", [
    ("LL-50", "LL-18", "LL-9"),
    ("LL-50", "LL-18", "LL-9", "LL-55", "LL-55"),
    ("LL-50", "LL-18", "LL-9", "LL-55", "LL-99"),
])
def test_invalid_internal_priority_plan_fails_closed(rank_order):
    req = request()
    bounded, _ = bridge._bound_relevant_lessons_with_order(req, _normalized())
    outcome = consume_lesson_preflight(req, bounded, _ranked_order=rank_order)
    assert outcome.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert outcome.selected_lesson_ids == ()
    assert "upstream-ranking-order-mismatch" in outcome.selection_reason_codes


def test_primary_provenance_is_not_overridden_by_rank_plan():
    rows = _rows()
    selected = next(x for x in rows if x["properties"]["Lesson ID"]["unique_id"]["number"] == 50)
    selected["properties"]["Source Link"]["url"] = None
    result = _replay(snapshot=rows)
    assert result.lesson_retrieval_status is not LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ()


def test_conflicting_revisions_at_priority_boundary_fail_closed():
    rows = _rows()
    head = next(x for x in rows if x["properties"]["Lesson ID"]["unique_id"]["number"] == 56)
    duplicate = dict(head)
    duplicate["last_edited_time"] = "2026-11-21T00:00:00.000Z"
    result = _replay(snapshot=rows + [duplicate])
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selected_lesson_ids == ()
    assert "duplicate-identity-conflict" in result.selection_reason_codes


def test_explicit_higher_bucket_outweighs_generic_context():
    req = request(library_hints=("pinned-lib",))
    original = _normalized()
    boosted = replace(original[0], library_name="pinned-lib")
    bound, order = bridge._bound_relevant_lessons_with_order(
        req, (boosted, *original[1:])
    )
    assert order[0] == boosted.lesson_id
    outcome = consume_lesson_preflight(req, bound, _ranked_order=order)
    assert outcome.selected_lesson_ids[0] == boosted.lesson_id


def test_zero_context_overlap_preserves_lexical_cut():
    req = request(kind="original", task_reference="zzzz qqqq", capability_keywords=("testing",))
    bounded, order = bridge._bound_relevant_lessons_with_order(req, _normalized())
    assert order[:3] == ("LL-10", "LL-18", "LL-21")
    outcome = consume_lesson_preflight(req, bounded, _ranked_order=order)
    assert outcome.selected_lesson_ids == order[:3]
