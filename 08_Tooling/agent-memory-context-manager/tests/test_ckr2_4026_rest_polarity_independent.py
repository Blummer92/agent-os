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


@pytest.mark.parametrize(
    "kind,hints,guidance",
    [
        ("pagination", PAGINATION,
         "Reject duplicate GitHub comment IDs across pages only if duplicates are allowed."),
        ("pagination", PAGINATION,
         "Reject duplicate GitHub comment IDs across pages, but only if duplicates are allowed."),
        ("receipt", RECEIPTS,
         "Reject oversized GitHub HTTP GET response bytes and verify edited timestamp provenance; "
         "otherwise treat the runtime timestamp as authoritative."),
        ("receipt", RECEIPTS,
         "Verify oversized GitHub HTTP GET response bytes are accepted and verify edited timestamp provenance."),
        ("receipt", RECEIPTS,
         "Reject oversized GitHub HTTP GET response bytes and verify a local cache timestamp."),
    ],
    ids=("conditional-duplicate-acceptance", "comma-carveout", "semicolon-carveout",
         "wrong-size-action", "wrong-timestamp-object"),
)
def test_rest_specialization_requires_unambiguous_action_and_object(kind, hints, guidance):
    result = select_coding_knowledge(request(hints), (candidate(kind, use_when=(guidance,)),))
    assert result.sufficiency_status is SufficiencyStatus.INSUFFICIENT
    assert result.reason_codes == ("no-relevant-candidate",)
    assert result.selected == ()
    assert result.authority_created is False


@pytest.mark.parametrize("kind,hints,guardrail", [
    ("pagination", PAGINATION, PAGINATION_GUIDANCE),
    ("receipt", RECEIPTS, RECEIPT_GUIDANCE),
], ids=("pagination", "receipt"))
@pytest.mark.parametrize("primary_is_relevant", (False, True), ids=("guardrail-only", "primary"))
def test_normalized_rest_positive_must_come_from_primary_guidance(
    kind, hints, guardrail, primary_is_relevant,
):
    row = _lesson_row("LL-444")
    row["properties"].update({
        "Lesson Learned": _title(candidate(kind).name),
        "What To Do Next Time": _rich_text(
            guardrail if primary_is_relevant else "Review the release readiness report."
        ),
        "Guardrail": _rich_text(guardrail),
    })
    result = orchestrate_lesson_retrieval(
        request(hints), execute_read=lambda _query: {"results": [row], "has_more": False},
    )
    assert result.retrieval_diagnostics["normalized_rows"] == 1
    assert result.retrieval_diagnostics["skipped_rows"] == 0
    if primary_is_relevant:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
        assert result.selected_lesson_ids == ("LL-444",)
    else:
        assert result.lesson_retrieval_status is LessonRetrievalStatus.INSUFFICIENT
        assert result.selection_reason_codes == ("no-relevant-candidate",)
        assert result.selected_lesson_ids == ()


@pytest.mark.parametrize("kinds", [
    ("rest",) * 4, ("writer",) * 4, ("rest", "writer") * 2,
], ids=("rest-only", "writer-only", "mixed"))
def test_consolidated_text_rules_abstain_on_four_way_unverified_tie(kinds):
    writer_hints = ("Notion writer", "persistence readback", "failure receipts")
    rows = []
    for i, kind in enumerate(kinds, 440):
        row = _lesson_row(f"LL-{i}")
        title, guidance, tags = (
            (candidate().name, PAGINATION_GUIDANCE, [])
            if kind == "rest" else
            ("Notion writer persistence readback",
             "After a Notion write, use an independent readback to verify the persisted revision.",
             [{"name": "Notion"}])
        )
        row["properties"].update({
            "Lesson Learned": _title(title),
            "What To Do Next Time": _rich_text(guidance),
            "Guardrail": _rich_text("Check the evidence before continuing."),
            "Applies To": {"type": "multi_select", "multi_select": tags},
        })
        rows.append(row)

    result = orchestrate_lesson_retrieval(
        request(PAGINATION + writer_hints),
        execute_read=lambda _query: {"results": rows, "has_more": False},
    )
    assert result.retrieval_diagnostics["normalized_rows"] == 4
    assert result.retrieval_diagnostics["best_bucket_tied_identities"] == 4
    assert result.retrieval_diagnostics["selection_basis"] == "generic-tie-lexical-cut"
    assert result.lesson_retrieval_status is LessonRetrievalStatus.MANUAL_REVIEW
    assert result.selection_reason_codes == ("generic-relevance-unverified",)
    assert result.selected_lesson_ids == ()
    assert result.authority_created is False
