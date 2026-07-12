"""Pure functions: turn raw sheet rows into keyed records.

Every tab in the navigation index is a header row plus data rows, so one
parser covers all of them -- no per-tab bespoke parsing needed.
"""
from __future__ import annotations

NAVIGATION_WARNING = (
    "Navigation aid only. Verify live state in Notion before updating "
    "readiness, status, ownership, or curriculum decisions."
)


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
