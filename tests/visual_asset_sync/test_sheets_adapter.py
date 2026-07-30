"""Focused tests for fixture-first, read-only Sheets extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual_asset_sync.models import ReconciliationResult
from visual_asset_sync.reconcile import build_plan
from visual_asset_sync.sheets_adapter import (
    GoogleSheetsValuesReader,
    SheetReadError,
    SheetReadRequest,
    SheetRowError,
    SheetSchemaError,
    extract_source_records,
    map_sheet_values,
)

HEADER_MAP = {
    "drive_file_id": "Drive File ID",
    "drive_url": "Drive URL",
    "file_name": "File Name",
    "approved_use": "Approved Use",
    "audience": "Audience",
    "review_status": "Review Status",
    "review_date": "Review Date",
    "visual_rationale": "Visual Rationale",
    "worksheet_fit": "Worksheet Fit",
    "slideshow_fit": "Slideshow Fit",
    "poster_fit": "Poster Fit",
    "format_decision_notes": "Format Decision Notes",
    "excluded": "Excluded",
}


def fixture_values() -> list[list[object]]:
    path = Path(__file__).parent / "fixtures" / "approved_use_review_values.json"
    return json.loads(path.read_text())


def test_fixture_rows_map_to_source_records_in_order() -> None:
    records = map_sheet_values(fixture_values(), HEADER_MAP)
    assert [record.source_row for record in records] == ["2", "3"]
    assert records[0].file_name == "camera-angle.png"
    assert records[1].excluded is True


def test_empty_optional_cells_become_none() -> None:
    records = map_sheet_values(fixture_values(), HEADER_MAP)
    assert records[1].drive_url is None
    assert records[1].review_date is None


def test_drive_values_pass_through_without_validation_or_repair() -> None:
    records = map_sheet_values(fixture_values(), HEADER_MAP)
    assert records[1].drive_file_id == "bad-id"
    assert build_plan([records[1]], [])[0].result is ReconciliationResult.EXCLUDED


def test_planner_smoke_uses_extracted_valid_identity() -> None:
    records = map_sheet_values(fixture_values(), HEADER_MAP)
    assert (
        build_plan([records[0]], [])[0].result
        is ReconciliationResult.CREATE_MISSING
    )


def test_blank_rows_are_skipped_but_sheet_row_numbers_are_preserved() -> None:
    values = fixture_values()
    values.insert(1, ["" for _ in values[0]])
    records = map_sheet_values(values, HEADER_MAP, header_sheet_row=4)
    assert [record.source_row for record in records] == ["6", "7"]


def test_header_and_cell_whitespace_are_handled_explicitly() -> None:
    values = fixture_values()
    values[0] = [f"  {header}  " for header in values[0]]
    values[1][-1] = "  FALSE  "
    values[1][2] = "  camera-angle.png  "
    records = map_sheet_values(values, HEADER_MAP)
    assert records[0].file_name == "camera-angle.png"
    assert records[0].excluded is False


def test_missing_required_header_fails_closed() -> None:
    values = fixture_values()
    values[0][0] = "Wrong"
    with pytest.raises(SheetSchemaError, match="missing configured headers"):
        map_sheet_values(values, HEADER_MAP)


def test_duplicate_header_fails_closed() -> None:
    values = fixture_values()
    values[0][1] = values[0][0]
    with pytest.raises(SheetSchemaError, match="duplicate headers"):
        map_sheet_values(values, HEADER_MAP)


def test_unexpected_header_fails_closed() -> None:
    values = fixture_values()
    values[0].append("Unexpected")
    values[1].append("x")
    values[2].append("x")
    with pytest.raises(SheetSchemaError, match="unexpected headers"):
        map_sheet_values(values, HEADER_MAP)


def test_malformed_boolean_fails_closed() -> None:
    values = fixture_values()
    values[1][-1] = "yes"
    with pytest.raises(SheetRowError, match="excluded cell"):
        map_sheet_values(values, HEADER_MAP)


def test_unsupported_cell_type_fails_without_coercion() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise AssertionError("must not stringify")

        def __repr__(self) -> str:
            raise AssertionError("must not repr")

        def __bool__(self) -> bool:
            raise AssertionError("must not test truthiness")

    values = fixture_values()
    values[1][2] = Hostile()
    with pytest.raises(SheetRowError, match="file_name cell"):
        map_sheet_values(values, HEADER_MAP)


def test_short_rows_treat_missing_optional_cells_as_empty() -> None:
    values = fixture_values()
    values[2] = values[2][:3]
    records = map_sheet_values(values, HEADER_MAP)
    assert records[1].approved_use is None
    assert records[1].excluded is False


def test_cells_beyond_header_fail_closed() -> None:
    values = fixture_values()
    values[1].append("orphan")
    with pytest.raises(SheetRowError, match="beyond the header"):
        map_sheet_values(values, HEADER_MAP)


def test_header_map_must_cover_every_text_contract_field() -> None:
    mapping = dict(HEADER_MAP)
    mapping.pop("audience")
    with pytest.raises(SheetSchemaError, match="missing required target fields"):
        map_sheet_values(fixture_values(), mapping)


def test_request_builds_bounded_quoted_a1_range() -> None:
    request = SheetReadRequest(
        " sheet-id ",
        "Approved Use Review's",
        "n",
        100,
        start_row=1,
    )
    assert request.spreadsheet_id == "sheet-id"
    assert request.a1_range == "'Approved Use Review''s'!A1:N100"


def test_request_rejects_unbounded_row_count() -> None:
    with pytest.raises(ValueError, match="exceeds the adapter limit"):
        SheetReadRequest("sheet-id", "Tab", "N", 10_001)


class FakeExecute:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def execute(self) -> object:
        if self.error:
            raise self.error
        return self.payload


class FakeValues:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get(self, **kwargs: object) -> FakeExecute:
        self.calls.append(kwargs)
        return FakeExecute(self.payload, self.error)


class FakeSpreadsheets:
    def __init__(self, values: FakeValues) -> None:
        self._values = values

    def values(self) -> FakeValues:
        return self._values


class FakeService:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.values_api = FakeValues(payload, error)

    def spreadsheets(self) -> FakeSpreadsheets:
        return FakeSpreadsheets(self.values_api)


def test_google_reader_uses_values_get_and_no_write_method() -> None:
    service = FakeService({"values": fixture_values()})
    reader = GoogleSheetsValuesReader(service)
    request = SheetReadRequest("sheet-id", "Approved Use Review", "N", 100)
    records = extract_source_records(reader, request, HEADER_MAP)

    assert len(records) == 2
    assert service.values_api.calls == [
        {
            "spreadsheetId": "sheet-id",
            "range": "'Approved Use Review'!A1:N100",
            "majorDimension": "ROWS",
            "valueRenderOption": "FORMATTED_VALUE",
            "dateTimeRenderOption": "FORMATTED_STRING",
        }
    ]
    assert not hasattr(service.values_api, "update")
    assert not hasattr(service.values_api, "append")


def test_google_reader_translates_access_failure_deterministically() -> None:
    reader = GoogleSheetsValuesReader(
        FakeService(error=RuntimeError("secret detail"))
    )
    with pytest.raises(SheetReadError, match="Google Sheets read failed"):
        reader.fetch_values(SheetReadRequest("sheet-id", "Tab", "N", 100))
