"""#3973 full-database repair: CKR6 retrieval must exhaust every Notion page.

Before this fix `orchestrate_lesson_activation` made exactly one
`execute_read` call and ignored `has_more` / `next_cursor`, so every lesson
past the first provider page was silently invisible to CKR6 -- exactly the
failure a full-database inventory cannot tolerate (the live database holds
more rows than one page_size=25 response can carry). These tests pin:

- multi-page exhaustion: a lesson that only exists on page 2 reaches CKR2;
- explicit single-page executors with `has_more: false` remain supported;
  missing `has_more` is malformed (P6), never assumed complete;
- malformed pagination state fails closed instead of looping or truncating:
  `has_more` without a cursor, a repeated cursor, a non-boolean `has_more`,
  a non-string cursor, and an executor that never ends its pages;
- exactly 25 rows with `has_more: false` are allowed; an oversized page,
  cumulative overflow, or 25 rows with `has_more: true` fail closed
  without admitting a truncated partial candidate set.
"""
import pytest

from agent_memory_context_manager.coding_knowledge_selection import CodingKnowledgeRequest
from agent_memory_context_manager.lesson_activation_bridge import (
    MAX_RETRIEVAL_PAGES,
    MAX_RETRIEVAL_ROWS,
    LessonActivationError,
    orchestrate_lesson_activation,
)
from agent_memory_context_manager.lesson_preflight import LessonRetrievalStatus

from test_lesson_retrieval_orchestrator import OPAQUE_CURSORS


def request(**overrides):
    data = dict(
        task_reference="issue:#3973",
        ecosystem_hints=("python",),
        capability_keywords=("testing",),
        target_path_hints=(),
        canonical_rule_refs=(),
        known_knowledge_refs=(),
        specialized_knowledge_required=None,
    )
    data.update(overrides)
    return CodingKnowledgeRequest(**data)


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich_text(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name}}


def _multi_select(*names):
    return {"type": "multi_select", "multi_select": [{"name": name} for name in names]}


def _checkbox(value):
    return {"type": "checkbox", "checkbox": value}


def _url(value):
    return {"type": "url", "url": value}


def live_row(number):
    return {
        "object": "page",
        "id": f"11111111-1111-1111-1111-1111111111{number:02d}",
        "url": "https://www.notion.so/lesson-page-abc123",
        "last_edited_time": "2026-08-30T12:00:00.000Z",
        "properties": {
            "Lesson ID": _rich_text(f"LL-{number}"),
            "Lesson Learned": _title(f"Lesson number {number}"),
            "Status": _select("Applied"),
            "Surface Before Work?": _checkbox(True),
            "Area": _select("Testing"),
            "Applies To": _multi_select("Notion", "Curriculum"),
            "Learning Type": _select("Testing lesson"),
            "Source Link": _url("https://github.com/Blummer92/agent-os/issues/2064"),
            "Guardrail": _rich_text("Never reuse stale evidence."),
            "What To Do Next Time": _rich_text("Reacquire evidence after head advances."),
        },
    }


def test_second_page_rows_reach_ckr2():
    calls = []

    def executor(query):
        calls.append(dict(query))
        if "start_cursor" not in query:
            return {"results": [live_row(n) for n in (4, 5, 6)], "has_more": True, "next_cursor": "c1"}
        return {"results": [live_row(n) for n in (1, 2, 3)], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 2
    assert "start_cursor" not in calls[0]
    assert calls[1]["start_cursor"] == "c1"
    # The follow-up page keeps the original filter and page size.
    assert calls[1]["filter"] == calls[0]["filter"]
    assert calls[1]["page_size"] == calls[0]["page_size"]
    # LL-1..LL-3 exist only on page 2, and CKR2 ranks by lesson ID, so all
    # three must be selected: without exhaustion they could never be
    # selected at all. The candidate budget still holds five distinct IDs.
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.candidate_count == 5
    assert set(result.selected_lesson_ids) == {"LL-1", "LL-2", "LL-3"}


def test_single_page_explicit_has_more_false_is_unchanged():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {"results": [live_row(1)], "has_more": False}

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 1
    assert "start_cursor" not in calls[0]
    assert result.selected_lesson_ids == ("LL-1",)


def test_missing_has_more_is_malformed_not_a_complete_page():
    # P6 fix: a page without has_more is rejected, never assumed complete.
    def executor(query):
        return {"results": [live_row(1)]}

    with pytest.raises(LessonActivationError, match="missing 'has_more'"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_non_mapping_result_items_fail_closed():
    # P5 fix: any non-mapping item makes the whole page malformed.
    def executor(query):
        return {"results": [live_row(1), "not-a-mapping"], "has_more": False}

    with pytest.raises(LessonActivationError, match="non-mapping items"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_has_more_without_cursor_fails_closed():
    def executor(query):
        if "start_cursor" not in query:
            return {"results": [live_row(1)], "has_more": True, "next_cursor": None}
        return {"results": [], "has_more": False, "next_cursor": None}

    with pytest.raises(LessonActivationError, match="missing next cursor"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_repeated_cursor_fails_closed():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {"results": [live_row(1)], "has_more": True, "next_cursor": "c1"}

    with pytest.raises(LessonActivationError, match="repeated pagination cursor"):
        orchestrate_lesson_activation(request(), execute_read=executor)
    # First page (cursor None) + second page (cursor c1); the third attempt
    # is refused before another read, so the executor is never called again.
    assert len(calls) == 2


def test_page_cap_fails_closed_instead_of_silent_truncation():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {
            "results": [live_row(len(calls))],
            "has_more": True,
            "next_cursor": f"c{len(calls)}",
        }

    with pytest.raises(LessonActivationError, match="exceeded page bound"):
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == MAX_RETRIEVAL_PAGES


def test_row_cap_with_more_fails_closed_without_follow_up():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {
            "results": [live_row(n) for n in range(1, MAX_RETRIEVAL_ROWS + 1)],
            "has_more": True,
            "next_cursor": "c1",
        }

    with pytest.raises(LessonActivationError, match="exceeded row bound"):
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 1


def test_exact_row_cap_complete_page_remains_admissible():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {
            "results": [live_row(n) for n in range(1, MAX_RETRIEVAL_ROWS + 1)],
            "has_more": False,
        }

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 1
    assert result.candidate_count == 5


def test_oversized_single_page_fails_closed_without_truncation():
    def executor(query):
        return {
            "results": [live_row(n) for n in range(1, MAX_RETRIEVAL_ROWS + 2)],
            "has_more": False,
        }

    with pytest.raises(LessonActivationError, match="exceeded row bound"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_exact_row_cap_without_has_more_fails_closed():
    def executor(query):
        return {"results": [live_row(n) for n in range(1, MAX_RETRIEVAL_ROWS + 1)]}

    with pytest.raises(LessonActivationError, match="missing 'has_more'"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_partial_first_page_cannot_admit_if_second_exceeds_total_budget():
    calls = []

    def executor(query):
        calls.append(dict(query))
        if "start_cursor" not in query:
            return {
                "results": [live_row(n) for n in range(1, 21)],
                "has_more": True, "next_cursor": "second",
            }
        return {
            "results": [live_row(n) for n in range(21, 27)],
            "has_more": False,
        }

    with pytest.raises(LessonActivationError, match="exceeded row bound"):
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 2


def test_malformed_has_more_fails_closed():
    def executor(query):
        return {"results": [live_row(1)], "has_more": "yes", "next_cursor": None}

    with pytest.raises(LessonActivationError, match="non-boolean has_more"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_malformed_next_cursor_fails_closed():
    def executor(query):
        return {"results": [live_row(1)], "has_more": True, "next_cursor": 123}

    with pytest.raises(LessonActivationError, match="malformed next_cursor"):
        orchestrate_lesson_activation(request(), execute_read=executor)


def test_empty_second_page_ends_retrieval():
    calls = []

    def executor(query):
        calls.append(dict(query))
        if "start_cursor" not in query:
            return {"results": [live_row(1)], "has_more": True, "next_cursor": "c1"}
        return {"results": [], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 2
    assert result.selected_lesson_ids == ("LL-1",)


# --- Opaque pagination cursor integrity on the activation (bridge) path ----
#
# Notion cursors are opaque (https://developers.notion.com/reference/pagination):
# a valid token is forwarded exactly as received. `_page_cursor` may use
# `.strip()` only to REJECT a whitespace-only token.


@pytest.mark.parametrize("cursor", OPAQUE_CURSORS)
def test_opaque_cursor_reaches_provider_verbatim_and_page_two_is_selected(cursor):
    calls = []

    def executor(query):
        calls.append(dict(query))
        if "start_cursor" not in query:
            return {"results": [], "has_more": True, "next_cursor": cursor}
        if query["start_cursor"] != cursor:
            raise RuntimeError(f"provider rejected start_cursor {query['start_cursor']!r}")
        return {"results": [live_row(1)], "has_more": False, "next_cursor": None}

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert [c.get("start_cursor") for c in calls] == [None, cursor]
    assert result.lesson_retrieval_status is LessonRetrievalStatus.SUFFICIENT
    assert result.selected_lesson_ids == ("LL-1",)


@pytest.mark.parametrize(
    "pagination, message",
    [
        pytest.param({"has_more": True, "next_cursor": ""}, "malformed next_cursor", id="empty"),
        pytest.param({"has_more": True, "next_cursor": " \t\u00a0\n "}, "malformed next_cursor", id="whitespace-only"),
        pytest.param({"has_more": True, "next_cursor": 123}, "malformed next_cursor", id="integer"),
        pytest.param({"has_more": True, "next_cursor": {"c": "x"}}, "malformed next_cursor", id="object"),
        pytest.param({"has_more": "true", "next_cursor": "c1"}, "non-boolean has_more", id="string-has-more"),
        pytest.param({"has_more": False, "next_cursor": "c1"}, "malformed next_cursor", id="terminal-with-cursor"),
        pytest.param({"has_more": False, "next_cursor": "  c1  "}, "malformed next_cursor", id="terminal-with-padded-cursor"),
        pytest.param({"has_more": True}, "missing next cursor", id="missing-cursor-key"),
        pytest.param({"has_more": True, "next_cursor": None}, "missing next cursor", id="null-cursor"),
    ],
)
def test_malformed_pagination_fails_closed_before_any_second_read(pagination, message):
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {"results": [live_row(1)], **pagination}

    with pytest.raises(LessonActivationError, match=message):
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 1


def test_provider_rejecting_second_page_cursor_yields_no_partial_result():
    calls = []

    def executor(query):
        calls.append(dict(query))
        if len(calls) == 1:
            return {"results": [live_row(1)], "has_more": True, "next_cursor": "  c1  "}
        raise RuntimeError("provider rejected start_cursor")

    with pytest.raises(RuntimeError, match="provider rejected"):
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == 2


def test_exactly_repeated_padded_cursor_is_still_a_cycle_without_disclosing_it():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {"results": [live_row(1)], "has_more": True, "next_cursor": "  PRIVATE-c1  "}

    with pytest.raises(LessonActivationError, match="repeated pagination cursor") as caught:
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert [c.get("start_cursor") for c in calls] == [None, "  PRIVATE-c1  "]
    assert "PRIVATE-c1" not in str(caught.value)


def test_cycle_protection_compares_exact_tokens_not_trimmed_copies():
    pages = iter([
        {"results": [], "has_more": True, "next_cursor": "c1"},
        {"results": [], "has_more": True, "next_cursor": "  c1  "},
        {"results": [live_row(1)], "has_more": False, "next_cursor": None},
    ])
    calls = []

    def executor(query):
        calls.append(dict(query))
        return next(pages)

    result = orchestrate_lesson_activation(request(), execute_read=executor)
    assert [c.get("start_cursor") for c in calls] == [None, "c1", "  c1  "]
    assert result.selected_lesson_ids == ("LL-1",)


def test_page_bound_with_padded_cursors_still_fails_closed():
    calls = []

    def executor(query):
        calls.append(dict(query))
        return {"results": [], "has_more": True, "next_cursor": f"  cursor-{len(calls)}  "}

    with pytest.raises(LessonActivationError, match="exceeded page bound"):
        orchestrate_lesson_activation(request(), execute_read=executor)
    assert len(calls) == MAX_RETRIEVAL_PAGES
