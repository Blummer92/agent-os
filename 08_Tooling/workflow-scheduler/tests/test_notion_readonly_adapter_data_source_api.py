"""Issue #936 coverage for the current Notion Data Source read API."""

import urllib.error

import pytest

from workflow_scheduler.adapters import NotionReadOnlyAdapter, NotionReadOnlyAdapterError
from workflow_scheduler.adapters import notion_readonly_adapter as nrao
from workflow_scheduler.models import Task


def make_task(payload, retry_count=0):
    return Task(id="notion-936", workflow_id="workflow-936", type="read", owner="system", action="read:notion", idempotency_key="notion-936-key", payload=payload, retry_count=retry_count)


class FakeGet:
    def __init__(self, responses=None, exc=None):
        self.responses = list(responses or [])
        self.exc = exc
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        if self.exc:
            raise self.exc
        return self.responses.pop(0)


class FakePost:
    def __init__(self, responses=None, exc=None):
        self.responses = list(responses or [])
        self.exc = exc
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body, timeout))
        if self.exc:
            raise self.exc
        return self.responses.pop(0)


def test_pins_current_notion_api_version():
    assert nrao.NOTION_VERSION == "2026-03-11"


def test_get_data_source_uses_current_read_endpoint_and_distinct_identity():
    http_get = FakeGet([{"id": "ds-1", "name": "Lessons", "parent": {"type": "database_id", "database_id": "db-1"}, "properties": {}, "in_trash": False}])
    result = NotionReadOnlyAdapter(http_get=http_get).execute(make_task({"action": "get_data_source", "data_source_id": "ds-1"}))
    assert result["status"] == "success"
    assert result["output"]["parent"]["database_id"] == "db-1"
    assert http_get.calls[0][0] == "https://api.notion.com/v1/data_sources/ds-1"
    assert http_get.calls[0][1]["Notion-Version"] == "2026-03-11"


def test_query_data_source_uses_exact_current_endpoint_and_read_post_only():
    http_post = FakePost([{"results": [], "has_more": False, "next_cursor": None}])
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(make_task({"action": "query_data_source", "data_source_id": "ds-1"}))
    assert result["status"] == "success"
    assert http_post.calls[0][0] == "https://api.notion.com/v1/data_sources/ds-1/query"
    assert http_post.calls[0][1]["Content-Type"] == "application/json"


def test_query_data_source_passes_filter_sorts_and_property_selection():
    http_post = FakePost([{"results": [], "has_more": False, "next_cursor": None}])
    payload = {"action": "query_data_source", "data_source_id": "ds-1", "filter": {"property": "Status", "select": {"equals": "Ready"}}, "sorts": [{"property": "Name", "direction": "ascending"}], "filter_properties": ["Name", "Status"], "page_size": 25}
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(make_task(payload))
    assert result["status"] == "success"
    url, _, body, _ = http_post.calls[0]
    assert url.endswith("?filter_properties=Name&filter_properties=Status")
    assert body["filter"] == payload["filter"]
    assert body["sorts"] == payload["sorts"]


def test_query_data_source_keeps_cursors_opaque_and_bounds_pagination():
    http_post = FakePost([{"results": [{"id": "a"}], "has_more": True, "next_cursor": "opaque:1/+="}, {"results": [{"id": "b"}], "has_more": True, "next_cursor": "opaque:2/+="}])
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(make_task({"action": "query_data_source", "data_source_id": "ds-1", "page_size": 1, "max_pages": 2, "max_results": 2}))
    assert [row["id"] for row in result["output"]["results"]] == ["a", "b"]
    assert len(http_post.calls) == 2
    assert http_post.calls[1][2]["start_cursor"] == "opaque:1/+="
    assert result["output"]["has_more"] is True


def test_page_property_retrieval_is_bounded_and_cursor_aware():
    http_get = FakeGet([{"object": "list", "results": [{"object": "property_item", "id": "rel"}], "has_more": True, "next_cursor": "next relation cursor"}])
    result = NotionReadOnlyAdapter(http_get=http_get).execute(make_task({"action": "get_page_property", "page_id": "page-1", "property_id": "abc:def", "page_size": 50, "start_cursor": "opaque cursor"}))
    assert result["status"] == "success"
    assert "/pages/page-1/properties/abc%3Adef?" in http_get.calls[0][0]
    assert "start_cursor=opaque+cursor" in http_get.calls[0][0]


def test_get_page_preserves_parent_data_source_identity_for_bounded_source_verification():
    parent = {
        "type": "data_source_id",
        "data_source_id": "lessons-source-current",
        "database_id": "lessons-database-current",
    }
    result = NotionReadOnlyAdapter(
        http_get=FakeGet([{"id": "lesson-page", "parent": parent, "archived": False, "in_trash": False}])
    ).execute(make_task({"action": "get_page", "page_id": "lesson-page"}))

    assert result["status"] == "success"
    assert result["output"]["parent"] == parent


def test_archive_and_trash_compatibility_fields_are_preserved():
    result = NotionReadOnlyAdapter(http_get=FakeGet([{"id": "page-1", "archived": False, "in_trash": True}])).execute(make_task({"action": "get_page", "page_id": "page-1"}))
    assert result["output"]["archived"] is False
    assert result["output"]["in_trash"] is True


@pytest.mark.parametrize("status", [401, 403, 404])
def test_permanent_http_errors_are_failures(status):
    error = urllib.error.HTTPError("https://api.notion.com/v1/pages/p", status, "denied", {}, None)
    with pytest.raises(NotionReadOnlyAdapterError) as excinfo:
        nrao._raise_for_http_error(error, "Notion API")
    assert excinfo.value.is_transient is False


def test_429_preserves_retry_after_evidence_without_retry_loop():
    error = urllib.error.HTTPError("https://api.notion.com/v1/data_sources/d/query", 429, "rate limited", {"Retry-After": "17"}, None)
    try:
        nrao._raise_for_http_error(error, "Notion API")
    except NotionReadOnlyAdapterError as exc:
        result = NotionReadOnlyAdapter(http_get=FakeGet(exc=exc)).execute(make_task({"action": "get_page", "page_id": "p"}, retry_count=4))
    assert result["status"] == "retryable"
    assert result["retry_after"] == 17.0


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_5xx_errors_are_retryable(status):
    result = NotionReadOnlyAdapter(http_get=FakeGet(exc=NotionReadOnlyAdapterError(f"HTTP {status}", is_transient=True))).execute(make_task({"action": "get_page", "page_id": "p"}))
    assert result["status"] == "retryable"


def test_malformed_or_missing_required_response_fields_fail_cleanly():
    assert NotionReadOnlyAdapter(http_get=FakeGet([[]])).execute(make_task({"action": "get_page", "page_id": "p"}))["status"] == "failure"
    assert NotionReadOnlyAdapter(http_get=FakeGet([{}])).execute(make_task({"action": "get_data_source", "data_source_id": "d"}))["status"] == "failure"
    assert NotionReadOnlyAdapter(http_post_query_data_source=FakePost([{}])).execute(make_task({"action": "query_data_source", "data_source_id": "d"}))["status"] == "failure"


def test_unsupported_write_like_actions_never_call_network():
    http_get, http_post = FakeGet([{"id": "unused"}]), FakePost([{"results": []}])
    adapter = NotionReadOnlyAdapter(http_get=http_get, http_post_query_data_source=http_post)
    for action in ("create_page", "update_page", "archive_page", "delete_page", "patch"):
        assert adapter.execute(make_task({"action": action}))["status"] == "failure"
    assert http_get.calls == []
    assert http_post.calls == []


def test_invalid_bounds_fail_without_network():
    http_post = FakePost([{"results": []}])
    adapter = NotionReadOnlyAdapter(http_post_query_data_source=http_post)
    for payload in ({"action": "query_data_source", "data_source_id": "d", "page_size": 0}, {"action": "query_data_source", "data_source_id": "d", "max_pages": 21}, {"action": "query_data_source", "data_source_id": "d", "max_results": 2001}, {"action": "query_data_source", "data_source_id": "d", "filter_properties": "Name"}):
        assert adapter.execute(make_task(payload))["status"] == "failure"
    assert http_post.calls == []


def test_retired_query_database_action_is_not_registered():
    http_post = FakePost([{"results": [], "has_more": False, "next_cursor": None}])
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(
        make_task({"action": "query_database", "database_id": "db-1"})
    )
    assert result["status"] == "failure"
    assert "Unsupported action" in result["message"]
    assert http_post.calls == []


def test_query_data_source_rejects_missing_has_more():
    # #4016 R-1: a provider page without pagination metadata must fail, never
    # become an apparently complete read.
    http_post = FakePost([{"results": [{"id": "a"}]}])
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(
        make_task({"action": "query_data_source", "data_source_id": "ds-1"})
    )
    assert result["status"] == "failure"
    assert "pagination metadata is malformed" in result["message"]
    assert "missing required field 'has_more'" in result["message"]


@pytest.mark.parametrize(
    "has_more", [None, "false", 0, 1], ids=["null", "string", "zero", "one"]
)
def test_query_data_source_rejects_wrong_type_has_more(has_more):
    http_post = FakePost([{"results": [{"id": "a"}], "has_more": has_more}])
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(
        make_task({"action": "query_data_source", "data_source_id": "ds-1"})
    )
    assert result["status"] == "failure"
    assert "'has_more' must be a boolean" in result["message"]


def test_query_data_source_returns_oversized_page_whole_without_slicing():
    # #4016 R-2: the adapter reports the provider page whole; the consuming
    # layer owns the row bound and rejects it there.
    rows = [{"id": f"row-{n}"} for n in range(3)]
    http_post = FakePost([{"results": rows, "has_more": False, "next_cursor": None}])
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(
        make_task(
            {
                "action": "query_data_source",
                "data_source_id": "ds-1",
                "page_size": 1,
                "max_pages": 1,
                "max_results": 2,
            }
        )
    )
    assert result["status"] == "success"
    assert [row["id"] for row in result["output"]["results"]] == ["row-0", "row-1", "row-2"]
    assert result["output"]["has_more"] is False


def test_query_data_source_reports_cumulative_overflow_with_truthful_has_more():
    # The read stops at max_results, but the returned has_more is the
    # provider's own: more results remain, so no consumer may call this complete.
    http_post = FakePost(
        [
            {"results": [{"id": "a"}, {"id": "b"}], "has_more": True, "next_cursor": "c1"},
            {"results": [{"id": "c"}], "has_more": True, "next_cursor": "c2"},
        ]
    )
    result = NotionReadOnlyAdapter(http_post_query_data_source=http_post).execute(
        make_task(
            {
                "action": "query_data_source",
                "data_source_id": "ds-1",
                "page_size": 2,
                "max_pages": 2,
                "max_results": 3,
            }
        )
    )
    assert result["status"] == "success"
    assert [row["id"] for row in result["output"]["results"]] == ["a", "b", "c"]
    assert result["output"]["has_more"] is True
    assert result["output"]["next_cursor"] == "c2"
    assert len(http_post.calls) == 2
