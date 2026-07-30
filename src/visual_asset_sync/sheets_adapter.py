"""Read-only Google Sheets extraction for visual asset reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from .models import SourceAssetRecord
from .normalize import normalize_source_record

READ_ONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
MAX_ROWS_PER_REQUEST = 10_000
MAX_SPREADSHEET_ID_LENGTH = 512
MAX_WORKSHEET_NAME_LENGTH = 256
_COLUMN_RE = re.compile(r"^[A-Z]{1,3}$")

SOURCE_TEXT_FIELDS = (
    "drive_file_id",
    "drive_url",
    "file_name",
    "approved_use",
    "audience",
    "review_status",
    "review_date",
    "visual_rationale",
    "worksheet_fit",
    "slideshow_fit",
    "poster_fit",
    "format_decision_notes",
)
ALLOWED_TARGET_FIELDS = frozenset((*SOURCE_TEXT_FIELDS, "excluded"))
REQUIRED_TARGET_FIELDS = frozenset(SOURCE_TEXT_FIELDS)


class SheetAdapterError(Exception):
    """Base error for deterministic Sheet adapter failures."""


class SheetReadError(SheetAdapterError):
    """Raised when the read-only Sheets boundary fails."""


class SheetSchemaError(SheetAdapterError):
    """Raised when headers or configured mapping are invalid."""


class SheetRowError(SheetAdapterError):
    """Raised when one data row cannot satisfy the source contract."""


@dataclass(frozen=True)
class SheetReadRequest:
    """One explicit, bounded read against a single worksheet range."""

    spreadsheet_id: str
    worksheet_name: str
    end_column: str
    end_row: int
    start_row: int = 1

    def __post_init__(self) -> None:
        if type(self.spreadsheet_id) is not str:
            raise TypeError("spreadsheet_id must be an exact string")
        spreadsheet_id = self.spreadsheet_id.strip()
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id must not be empty")
        if len(spreadsheet_id) > MAX_SPREADSHEET_ID_LENGTH:
            raise ValueError("spreadsheet_id exceeds the length limit")

        if type(self.worksheet_name) is not str:
            raise TypeError("worksheet_name must be an exact string")
        worksheet_name = self.worksheet_name.strip()
        if not worksheet_name:
            raise ValueError("worksheet_name must not be empty")
        if len(worksheet_name) > MAX_WORKSHEET_NAME_LENGTH:
            raise ValueError("worksheet_name exceeds the length limit")
        if any(ord(character) < 32 for character in worksheet_name):
            raise ValueError("worksheet_name contains control characters")

        if type(self.end_column) is not str:
            raise TypeError("end_column must be an exact string")
        end_column = self.end_column.strip().upper()
        if _COLUMN_RE.fullmatch(end_column) is None:
            raise ValueError("end_column must be an A1 column label")

        if type(self.start_row) is not int:
            raise TypeError("start_row must be an exact integer")
        if type(self.end_row) is not int:
            raise TypeError("end_row must be an exact integer")
        if self.start_row < 1:
            raise ValueError("start_row must be positive")
        if self.end_row < self.start_row:
            raise ValueError("end_row must not precede start_row")
        if self.end_row - self.start_row + 1 > MAX_ROWS_PER_REQUEST:
            raise ValueError("requested row range exceeds the adapter limit")

        object.__setattr__(self, "spreadsheet_id", spreadsheet_id)
        object.__setattr__(self, "worksheet_name", worksheet_name)
        object.__setattr__(self, "end_column", end_column)

    @property
    def a1_range(self) -> str:
        escaped_name = self.worksheet_name.replace("'", "''")
        return (
            f"'{escaped_name}'!A{self.start_row}:"
            f"{self.end_column}{self.end_row}"
        )


class SheetValuesReader(Protocol):
    """Minimal read-only boundary used by the extraction layer."""

    def fetch_values(self, request: SheetReadRequest) -> list[list[Any]]:
        """Return rows for one explicit bounded request."""


class GoogleSheetsValuesReader:
    """Read-only Sheets API implementation using values.get only."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def fetch_values(self, request: SheetReadRequest) -> list[list[Any]]:
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=request.spreadsheet_id,
                    range=request.a1_range,
                    majorDimension="ROWS",
                    valueRenderOption="FORMATTED_VALUE",
                    dateTimeRenderOption="FORMATTED_STRING",
                )
                .execute()
            )
        except Exception as exc:
            raise SheetReadError("Google Sheets read failed") from exc

        if type(response) is not dict:
            raise SheetReadError("Google Sheets response must be an exact dictionary")
        values = response.get("values", [])
        return _require_exact_rows(values)


def extract_source_records(
    reader: SheetValuesReader,
    request: SheetReadRequest,
    header_map: dict[str, str],
) -> tuple[SourceAssetRecord, ...]:
    """Read and map one bounded worksheet range into planner records."""
    values = reader.fetch_values(request)
    return map_sheet_values(
        values,
        header_map,
        header_sheet_row=request.start_row,
    )


def map_sheet_values(
    values: list[list[Any]],
    header_map: dict[str, str],
    *,
    header_sheet_row: int = 1,
) -> tuple[SourceAssetRecord, ...]:
    """Purely map header + data rows into strict planner records."""
    rows = _require_exact_rows(values)
    if type(header_sheet_row) is not int:
        raise TypeError("header_sheet_row must be an exact integer")
    if header_sheet_row < 1:
        raise ValueError("header_sheet_row must be positive")
    if not rows:
        raise SheetSchemaError("sheet values must include a header row")

    configured = _validate_header_map(header_map)
    headers = _normalize_headers(rows[0])
    index_by_header = {header: index for index, header in enumerate(headers)}

    configured_headers = set(configured.values())
    if not configured_headers.issubset(index_by_header):
        raise SheetSchemaError("sheet is missing configured headers")
    if set(headers) != configured_headers:
        raise SheetSchemaError("sheet contains unexpected headers")

    records: list[SourceAssetRecord] = []
    for offset, row in enumerate(rows[1:], start=1):
        sheet_row = header_sheet_row + offset
        if _is_blank_row(row):
            continue
        if len(row) > len(headers) and not _is_blank_row(row[len(headers) :]):
            raise SheetRowError("sheet row contains cells beyond the header")

        raw: dict[str, Any] = {"source_row": f"{sheet_row}"}
        for target_field, source_header in configured.items():
            index = index_by_header[source_header]
            cell = row[index] if index < len(row) else None
            if target_field == "excluded":
                raw[target_field] = _parse_excluded(cell)
            else:
                raw[target_field] = _text_cell(cell, target_field)
        if "excluded" not in configured:
            raw["excluded"] = False

        try:
            records.append(normalize_source_record(raw))
        except (TypeError, ValueError) as exc:
            raise SheetRowError("sheet row is incompatible with source contract") from exc

    return tuple(records)


def _validate_header_map(header_map: dict[str, str]) -> dict[str, str]:
    if type(header_map) is not dict:
        raise TypeError("header_map must be an exact dictionary")

    normalized: dict[str, str] = {}
    for target_field, source_header in header_map.items():
        if type(target_field) is not str:
            raise TypeError("header_map keys must be exact strings")
        if target_field not in ALLOWED_TARGET_FIELDS:
            raise SheetSchemaError("header_map contains an unsupported target field")
        if type(source_header) is not str:
            raise TypeError("header_map values must be exact strings")
        header = source_header.strip()
        if not header:
            raise SheetSchemaError("header_map values must not be empty")
        normalized[target_field] = header

    if not REQUIRED_TARGET_FIELDS.issubset(normalized):
        raise SheetSchemaError("header_map is missing required target fields")
    if len(set(normalized.values())) != len(normalized):
        raise SheetSchemaError("header_map assigns one header more than once")
    return normalized


def _normalize_headers(row: list[Any]) -> tuple[str, ...]:
    headers: list[str] = []
    for cell in row:
        if type(cell) is not str:
            raise SheetSchemaError("sheet headers must be exact strings")
        header = cell.strip()
        if not header:
            raise SheetSchemaError("sheet headers must not be empty")
        headers.append(header)
    if len(set(headers)) != len(headers):
        raise SheetSchemaError("sheet contains duplicate headers")
    return tuple(headers)


def _require_exact_rows(values: Any) -> list[list[Any]]:
    if type(values) is not list:
        raise SheetReadError("sheet values must be an exact list")
    for row in values:
        if type(row) is not list:
            raise SheetReadError("sheet rows must be exact lists")
    return values


def _text_cell(cell: Any, field: str) -> str | None:
    if cell is None:
        return None
    if type(cell) is not str:
        raise SheetRowError(f"{field} cell must be an exact string or null")
    return cell


def _parse_excluded(cell: Any) -> bool:
    if cell is None:
        return False
    if type(cell) is bool:
        return cell
    if type(cell) is not str:
        raise SheetRowError("excluded cell must be a boolean, TRUE, FALSE, or blank")
    value = cell.strip()
    if not value:
        return False
    if value == "TRUE":
        return True
    if value == "FALSE":
        return False
    raise SheetRowError("excluded cell must be a boolean, TRUE, FALSE, or blank")


def _is_blank_row(row: list[Any]) -> bool:
    for cell in row:
        if cell is None:
            continue
        if type(cell) is str and not cell.strip():
            continue
        return False
    return True
