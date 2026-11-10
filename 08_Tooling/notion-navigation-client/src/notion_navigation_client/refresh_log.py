"""Pure functions: bounded, read-only chronology evidence from the Refresh Log tab.

The `Refresh Log` tab of the navigation-index sheet records when the cached
navigation index was refreshed from Notion. This module turns that tab's raw
rows into evidence a caller can reason about without a second data store:

- every entry keeps the sheet row's raw cells untouched, plus its 1-based
  source-row number, and entries stay in source-row order -- nothing is
  re-sorted;
- a timestamp is converted to UTC only when the raw string itself states its
  zone (`UTC`, `Z`, or a numeric offset). A timestamp that parses but states
  no zone is reported as ambiguous and never guessed; any other format is
  reported as unrecognized and left raw;
- the latest observed refresh is reported by source row and, only when every
  populated row carries explicit zone evidence, by timestamp as well.

The Refresh Log is navigation-cache evidence only. It is not a complete history
of teacher work, GitHub work, or Notion edits, and it never replaces live Notion
or GitHub verification.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .records import NAVIGATION_WARNING, header_row_index, rows_to_records, with_warning

TAB_REFRESH_LOG = "Refresh Log"
TIMESTAMP_COLUMN = "Refresh Date"

DEFAULT_LIMIT = 20
MAX_LIMIT = 200

STATUS_EXPLICIT_UTC = "explicit-utc"
STATUS_EXPLICIT_OFFSET = "explicit-offset"
STATUS_AMBIGUOUS = "ambiguous-timezone"
STATUS_UNRECOGNIZED = "unrecognized-format"
STATUS_MISSING = "missing"
TIMESTAMP_STATUSES = (
    STATUS_EXPLICIT_UTC,
    STATUS_EXPLICIT_OFFSET,
    STATUS_AMBIGUOUS,
    STATUS_UNRECOGNIZED,
    STATUS_MISSING,
)
_EXPLICIT_STATUSES = frozenset({STATUS_EXPLICIT_UTC, STATUS_EXPLICIT_OFFSET})

UNAVAILABLE_NO_ENTRIES = "no-entries"
UNAVAILABLE_COLUMN_MISSING = "timestamp-column-missing"
UNAVAILABLE_NOT_ALL_EXPLICIT = "timestamps-not-all-explicit"

COMPLETENESS_NOTICE = (
    "Refresh Log rows describe navigation-cache refreshes only. They are not a "
    "complete history of teacher work, GitHub work, or Notion edits, and they do "
    "not replace live Notion or GitHub verification."
)

# ISO-like date and time, optionally followed by an explicit zone. A date with
# no time is deliberately not matched: it names a day, not an instant.
_TIMESTAMP_RE = re.compile(
    r"""^
    (?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})
    [T\ ](?P<hour>\d{2}):(?P<minute>\d{2})
    (?::(?P<second>\d{2})(?:\.(?P<fraction>\d{1,6}))?)?
    \s*(?P<zone>Z|UTC|[+-]\d{2}:?\d{2})?
    $""",
    re.VERBOSE | re.IGNORECASE,
)
_MAX_OFFSET_MINUTES = 14 * 60


def validate_limit(limit: object) -> int:
    """Return `limit` when it is an int within 1..MAX_LIMIT, else raise ValueError."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    return limit


def _as_text(cell: object) -> str:
    if cell is None:
        return ""
    return cell if isinstance(cell, str) else str(cell)


def _parse_instant(text: str) -> tuple[str, datetime | None]:
    """Classify one timestamp string; return (status, aware-UTC datetime or None).

    A UTC datetime is produced only from explicit zone evidence in `text`.
    """
    if not text.strip():
        return STATUS_MISSING, None

    match = _TIMESTAMP_RE.match(text.strip())
    if match is None:
        return STATUS_UNRECOGNIZED, None

    parts = match.groupdict()
    fraction = parts["fraction"] or ""
    try:
        naive = datetime(
            int(parts["year"]),
            int(parts["month"]),
            int(parts["day"]),
            int(parts["hour"]),
            int(parts["minute"]),
            int(parts["second"] or 0),
            int(fraction.ljust(6, "0")) if fraction else 0,
        )
    except ValueError:
        return STATUS_UNRECOGNIZED, None

    zone = parts["zone"]
    if zone is None:
        return STATUS_AMBIGUOUS, None
    if zone.upper() in ("Z", "UTC"):
        return STATUS_EXPLICIT_UTC, naive.replace(tzinfo=timezone.utc)

    digits = zone[1:].replace(":", "")
    offset_minutes = int(digits[:2]) * 60 + int(digits[2:])
    if int(digits[2:]) >= 60 or offset_minutes > _MAX_OFFSET_MINUTES:
        return STATUS_UNRECOGNIZED, None
    sign = -1 if zone[0] == "-" else 1
    offset = timezone(sign * timedelta(minutes=offset_minutes))
    try:
        instant = naive.replace(tzinfo=offset).astimezone(timezone.utc)
    except OverflowError:  # e.g. 0001-01-01 00:00 +01:00 has no representable UTC instant
        return STATUS_UNRECOGNIZED, None
    return STATUS_EXPLICIT_OFFSET, instant


def _classify(raw: object) -> tuple[dict, datetime | None]:
    text = _as_text(raw)
    status, instant = _parse_instant(text)
    utc = instant.isoformat().replace("+00:00", "Z") if instant is not None else None
    return {"raw": text, "status": status, "utc": utc}, instant


def classify_timestamp(raw: object) -> dict:
    """Return `{"raw", "status", "utc"}` for one raw Refresh Date cell.

    `raw` is returned exactly as supplied (as text). `utc` is an ISO-8601 UTC
    string only when `status` is `explicit-utc` or `explicit-offset`; otherwise
    it is None. No timezone is ever assumed.
    """
    return _classify(raw)[0]


def _is_blank_row(row: list) -> bool:
    return not any(_as_text(cell).strip() for cell in row)


def _copy_entry(entry: dict) -> dict:
    return {**entry, "timestamp": dict(entry["timestamp"]), "record": dict(entry["record"])}


def build_refresh_log_evidence(rows: list[list[str]], *, limit: int = DEFAULT_LIMIT) -> dict:
    """Build bounded Refresh Log evidence from the raw rows of the tab.

    `rows` is the tab exactly as fetched (optional navigation-warning banner,
    header row, data rows). Returns a new dict on every call; `rows` is not
    modified. Raises ValueError when `limit` is not an int within 1..MAX_LIMIT.

    The returned `entries` are the last `limit` populated data rows in
    ascending source-row order. The bound applies to what is returned, not to
    the evidence used for the summary fields, which cover every populated row.
    """
    limit = validate_limit(limit)

    header_index = header_row_index(rows)
    header = list(rows[header_index]) if header_index is not None else []
    first_data_row = (header_index + 2) if header_index is not None else 1
    data_rows = rows[header_index + 1 :] if header_index is not None else []
    column_present = TIMESTAMP_COLUMN in header

    parsed: list[tuple[dict, datetime | None]] = []
    rows_outside_header = 0
    for offset, row in enumerate(data_rows):
        cells = list(row)
        # Only the header's columns form a record, so only they decide whether a
        # row is populated; content past the last header column is counted, not kept.
        if not _is_blank_row(cells[len(header) :]):
            rows_outside_header += 1
        if _is_blank_row(cells[: len(header)]):
            continue
        record = rows_to_records(header, [cells])[0]
        timestamp, instant = _classify(record.get(TIMESTAMP_COLUMN, ""))
        entry = with_warning(
            {"source_row": first_data_row + offset, "timestamp": timestamp, "record": record}
        )
        parsed.append((entry, instant))

    status_counts = {status: 0 for status in TIMESTAMP_STATUSES}
    for entry, _ in parsed:
        status_counts[entry["timestamp"]["status"]] += 1

    by_source_row = _copy_entry(parsed[-1][0]) if parsed else None
    by_timestamp = None
    order_matches: bool | None = None
    if not parsed:
        unavailable_reason = UNAVAILABLE_NO_ENTRIES
    elif not column_present:
        unavailable_reason = UNAVAILABLE_COLUMN_MISSING
    elif any(entry["timestamp"]["status"] not in _EXPLICIT_STATUSES for entry, _ in parsed):
        # One unresolved row could be newer than every explicit one, so no
        # timestamp-based "latest" or ordering claim is made.
        unavailable_reason = UNAVAILABLE_NOT_ALL_EXPLICIT
    else:
        unavailable_reason = None
        instants = [instant for _, instant in parsed]
        order_matches = all(earlier <= later for earlier, later in zip(instants, instants[1:]))
        # Equal instants resolve to the later source row, deterministically.
        latest_entry, _ = max(parsed, key=lambda pair: (pair[1], pair[0]["source_row"]))
        by_timestamp = _copy_entry(latest_entry)

    window = [_copy_entry(entry) for entry, _ in parsed[-limit:]]

    return {
        "tab": TAB_REFRESH_LOG,
        "navigation_warning": NAVIGATION_WARNING,
        "completeness_notice": COMPLETENESS_NOTICE,
        "ordering": "source-row",
        "window": "last-populated-source-rows",
        "limit": limit,
        "total_populated_rows": len(parsed),
        "returned_rows": len(window),
        "truncated": len(parsed) > len(window),
        "rows_with_cells_outside_header": rows_outside_header,
        "timestamp_column": TIMESTAMP_COLUMN,
        "timestamp_column_present": column_present,
        "timestamp_status_counts": status_counts,
        "source_order_matches_timestamp_order": order_matches,
        "latest_observed_refresh": {
            "by_source_row": by_source_row,
            "by_timestamp": by_timestamp,
            "by_timestamp_unavailable_reason": unavailable_reason,
            "agree": (
                by_source_row["source_row"] == by_timestamp["source_row"]
                if by_source_row is not None and by_timestamp is not None
                else None
            ),
        },
        "entries": window,
    }
