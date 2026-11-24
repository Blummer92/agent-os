"""Independent synthetic polarity and completeness controls for #4111."""
import pytest

from agent_memory_context_manager.coding_knowledge_selection import (
    SufficiencyStatus,
    select_coding_knowledge,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus
from agent_memory_context_manager.lesson_retrieval_orchestrator import (
    orchestrate_lesson_retrieval,
)
from test_ckr2_4026_github_rest_evidence import PAGINATION, RECEIPTS, candidate, request
from test_lesson_retrieval_orchestrator import _lesson_row, _rich_text, _title


PAGINATION_GUIDANCE = "Reject duplicate GitHub comment IDs across paginated pages."
RECEIPT_GUIDANCE = "Reject oversized GitHub HTTP GET response bytes and verify edited timestamp provenance."


@pytest.mark.parametrize(
    "kind,hints,changes",
    [
        ("pagination", PAGINATION, {"use_when": ("Review the release readiness report.",),
                                    "avoid_when": (PAGINATION_GUIDANCE,)}),
        ("pagination", PAGINATION, {"use_when": ("GitHub comment IDs are listed in the docs.",
                                                "Reject duplicate classroom records.")}),
        ("pagination", PAGINATION, {"use_when": (
            "Verify documentation. GitHub comment pages mention duplicate IDs.",)}),
        ("pagination", PAGINATION, {"name": "GitHub issue comment pagination is unrelated",
                                    "use_when": (PAGINATION_GUIDANCE,)}),
        ("pagination", PAGINATION, {"use_when": (
            "The review did not reject duplicate GitHub comment IDs across pages.",)}),
        ("receipt", RECEIPTS, {"use_when": ("Reject oversized GitHub HTTP GET response bytes.",)}),
        ("receipt", RECEIPTS, {"name": "GitHub REST bounded HTTP POST response evidence",
                              "use_when": ("Reject oversized GitHub HTTP POST response bytes "
                                "and verify edited timestamp provenance.",)}),
        ("receipt", RECEIPTS, {"use_when": (
            "Verify GitHub HTTP GET timestamp provenance before retaining the receipt.",)}),
        ("receipt", RECEIPTS, {"use_when": (
            "Reject oversized GitHub HTTP GET response bytes and disregard edited timestamp provenance.",)}),
    ],
    ids=("avoid-only", "split-fields", "split-sentences", "title-veto", "descriptive-negation",
         "size-only", "write-not-read", "time-only", "time-not-verified"),
)
def test_non_affirmative_or_partial_guidance_does_not_qualify(kind, hints, changes):
    result = select_coding_knowledge(request(hints), (candidate(kind, **changes),))
    assert result.selected == ()
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT


@pytest.mark.parametrize(
    "guidance,guardrail,should_select",
    [
        (PAGINATION_GUIDANCE, "Do not trust incomplete GitHub pages.", True),
        ("GitHub comment IDs are listed in the docs.",
         "Reject duplicate classroom records.", False),
    ],
    ids=("complete-source-assertion", "cross-field-word-collage"),
)
def test_normalized_snapshot_respects_guidance_polarity(guidance, guardrail, should_select):
    row = _lesson_row("LL-444")
    row["properties"].update({
        "Lesson Learned": _title("GitHub issue comment pagination"),
        "What To Do Next Time": _rich_text(guidance),
        "Guardrail": _rich_text(guardrail),
    })

    def mock_read(_query):
        return {"results": [row], "has_more": False}

    result = orchestrate_lesson_retrieval(request(), execute_read=mock_read)
    assert result.retrieval_diagnostics["observed_rows"] >= 1
    assert result.retrieval_diagnostics["normalized_rows"] >= 1
    assert result.retrieval_diagnostics["skipped_rows"] == 0
    if should_select:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.selected_lesson_ids == ("LL-444",)
        assert result.retrieval_diagnostics["selection_basis"] == "generic-unique"
    else:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
        assert result.selected_lesson_ids == ()


def test_explicit_receipt_mechanisms_still_qualify():
    result = select_coding_knowledge(
        request(RECEIPTS), (candidate("receipt", name="GitHub REST bounded HTTP GET response evidence",
                                       use_when=(RECEIPT_GUIDANCE,)),)
    )
    assert result.sufficiency_status is SufficiencyStatus.SUFFICIENT
    assert result.selected[0].reason_codes == ("github-rest-evidence-text-match",)
