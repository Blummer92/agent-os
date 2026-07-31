"""Offline tests for the bounded read-only Notion adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual_asset_sync.models import ExistingAssetRecord, SourceAssetRecord
from visual_asset_sync.notion_adapter import (
    InjectedNotionDataSourceReader,
    NotionConfigurationError,
    NotionPaginationError,
    NotionRateLimitError,
    NotionReadError,
    NotionReadRequest,
    NotionRecordError,
    NotionRetryLimitError,
    NotionSchemaError,
    SUPPORTED_NOTION_VERSION,
    read_existing_assets,
)
from visual_asset_sync.plan import build_reconciliation_plan

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "notion_visual_asset_pages.json"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FakeReader:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def query_data_source(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _page_response(results, *, has_more=False, next_cursor=None):
    return {
        "results": results,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def test_request_defaults_and_exact_identifier():
    request = NotionReadRequest(" fixture-source ")
    assert request.data_source_id == "fixture-source"
    assert request.notion_version == SUPPORTED_NOTION_VERSION
    assert request.page_size == 25
    assert request.maximum_pages == 25
    assert request.maximum_records == 625
    assert request.maximum_retries == 2
    assert request.maximum_total_retry_delay == 30.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data_source_id": ""},
        {"data_source_id": object()},
        {"data_source_id": "x", "notion_version": "2022-06-28"},
        {"data_source_id": "x", "page_size": 101},
        {"data_source_id": "x", "page_size": True},
        {"data_source_id": "x", "maximum_pages": True},
        {"data_source_id": "x", "maximum_records": True},
        {"data_source_id": "x", "maximum_retries": True},
        {"data_source_id": "x", "maximum_total_retry_delay": object()},
        {"data_source_id": "x", "maximum_total_retry_delay": -1},
        {"data_source_id": "x", "maximum_total_retry_delay": float("inf")},
    ],
)
def test_invalid_request_configuration_fails_closed(kwargs):
    with pytest.raises(NotionConfigurationError):
        NotionReadRequest(**kwargs)


def test_page_size_100_is_allowed():
    assert NotionReadRequest("x", page_size=100).page_size == 100


def test_injected_reader_constructs_without_call_and_forwards_exact_values():
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return _page_response([])

    reader = InjectedNotionDataSourceReader(query)
    assert calls == []
    request = NotionReadRequest("source", page_size=37)
    assert read_existing_assets(reader, request, {"asset_title": "Title"}) == ()
    assert calls == [
        {
            "data_source_id": "source",
            "notion_version": SUPPORTED_NOTION_VERSION,
            "page_size": 37,
            "start_cursor": None,
        }
    ]


def test_reader_exposes_no_write_methods():
    reader = InjectedNotionDataSourceReader(lambda **_: _page_response([]))
    for name in (
        "create",
        "update",
        "archive",
        "delete",
        "comment",
        "upload",
        "share",
        "schema",
    ):
        assert not hasattr(reader, name)


def test_external_failure_is_sanitized_without_chained_cause():
    def query(**_):
        raise RuntimeError("secret token and raw payload")

    reader = InjectedNotionDataSourceReader(query)
    with pytest.raises(NotionReadError) as caught:
        read_existing_assets(reader, NotionReadRequest("source"), {"asset_title": "Title"})
    assert str(caught.value) == "Notion read failed"
    assert caught.value.__cause__ is None
    assert "secret token" not in str(caught.value)


def test_valid_fixture_maps_and_preserves_extra_fields():
    fixture = _fixture()
    reader = FakeReader([_page_response([fixture["pages"][0]])])
    records = read_existing_assets(
        reader,
        NotionReadRequest("source"),
        fixture["mapping"],
        required_fields=frozenset({"asset_title", "drive_file_id"}),
    )
    assert len(records) == 1
    record = records[0]
    assert type(record) is ExistingAssetRecord
    assert record.page_id == "fixture-page-001"
    assert record.page_url == "https://www.notion.so/fixture-page-001"
    assert record.drive_file_id == "fixtureDriveFileId_000001"
    assert record.drive_url.endswith("fixtureDriveFileId_000001/view")
    assert record.asset_title == "Camera Diagram"
    assert record.human_review_status == "Reviewed"
    assert record.review_date == "2026-07-30"
    assert record.extra_fields["Teacher Visible"] is True
    assert record.extra_fields["Revision Count"] == 2


def test_multiple_pages_preserve_order_and_forward_opaque_cursor():
    fixture = _fixture()
    reader = FakeReader(
        [
            _page_response([fixture["pages"][0]], has_more=True, next_cursor="opaque-A"),
            _page_response([fixture["pages"][1]]),
        ]
    )
    records = read_existing_assets(reader, NotionReadRequest("source"), fixture["mapping"])
    assert [record.page_id for record in records] == ["fixture-page-001", "fixture-page-002"]
    assert reader.calls[1]["start_cursor"] == "opaque-A"


def test_empty_result_returns_empty_tuple():
    assert read_existing_assets(
        FakeReader([_page_response([])]),
        NotionReadRequest("source"),
        {"asset_title": "Title"},
    ) == ()


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        ([], NotionSchemaError),
        ({"results": {}, "has_more": False, "next_cursor": None}, NotionSchemaError),
        ({"results": [1], "has_more": False, "next_cursor": None}, NotionSchemaError),
        ({"results": [], "has_more": 1, "next_cursor": None}, NotionPaginationError),
        ({"results": [], "has_more": True}, NotionPaginationError),
        ({"results": [], "has_more": True, "next_cursor": ""}, NotionPaginationError),
        ({"results": [], "has_more": False, "next_cursor": "x"}, NotionPaginationError),
    ],
)
def test_malformed_page_metadata_fails_closed(response, error_type):
    with pytest.raises(error_type):
        read_existing_assets(
            FakeReader([response]),
            NotionReadRequest("source"),
            {"asset_title": "Title"},
        )


def test_repeated_cursor_and_cycle_fail_closed():
    responses = [
        _page_response([], has_more=True, next_cursor="A"),
        _page_response([], has_more=True, next_cursor="B"),
        _page_response([], has_more=True, next_cursor="A"),
    ]
    with pytest.raises(NotionPaginationError, match="cursor repeated"):
        read_existing_assets(
            FakeReader(responses),
            NotionReadRequest("source", maximum_pages=5),
            {"asset_title": "Title"},
        )


def test_page_and_record_limits_fail_closed():
    with pytest.raises(NotionPaginationError, match="maximum page"):
        read_existing_assets(
            FakeReader([_page_response([], has_more=True, next_cursor="A")]),
            NotionReadRequest("source", maximum_pages=1),
            {"asset_title": "Title"},
        )
    fixture = _fixture()
    with pytest.raises(NotionPaginationError, match="maximum record"):
        read_existing_assets(
            FakeReader([_page_response(fixture["pages"])]),
            NotionReadRequest("source", maximum_records=1),
            fixture["mapping"],
        )


def test_page_identity_and_property_shape_failures():
    fixture = _fixture()
    page = dict(fixture["pages"][0])
    page.pop("id")
    with pytest.raises(NotionRecordError):
        read_existing_assets(FakeReader([_page_response([page])]), NotionReadRequest("x"), fixture["mapping"])

    page = dict(fixture["pages"][0], url=7)
    with pytest.raises(NotionRecordError):
        read_existing_assets(FakeReader([_page_response([page])]), NotionReadRequest("x"), fixture["mapping"])

    page = dict(fixture["pages"][0], properties=[])
    with pytest.raises(NotionRecordError):
        read_existing_assets(FakeReader([_page_response([page])]), NotionReadRequest("x"), fixture["mapping"])


def test_missing_page_url_and_optional_property_are_allowed():
    fixture = _fixture()
    records = read_existing_assets(
        FakeReader([_page_response([fixture["pages"][1]])]),
        NotionReadRequest("source"),
        fixture["mapping"],
    )
    assert records[0].page_url is None
    assert records[0].review_date is None


def test_required_property_missing_fails_closed():
    fixture = _fixture()
    with pytest.raises(NotionRecordError, match="required mapped property"):
        read_existing_assets(
            FakeReader([_page_response([fixture["pages"][1]])]),
            NotionReadRequest("source"),
            fixture["mapping"],
            required_fields=frozenset({"review_date"}),
        )


@pytest.mark.parametrize(
    "mapping,required",
    [({}, frozenset()), ({"unknown": "Title"}, frozenset()), ({"asset_title": "X", "drive_url": "X"}, frozenset()), ({"asset_title": "Title"}, {"asset_title"}), ({"asset_title": "Title"}, frozenset({"drive_url"})),
    ],
)
def test_mapping_configuration_fails_closed(mapping, required):
    with pytest.raises(NotionConfigurationError):
        read_existing_assets(
            FakeReader([_page_response([])]),
            NotionReadRequest("source"),
            mapping,
            required_fields=required,
        )


def test_unsupported_and_malformed_property_values_fail_closed():
    base = {"id": "page", "url": None, "properties": {"Title": {"type": "formula", "formula": {}}}}
    with pytest.raises(NotionRecordError, match="unsupported"):
        read_existing_assets(FakeReader([_page_response([base])]), NotionReadRequest("x"), {"asset_title": "Title"})
    base["properties"]["Title"] = {"type": "title", "title": [{}]}
    with pytest.raises(NotionRecordError, match="fragment"):
        read_existing_assets(FakeReader([_page_response([base])]), NotionReadRequest("x"), {"asset_title": "Title"})


def test_rate_limit_retries_use_exact_delays_and_reset_per_page():
    fixture = _fixture()
    reader = FakeReader(
        [
            NotionRateLimitError(1.5),
            _page_response([fixture["pages"][0]], has_more=True, next_cursor="A"),
            NotionRateLimitError(2),
            _page_response([fixture["pages"][1]]),
        ]
    )
    delays = []
    records = read_existing_assets(
        reader,
        NotionReadRequest("source", maximum_retries=1, maximum_total_retry_delay=2),
        fixture["mapping"],
        sleep=delays.append,
    )
    assert len(records) == 2
    assert delays == [1.5, 2.0]


def test_retry_count_and_total_delay_limits_fail_closed():
    with pytest.raises(NotionRetryLimitError, match="retry count"):
        read_existing_assets(
            FakeReader([NotionRateLimitError(0), NotionRateLimitError(0)]),
            NotionReadRequest("source", maximum_retries=1),
            {"asset_title": "Title"},
            sleep=lambda _: None,
        )
    with pytest.raises(NotionRetryLimitError, match="retry delay"):
        read_existing_assets(
            FakeReader([NotionRateLimitError(2)]),
            NotionReadRequest("source", maximum_total_retry_delay=1),
            {"asset_title": "Title"},
            sleep=lambda _: None,
        )


def test_non_rate_limit_failure_is_not_retried():
    reader = FakeReader([RuntimeError("raw secret")])
    with pytest.raises(NotionReadError):
        read_existing_assets(reader, NotionReadRequest("source"), {"asset_title": "Title"})
    assert len(reader.calls) == 1


def test_planner_smoke_and_one_collection_for_many_sources():
    fixture = _fixture()
    reader = FakeReader([_page_response([fixture["pages"][0]])])
    existing = read_existing_assets(reader, NotionReadRequest("source"), fixture["mapping"])
    sources = [
        SourceAssetRecord(source_row="2", drive_file_id="fixtureDriveFileId_000001"),
        SourceAssetRecord(source_row="3", drive_file_id="fixtureDriveFileId_000003"),
    ]
    plan = build_reconciliation_plan(sources, existing)
    assert len(plan.entries) == 2
    assert len(reader.calls) == 1
