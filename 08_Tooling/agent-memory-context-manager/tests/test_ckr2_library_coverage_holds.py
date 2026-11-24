"""Coverage cannot turn an unresolved original bounded identity into acceptance."""
from copy import deepcopy
from dataclasses import replace

import pytest

from agent_memory_context_manager import lesson_activation_bridge as activation
from agent_memory_context_manager import lesson_retrieval_orchestrator as retrieval
from test_ckr2_4026_rank_once import _duplicate_ranking_rows, _read, _rich, request


def _rows(case):
    seed = _duplicate_ranking_rows()[0]
    numbers = tuple(range(10, 16)) if case != "four-clean" else (10, 11, 12, 15)
    rows = []
    for i in numbers:
        row = deepcopy(seed)
        row["id"] = f"local-fixture-{i}"
        props = row["properties"]
        props["Lesson ID"]["unique_id"]["number"] = i
        props["Lesson Learned"] = _rich("Alpha" if i < 15 else "Beta", "title")
        rows.append(row)
    if case == "missing-primary":
        rows[4]["properties"]["Source Link"]["url"] = None
    if case in ("conflicting-revision", "mixed-eligibility"):
        duplicate = deepcopy(rows[4])
        duplicate["last_edited_time"] = "2026-11-16T00:41:00.000Z"
        if case == "mixed-eligibility":
            duplicate["properties"]["Surface Before Work?"]["checkbox"] = False
        rows.append(duplicate)
    return rows


@pytest.mark.parametrize(
    "case,reason,selected",
    [
        ("four-clean", "knowledge-sufficient", ("LL-10", "LL-11", "LL-15")),
        ("six-clean", "knowledge-sufficient", ("LL-10", "LL-11", "LL-15")),
        ("missing-primary", "unverifiable-relevant-candidate", ()),
        ("conflicting-revision", "duplicate-identity-conflict", ()),
        ("mixed-eligibility", "duplicate-identity-conflict", ()),
    ],
)
def test_ckr11_coverage_repair_keeps_preexisting_bounded_holds(case, reason, selected):
    req = request(task_reference="isolated coverage check", library_hints=("Alpha", "Beta"))
    result = retrieval.orchestrate_lesson_retrieval(req, execute_read=_read(_rows(case)))
    assert result.selection_reason_codes == (reason,)
    assert result.selected_lesson_ids == selected
    assert result.lesson_retrieval_status.value == ("sufficient" if selected else "manual-review")
    assert not result.authority_created


@pytest.mark.parametrize(
    "case,preflight_sizes",
    [("four-clean", [4]), ("six-clean", [5, 5]), ("conflicting-revision", [5, 5])],
)
def test_compatibility_evaluation_only_when_bound_membership_changes(
    monkeypatch, case, preflight_sizes,
):
    seen = []
    real = retrieval.consume_lesson_preflight

    def record(req, rows, **kwargs):
        seen.append(len({row.lesson_id for row in rows}))
        return real(req, rows, **kwargs)

    monkeypatch.setattr(activation, "consume_lesson_preflight", record)
    monkeypatch.setattr(retrieval, "consume_lesson_preflight", record)
    req = request(task_reference="isolated coverage check", library_hints=("Alpha", "Beta"))
    retrieval.orchestrate_lesson_retrieval(req, execute_read=_read(_rows(case)))
    assert seen == preflight_sizes


def test_prior_cut_counts_distinct_ids_not_observational_rows():
    rows = tuple(map(activation.normalize_lesson_row, _rows("missing-primary")))
    duplicate = replace(rows[0], dropped_supporting_refs=("synthetic",))
    req = request(task_reference="isolated coverage check", library_hints=("Alpha", "Beta"))
    bounded, ranked = activation._bound_relevant_lessons_with_order(req, (*rows, duplicate))
    assert ranked == ("LL-10", "LL-11", "LL-12", "LL-13", "LL-14")
    assert len(bounded) == 6
