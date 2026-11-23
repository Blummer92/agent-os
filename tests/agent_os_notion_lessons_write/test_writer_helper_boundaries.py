"""Source-grounded Notion writer helper regression tests (offline, no provider writes).

Covers bounded rich-text parsing, canonical property decoding, and page-state
rejection. This file tests genuine public validation invariants rather than
mutation IDs or the internal implementation of mutmut.
"""

from copy import deepcopy

import pytest

from scripts.agent_os_notion_lessons_write.admission import WriteBlocked
from scripts.agent_os_notion_lessons_write.catalog import SUPPORTING_SOURCE_LINKS
from scripts.agent_os_notion_lessons_write.writer import _page, _text, _values


SOURCE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_ID = "00000000-0000-0000-0000-000000000002"


def assert_blocked_exact(fn, code):
    with pytest.raises(WriteBlocked) as exc:
        fn()
    assert str(exc.value) == code


def text_item(value="x", *, fallback=None):
    return {
        "type": "text",
        "plain_text": value,
        "text": {"content": value if fallback is None else fallback},
    }


def canonical_page():
    return {
        "id": PAGE_ID,
        "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
        "last_edited_time": "2026-10-06T20:00:00.000Z",
        "archived": False,
        "is_archived": False,
        "in_trash": False,
    }


def property_page(name, kind, data):
    return {"properties": {name: {"type": kind, kind: data}}}


# Rich-text item-count bounds are inclusive at 100, exclusive at 101.
@pytest.mark.parametrize("count", [0, 1, 99, 100])
def test_text_accepts_at_most_one_hundred_items(count):
    assert _text([text_item("a") for _ in range(count)]) == "a" * count


@pytest.mark.parametrize("count", [101, 102])
def test_text_rejects_oversize_item_collections(count):
    assert_blocked_exact(lambda: _text([text_item("x") for _ in range(count)]),
                         "malformed-page-properties")


@pytest.mark.parametrize("invalid", [42, None, ["x"], {"type": "mention", "plain_text": "x"}])
def test_text_non_text_items_fail_with_finite_code(invalid):
    assert_blocked_exact(lambda: _text([invalid]), "non-text-lesson-content")


def test_text_prefers_plain_text_and_preserves_chunk_boundaries():
    items = [text_item("authoritative", fallback="incorrect"),
             text_item(" source", fallback="wrong")]
    assert _text(items) == "authoritative source"


def test_text_plain_text_without_nested_text_is_valid():
    assert _text([{"type": "text", "plain_text": "already-rendered"}]) == "already-rendered"


@pytest.mark.parametrize("invalid", [None, 9, {"value": "x"}])
def test_text_rejects_non_string_content_with_correct_diagnostic(invalid):
    assert_blocked_exact(lambda: _text([text_item(invalid)]), "malformed-page-properties")


@pytest.mark.parametrize("size", [0, 1, 1999, 2000])
def test_text_accepted_content_character_limit(size):
    assert _text([text_item("x" * size)]) == "x" * size


@pytest.mark.parametrize("size", [2001, 2002])
def test_text_oversize_content_has_exact_diagnostic(size):
    assert_blocked_exact(lambda: _text([text_item("x" * size)]),
                         "malformed-page-properties")


@pytest.mark.parametrize("bad", [None, [], "not-a-mapping"])
def test_values_rejects_non_mapping_properties_with_finite_diagnostic(bad):
    assert_blocked_exact(lambda: _values({"properties": bad}, ("Area",)),
                         "malformed-page-properties")


@pytest.mark.parametrize("bad", [None, "not-an-array", {"rich_text": []}])
def test_values_supporting_links_require_list_with_exact_diagnostic(bad):
    row = property_page(SUPPORTING_SOURCE_LINKS, "rich_text", bad)
    assert_blocked_exact(lambda: _values(row, (SUPPORTING_SOURCE_LINKS,)),
                         "malformed-page-properties")


def test_values_supporting_links_do_not_skip_subsequent_metadata():
    link = "https://github.com/Blummer92/agent-os/issues/3305"
    row = {
        "properties": {
            SUPPORTING_SOURCE_LINKS: {"type": "rich_text", "rich_text": [text_item(link)]},
            "Area": {"type": "select", "select": {"name": "Governance"}},
        }
    }
    assert _values(row, (SUPPORTING_SOURCE_LINKS, "Area")) == {
        SUPPORTING_SOURCE_LINKS: (link,), "Area": "Governance"
    }


@pytest.mark.parametrize("bad", [None, "string-not-list", {"name": "one"}, 7])
def test_values_multi_select_rejects_non_list_with_finite_diagnostic(bad):
    row = property_page("Applies To", "multi_select", bad)
    assert_blocked_exact(lambda: _values(row, ("Applies To",)),
                         "malformed-page-properties")


@pytest.mark.parametrize("count", [0, 1, 99, 100])
def test_values_multi_select_accepts_up_to_one_hundred_options(count):
    row = property_page("Applies To", "multi_select", [{"name": "lesson"}] * count)
    assert _values(row, ("Applies To",)) == {"Applies To": ("lesson",) * count}


@pytest.mark.parametrize("count", [101, 102])
def test_values_multi_select_rejects_oversize_with_exact_diagnostic(count):
    row = property_page("Applies To", "multi_select", [{"name": "lesson"}] * count)
    assert_blocked_exact(lambda: _values(row, ("Applies To",)),
                         "malformed-page-properties")


@pytest.mark.parametrize("bad", [None, [], 23, "not-a-page"])
def test_page_requires_mapping_with_finite_reason_code(bad):
    assert_blocked_exact(lambda: _page(bad, SOURCE_ID), "malformed-page")


@pytest.mark.parametrize("flag", ["archived", "is_archived", "in_trash"])
def test_page_any_inactive_flag_blocks_with_exact_reason(flag):
    record = canonical_page()
    record[flag] = True
    assert_blocked_exact(lambda: _page(record, SOURCE_ID, PAGE_ID), "inactive-page")


def test_page_active_page_preserves_exact_identity():
    assert _page(deepcopy(canonical_page()), SOURCE_ID, PAGE_ID) == PAGE_ID