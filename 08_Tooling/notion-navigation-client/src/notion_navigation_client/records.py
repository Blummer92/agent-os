"""Pure functions: turn raw sheet rows into keyed records.

Navigation-index tabs may be exported in either of these forms:

- row 1 is the header row, followed by data rows
- row 1 is the standard navigation warning banner, row 2 is the header row,
  followed by data rows

The parser supports both forms so the read client can work against the live
sheet and older fixture-style rows.
"""
from __future__ import annotations

NAVIGATION_WARNING = (
    "Navigation aid only. Verify live state in Notion before updating "
    "readiness, status, ownership, or curriculum decisions."
)


def is_navigation_warning_row(row: list[str]) -> bool:
    """Return True when a sheet row is the standard navigation warning banner."""
    non_empty_cells = [str(cell).strip() for cell in row if str(cell).strip()]
    return len(non_empty_cells) == 1 and non_empty_cells[0] == NAVIGATION_WARNING


def split_header_and_data(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Return the header row and data rows, skipping the warning banner if present."""
    if not rows:
        return [], []

    header_index = 1 if is_navigation_warning_row(rows[0]) else 0
    if len(rows) <= header_index:
        return [], []

    return rows[header_index], rows[header_index + 1 :]


def rows_to_records(header_row: list[str], data_rows: list[list[str]]) -> list[dict]:
    """Zip a header row against each data row. Missing trailing cells become ''."""
    records = []
    for row in data_rows:
        padded = row + [""] * (len(header_row) - len(row))
        records.append(dict(zip(header_row, padded)))
    return records


def index_by(records: list[dict], key_field: str) -> dict[str, dict]:
    """Build a lookup keyed on one field. Later duplicate keys overwrite earlier ones."""
    return {record[key_field]: record for record in records if record.get(key_field)}


def with_warning(record: dict | None) -> dict | None:
    """Attach the navigation-aid warning to a record without mutating the original."""
    if record is None:
        return None
    return {**record, "navigation_warning": NAVIGATION_WARNING}
