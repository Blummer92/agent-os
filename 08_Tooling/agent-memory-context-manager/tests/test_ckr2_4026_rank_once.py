"""#4026 rank-once contract, independent of status/abstention policy.

The redacted 35-signature #4068 fixture records 33 competing bucket-2 IDs
from the original CKR6 failure (87 observed Notion rows). It is not gold
applicability truth. Original historical selected IDs LL-50/LL-56/LL-18
remain documented in Draft PR #4068 and issue #4026.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from agent_memory_context_manager import coding_knowledge_selection as cks
from agent_memory_context_manager import lesson_activation_bridge as bridge
from agent_memory_context_manager import lesson_retrieval_orchestrator as ckr11
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


def _replay_with_rank_receipt(monkeypatch, req, rows):
    """Capture the actual rank-once selection, respecting CKR11 abstention."""
    evaluated = []
    actual_consume = ckr11.consume_lesson_preflight

    def record_prepolicy_result(*args, **kwargs):
        result = actual_consume(*args, **kwargs)
        evaluated.append(result)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(ckr11, "consume_lesson_preflight", record_prepolicy_result)
        result = orchestrate_lesson_retrieval(req, execute_read=_read(rows))
    assert len(evaluated) == 1
    return result, evaluated[0]


def _assert_generic_abstention(result):
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selected_lesson_ids == ()
    assert result.selection_reason_codes == ("generic-relevance-unverified",)


def _normalized():
    result = [bridge.normalize_lesson_row(item) for item in _rows()]
    assert all(isinstance(item, bridge.LessonRecordEvidence) for item in result)
    return result


@pytest.mark.parametrize("kind", tuple(REQUEST_TEXT))
def test_rank_once_production_snapshot_preserves_original_priority(kind, monkeypatch):
    result, ranked = _replay_with_rank_receipt(monkeypatch, request(kind), _rows())
    assert ranked.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert ranked.selected_lesson_ids == EXPECTED_RANK_ONCE[kind]
    _assert_generic_abstention(result)
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
    result, ranked = _replay_with_rank_receipt(monkeypatch, request(), _rows())
    assert ranked.selected_lesson_ids == ("LL-50", "LL-18", "LL-9")
    _assert_generic_abstention(result)
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


def test_snapshot_order_does_not_affect_full_pool_ranking(monkeypatch):
    source = _rows()
    for current in (source, source[::-1], source[12:] + source[:12]):
        result, ranked = _replay_with_rank_receipt(monkeypatch, request(), current)
        assert ranked.selected_lesson_ids == ("LL-50", "LL-18", "LL-9")
        _assert_generic_abstention(result)


def _direct_candidates():
    high, low = map(bridge._as_selection_candidate, _normalized()[:2])
    # Named library = bucket 3; generic ecosystem + capability = bucket 2.
    return replace(high, knowledge_id="high", library_name="pinned-lib"), replace(
        low, knowledge_id="low"
    )


@pytest.mark.parametrize("invalid_plan", [
    pytest.param(("high",), id="missing-identity"),
    pytest.param(("high", "unexpected"), id="unexpected-identity"),
    pytest.param(("high", "low", "low"), id="duplicate-identity"),
    pytest.param(("low", "high"), id="cross-bucket-inversion"),
])
def test_direct_ckr2_rejects_invalid_rank_plan(invalid_plan):
    req = request(library_hints=("pinned-lib",))
    outcome = cks._select_coding_knowledge(
        req, _direct_candidates(), _ranked_order=invalid_plan
    )
    assert outcome.sufficiency_status is cks.SufficiencyStatus.MANUAL_REVIEW
    assert outcome.recommended_escalation is cks.RetrievalEscalation.MANUAL_REVIEW
    assert outcome.reason_codes == ("upstream-ranking-order-mismatch",)
    assert outcome.selected == ()


def test_direct_ckr2_rejects_bucket_zero_identity_in_rank_plan():
    req = request(library_hints=("pinned-lib",))
    high, low = _direct_candidates()
    irrelevant = replace(low, ecosystem="go", capability_kind="packaging", keywords=())
    outcome = cks._select_coding_knowledge(
        req, (high, irrelevant), _ranked_order=("high", "low")
    )
    assert outcome.sufficiency_status is cks.SufficiencyStatus.MANUAL_REVIEW
    assert outcome.recommended_escalation is cks.RetrievalEscalation.MANUAL_REVIEW
    assert outcome.reason_codes == ("upstream-ranking-order-mismatch",)
    assert outcome.selected == ()


def test_direct_ckr2_accepts_complete_rank_plan():
    req = request(library_hints=("pinned-lib",))
    outcome = cks._select_coding_knowledge(
        req, _direct_candidates(), _ranked_order=("high", "low")
    )
    assert outcome.sufficiency_status is cks.SufficiencyStatus.SUFFICIENT
    assert outcome.reason_codes == ("knowledge-sufficient",)
    assert outcome.knowledge_refs == ("high",)


@pytest.mark.parametrize("invalidity", [
    "missing-ineligible", "duplicate-ineligible", "unexpected-identity",
])
def test_consume_rejects_invalid_plan_even_if_eligible_projection_is_valid(invalidity):
    req = request()
    first, second = _normalized()[:2]
    bounded = (first, replace(second, surface_before_work=False))
    valid = (first.lesson_id, second.lesson_id)
    # Every invalid plan would reduce to (first.lesson_id,) after filtering.
    # A CKR2 rejection cannot substitute for this consume-level check.
    invalid_plan = {
        "missing-ineligible": valid[:1],
        "duplicate-ineligible": (*valid, second.lesson_id),
        "unexpected-identity": (first.lesson_id, "LL-999999"),
    }[invalidity]
    ok = consume_lesson_preflight(req, bounded, _ranked_order=valid)
    assert ok.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert ok.selected_lesson_ids == valid[:1]
    outcome = consume_lesson_preflight(req, bounded, _ranked_order=invalid_plan)
    assert outcome.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert outcome.retrieval_escalation is cks.RetrievalEscalation.MANUAL_REVIEW
    assert outcome.selection_reason_codes == ("upstream-ranking-order-mismatch",)
    assert outcome.selected_lesson_ids == ()
    assert outcome.selection is None


def _rows_with_ineligible_50():
    rows = _rows()
    ranked = next(row for row in rows if row["id"] == "frozen-50")
    alternate = deepcopy(ranked)
    alternate["last_edited_time"] = "2026-11-21T00:00:00.000Z"
    ranked["properties"]["Surface Before Work?"]["checkbox"] = False
    return rows, alternate


def test_production_filters_ineligible_before_selecting_without_rescoring(monkeypatch):
    rows, _ = _rows_with_ineligible_50()
    result, ranked = _replay_with_rank_receipt(monkeypatch, request(), rows)
    assert ranked.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert ranked.selection_reason_codes == ("knowledge-sufficient",)
    assert ranked.selected_lesson_ids == ("LL-18", "LL-9", "LL-55")
    _assert_generic_abstention(result)
    assert result.candidate_count == 4


@pytest.mark.parametrize("learning_type", [
    pytest.param("Mistake", id="e2-bucket-zero-alternate"),
    pytest.param("Testing lesson", id="e3-relevant-alternate"),
])
def test_production_mixed_eligibility_revisions_report_duplicate_conflict(learning_type):
    rows, alternate = _rows_with_ineligible_50()
    alternate["properties"]["Learning Type"]["select"]["name"] = learning_type
    for snapshot in (rows + [alternate], [alternate] + list(reversed(rows))):
        result = _replay(snapshot=snapshot)
        assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
        assert result.selection_reason_codes == ("duplicate-identity-conflict",)
        assert result.selected_lesson_ids == ()


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


def _duplicate_ranking_rows():
    return [
        {
            "object": "page",
            "id": f"synthetic-{number}",
            "last_edited_time": "2026-11-15T00:41:00.000Z",
            "properties": {
                "Lesson ID": {"type": "unique_id", "unique_id": {
                    "prefix": "LL", "number": number}},
                "Lesson Learned": _rich("Synthetic QA record", "title"),
                "Status": {"type": "select", "select": {"name": "Applied"}},
                "Surface Before Work?": {"type": "checkbox", "checkbox": True},
                "Area": {"type": "select", "select": {"name": "Testing"}},
                "Learning Type": {"type": "select", "select": {"name": "Testing lesson"}},
                "Applies To": {"type": "multi_select", "multi_select": []},
                "Source Link": {"type": "url", "url": REF},
                "Guardrail": _rich("Synthetic QA guardrail"),
                "What To Do Next Time": _rich(guidance),
            },
        }
        for number, guidance in enumerate(
            ("review timing planning", "review timing planning", "review timing", "pacing"), 1
        )
    ]


@pytest.mark.parametrize(("orchestrate", "duplicate_count"), (
    pytest.param(bridge.orchestrate_lesson_activation, 5, id="direct-activation"),
    pytest.param(orchestrate_lesson_retrieval, 4, id="ckr11-retrieval"),
))
@pytest.mark.parametrize("extra", ("none", "exact-repeat", "different-revision"))
def test_rank_once_scores_normalized_duplicates_once(orchestrate, duplicate_count, extra, monkeypatch):
    rows = _duplicate_ranking_rows()
    if extra != "none":
        repeated = deepcopy(rows[-1])
        if extra == "different-revision":
            repeated["last_edited_time"] = "2026-11-16T00:41:00.000Z"
        rows.append(repeated)

    req = request(task_reference="pacing review timing planning", capability_keywords=("testing",))
    if orchestrate is orchestrate_lesson_retrieval:
        result, ranked = _replay_with_rank_receipt(monkeypatch, req, rows)
    else:
        result = ranked = orchestrate(req, execute_read=_read(rows))

    if extra == "different-revision":
        assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
        assert result.selection_reason_codes == ("duplicate-identity-conflict",)
        assert result.selected_lesson_ids == ()
        assert result.candidate_count == 5
    else:
        assert ranked.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert ranked.selected_lesson_ids == ("LL-1", "LL-2", "LL-4")
        assert result.candidate_count == (duplicate_count if extra == "exact-repeat" else 4)
        if orchestrate is orchestrate_lesson_retrieval:
            _assert_generic_abstention(result)


@pytest.mark.parametrize("reverse_pair", (False, True), ids=("upper-first", "lower-first"))
@pytest.mark.parametrize("cut", (3, 5), ids=("final-selection", "bridge-bound"))
def test_rank_once_orders_case_distinct_ids_independently_of_provider_order(cut, reverse_pair, monkeypatch):
    pair = ("ID_A", "id_a")
    if reverse_pair:
        pair = pair[::-1]
    ids = (
        ("a", "b", *pair, "y", "z")
        if cut == 3
        else ("a", "b", "c", "d", *pair)
    )
    seed = _duplicate_ranking_rows()[0]
    rows = []
    for index, identity in enumerate(ids):
        row = deepcopy(seed)
        row["id"] = f"case-distinct-{index}"
        row["properties"]["Lesson ID"] = _rich(identity)
        rows.append(row)

    req = request(task_reference="zzzz qqqq", capability_keywords=("testing",))
    records = tuple(bridge.normalize_lesson_row(row) for row in rows)
    assert tuple(record.lesson_id for record in records) == ids
    _, rank_plan = bridge._bound_relevant_lessons_with_order(req, records)
    expected_plan = (
        ("a", "b", "ID_A", "id_a", "y")
        if cut == 3
        else ("a", "b", "c", "d", "ID_A")
    )
    assert rank_plan == expected_plan

    direct = bridge.orchestrate_lesson_activation(req, execute_read=_read(rows))
    result, ranked = _replay_with_rank_receipt(monkeypatch, req, rows)
    for prepolicy in (direct, ranked):
        assert prepolicy.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert prepolicy.candidate_count == 5
        assert prepolicy.selected_lesson_ids == expected_plan[:3]
    _assert_generic_abstention(result)
