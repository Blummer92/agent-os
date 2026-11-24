"""Coverage replay keeps the context-ranked (not lexical) prior safety bound."""
from copy import deepcopy

from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)

from test_ckr2_4026_rank_once import _duplicate_ranking_rows, _read, _rich, request


def test_coverage_replay_does_not_lose_hold_at_context_weighted_boundary():
    words = ("arcadian", "brighton", "coppered", "daytime", "eastern")
    seed = _duplicate_ranking_rows()[0]
    rows = []
    for number in range(10, 18):
        row = deepcopy(seed)
        row["id"] = f"synthetic-context-{number}"
        properties = row["properties"]
        properties["Lesson ID"]["unique_id"]["number"] = number
        properties["Lesson Learned"] = _rich("Alpha" if number < 17 else "Beta", "title")
        if 12 <= number <= 16:
            properties["What To Do Next Time"] = _rich(words[number - 12])
        if number == 16:
            properties["Source Link"]["url"] = None
        rows.append(row)

    req = request(task_reference=" ".join(words), library_hints=("Alpha", "Beta"))
    result = orchestrate_lesson_retrieval(req, execute_read=_read(rows))
    assert result.lesson_retrieval_status.value == "manual-review"
    assert result.selection_reason_codes == ("unverifiable-relevant-candidate",)
    assert result.candidate_count == 5
    assert not result.selected_lesson_ids
    assert not result.authority_created
