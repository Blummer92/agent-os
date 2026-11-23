"""Offline contract tests for Notion writer schema, page, and reconciliation boundaries.

These tests exercise closed reason codes, exact page identity/destination, page
revision requirements, live schema options, and fail-closed reconciliation.
No credentials or live Notion writes are used.
"""

from copy import deepcopy

import pytest

from scripts.agent_os_notion_lessons_write.admission import WriteBlocked
from scripts.agent_os_notion_lessons_write.writer import (
    _check_schema, _find_lesson_id, _find_title, _page, _single,
)


SOURCE_ID = "00000000-0000-0000-0000-000000000001"
PAGE_ID = "00000000-0000-0000-0000-000000000002"
OTHER_ID = "00000000-0000-0000-0000-000000000003"

# The first field is deliberately non-select. The schema checker must continue
# past it to validate the Area and Applies To options that follow.
LESSON = {
    "Lesson Learned": "Reviewed lesson",
    "Area": "Governance",
    "Applies To": ("Notion",),
}


def assert_blocked_exact(callback, code):
    with pytest.raises(WriteBlocked) as caught:
        callback()
    assert str(caught.value) == code


def page():
    return {
        "id": PAGE_ID,
        "parent": {"type": "data_source_id", "data_source_id": SOURCE_ID},
        "last_edited_time": "2026-11-23T06:00:00.000Z",
        "archived": False,
        "is_archived": False,
        "in_trash": False,
    }


def schema():
    return {
        "id": SOURCE_ID,
        "properties": {
            "Lesson Learned": {"type": "title"},
            "Area": {"type": "select", "select": {"options": [{"name": "Governance"}]}},
            "Applies To": {
                "type": "multi_select",
                "multi_select": {"options": [{"name": "Notion"}]},
            },
            "Lesson ID": {"type": "unique_id"},
            "Status": {"type": "select"},
        },
        "archived": False,
        "is_archived": False,
        "in_trash": False,
    }


def test_page_valid_canonical_source_and_revision():
    assert _page(page(), SOURCE_ID, PAGE_ID) == PAGE_ID


def test_page_missing_parent_yields_finite_destination_error():
    item = page()
    del item["parent"]
    # A missing parent must produce a finite WriteBlocked diagnostic, rather
    # than leaking an AttributeError/provider-unavailable receipt.
    assert_blocked_exact(lambda: _page(item, SOURCE_ID), "page-destination-mismatch")


@pytest.mark.parametrize("wrong_parent", [
    {"type": "database_id", "data_source_id": SOURCE_ID},
    {"type": "data_source_id", "data_source_id": OTHER_ID},
    {"type": "other"},
])
def test_page_wrong_destination_has_exact_diagnostic(wrong_parent):
    item = page()
    item["parent"] = wrong_parent
    assert_blocked_exact(lambda: _page(item, SOURCE_ID), "page-destination-mismatch")


@pytest.mark.parametrize("revision", [None, "", 1, 7, True, ["unexpected"]])
def test_page_requires_nonblank_string_revision(revision):
    item = page()
    item["last_edited_time"] = revision
    assert_blocked_exact(lambda: _page(item, SOURCE_ID), "page-revision-required")


def test_page_different_expected_page_identity_refused():
    assert_blocked_exact(lambda: _page(page(), SOURCE_ID, OTHER_ID), "page-identity-mismatch")


def test_schema_accepts_matching_closed_options_and_types():
    assert _check_schema(schema(), SOURCE_ID, LESSON) is None


def test_schema_rejects_wrong_source_with_finite_reason():
    item = schema()
    item["id"] = OTHER_ID
    assert_blocked_exact(lambda: _check_schema(item, SOURCE_ID, LESSON),
                         "schema-destination-mismatch")


@pytest.mark.parametrize("flag", ["is_archived", "in_trash", "archived"])
def test_schema_refuses_inactive_data_source_with_finite_reason(flag):
    item = schema()
    item[flag] = True
    assert_blocked_exact(lambda: _check_schema(item, SOURCE_ID, LESSON),
                         "inactive-data-source")


@pytest.mark.parametrize("name", ["Area", "Applies To"])
def test_schema_invalid_descriptor_options_are_not_created(name):
    item = schema()
    kind = "select" if name == "Area" else "multi_select"
    item["properties"][name][kind]["options"] = [{"name": "Unreviewed"}]
    assert_blocked_exact(lambda: _check_schema(item, SOURCE_ID, LESSON),
                         "descriptive-option-not-in-live-schema")


@pytest.mark.parametrize("name", ["Area", "Applies To"])
def test_schema_missing_option_section_is_blocked_not_provider_error(name):
    item = schema()
    kind = "select" if name == "Area" else "multi_select"
    del item["properties"][name][kind]
    assert_blocked_exact(lambda: _check_schema(item, SOURCE_ID, LESSON),
                         "descriptive-option-not-in-live-schema")


def test_schema_missing_properties_fails_closed():
    item = schema()
    del item["properties"]
    assert_blocked_exact(lambda: _check_schema(item, SOURCE_ID, LESSON),
                         "live-schema-drift")


def test_schema_writable_property_type_drift_is_not_accepted():
    item = schema()
    item["properties"]["Area"]["type"] = "rich_text"
    assert_blocked_exact(lambda: _check_schema(item, SOURCE_ID, LESSON),
                         "live-schema-drift")


@pytest.mark.parametrize("result", [
    {"has_more": True, "results": []},
    {"has_more": None, "results": []},
    {"has_more": False},
])
def test_reconciliation_refuses_incomplete_and_ambiguous_shapes(result):
    expected = "ambiguous-lesson" if result.get("has_more") is False else "incomplete-reconciliation"
    assert_blocked_exact(lambda: _single(result, SOURCE_ID), expected)


@pytest.mark.parametrize("rows", [None, "not-a-list", [page(), page()]])
def test_reconciliation_ambiguous_rows_use_finite_reason(rows):
    assert_blocked_exact(lambda: _single({"has_more": False, "results": rows}, SOURCE_ID),
                         "ambiguous-lesson")


def test_reconciliation_empty_result_is_not_a_candidate():
    assert _single({"has_more": False, "results": []}, SOURCE_ID) is None


def test_reconciliation_single_result_keeps_page_identity():
    row = page()
    assert _single({"has_more": False, "results": [deepcopy(row)]}, SOURCE_ID) == row


class SearchClient:
    def __init__(self, rows):
        self.rows = rows
        self.title_queries = []
        self.lesson_queries = []

    def find_exact(self, title):
        self.title_queries.append(title)
        return {"has_more": False, "results": deepcopy(self.rows)}

    def find_lesson(self, number):
        self.lesson_queries.append(number)
        return {"has_more": False, "results": deepcopy(self.rows)}


def query_page(*, title="Other lesson", number=93):
    item = page()
    item["properties"] = {
        "Lesson Learned": {"type": "title", "title": [
            {"type": "text", "plain_text": title, "text": {"content": title}}
        ]},
        "Lesson ID": {"type": "unique_id", "unique_id": {"number": number, "prefix": "LL"}},
    }
    return item


def test_find_title_rejects_candidate_whose_canonical_title_differs():
    client = SearchClient([query_page(title="Unrelated lesson")])
    assert_blocked_exact(
        lambda: _find_title(client, SOURCE_ID, {"Lesson Learned": "Reviewed lesson"}),
        "query-identity-mismatch",
    )
    assert client.title_queries == ["Reviewed lesson"]


def test_find_title_accepts_exact_canonical_result():
    row = query_page(title="Reviewed lesson")
    client = SearchClient([row])
    assert _find_title(client, SOURCE_ID, {"Lesson Learned": "Reviewed lesson"}) == row
    assert client.title_queries == ["Reviewed lesson"]


def test_find_lesson_id_refuses_unreviewed_format():
    client = SearchClient([])
    assert_blocked_exact(lambda: _find_lesson_id(client, SOURCE_ID, "not-reviewed"),
                         "reviewed-target-lesson-mismatch")
    assert client.lesson_queries == []


def test_find_lesson_id_requires_matching_canonical_identity():
    client = SearchClient([query_page(number=93)])
    assert_blocked_exact(lambda: _find_lesson_id(client, SOURCE_ID, "LL-94"),
                         "query-identity-mismatch")
    assert client.lesson_queries == [94]


def test_find_lesson_id_accepts_exact_target():
    row = query_page(number=93)
    client = SearchClient([row])
    assert _find_lesson_id(client, SOURCE_ID, "LL-93") == row
    assert client.lesson_queries == [93]