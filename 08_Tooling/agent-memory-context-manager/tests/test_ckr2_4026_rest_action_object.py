"""Synthetic tests for the exact action/object relation in REST pagination."""
import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)
from test_ckr2_4026_github_rest_evidence import candidate, request
from test_lesson_retrieval_orchestrator import _lesson_row, _rich_text, _title


SEPARATE_ACTION = "Check that paginated GitHub comment pages are complete and keep duplicate IDs."
BOUND_ACTION = "Check that GitHub issue comment IDs are unique across pages."


def test_checks_pages_not_duplicate_ids_is_not_relevant():
    result = select_coding_knowledge(request(), (candidate(use_when=(SEPARATE_ACTION,)),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("no-relevant-candidate",)
    assert result.selected == ()


@pytest.mark.parametrize("marker", ("", "- "), ids=("plain", "markdown"))
def test_checks_exact_comment_identity_object_is_relevant(marker):
    result = select_coding_knowledge(request(), (candidate(use_when=(marker + BOUND_ACTION,)),))
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].candidate.knowledge_id == "LL-SYNTHETIC"
    assert result.selected[0].reason_codes == ("github-rest-evidence-text-match",)
    assert not result.authority_created


def test_normalized_snapshot_keeps_distinct_action_and_object():
    row = _lesson_row("LL-444")
    row["properties"].update({
        "Lesson Learned": _title("GitHub issue comment pagination"),
        "What To Do Next Time": _rich_text(SEPARATE_ACTION),
        "Guardrail": _rich_text("Do not trust incomplete GitHub pages."),
    })
    result = orchestrate_lesson_retrieval(
        request(), execute_read=lambda _query: {"results": [row], "has_more": False}
    )
    assert result.retrieval_diagnostics["normalized_rows"] > 0
    assert result.retrieval_diagnostics["skipped_rows"] == 0
    assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
    assert result.selected_lesson_ids == ()
    assert "no-relevant-candidate" in result.selection_reason_codes
