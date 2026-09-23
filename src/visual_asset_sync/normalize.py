"""Normalize raw spreadsheet and Notion dictionaries into planner models."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from .models import ExistingAssetRecord, SourceAssetRecord

SUPPORTED_DRIVE_HOSTS = frozenset({"drive.google.com", "docs.google.com"})
_SUPPORTED_URL_SCHEMES = frozenset({"http", "https"})
DRIVE_FILE_ID_MIN_LENGTH = 20
DRIVE_FILE_ID_MAX_LENGTH = 128
MAX_TEXT_LENGTH = 2_048
MAX_SOURCE_ROW_LENGTH = 128
MAX_PAGE_ID_LENGTH = 256
_DRIVE_FILE_ID_RE = re.compile(
    rf"^[A-Za-z0-9_-]{{{DRIVE_FILE_ID_MIN_LENGTH},{DRIVE_FILE_ID_MAX_LENGTH}}}$"
)
_PATH_ID_RE = re.compile(r"/d/([^/]+)")
_ID_QUERY_KEYS = ("id",)

_KNOWN_EXISTING_FIELDS = {
    "page_id",
    "page_url",
    "drive_file_id",
    "drive_url",
    "asset_title",
    "approved_use",
    "asset_type",
    "human_review_status",
    "review_date",
}

_SOURCE_TEXT_FIELDS = (
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

_EXISTING_TEXT_FIELDS = (
    "page_url",
    "drive_file_id",
    "drive_url",
    "asset_title",
    "approved_use",
    "asset_type",
    "human_review_status",
    "review_date",
)


def is_valid_drive_file_id(value: str | None) -> bool:
    """Return True when value is an exact string shaped like a Drive File ID."""
    if type(value) is not str:
        return False
    return _DRIVE_FILE_ID_RE.fullmatch(value) is not None


def extract_drive_id_candidates(url: str | None) -> tuple[str, ...]:
    """Return distinct valid Drive IDs carried by one supported exact-string URL."""
    if type(url) is not str:
        return ()
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ()
    if parsed.scheme.lower() not in _SUPPORTED_URL_SCHEMES:
        return ()
    if host not in SUPPORTED_DRIVE_HOSTS:
        return ()

    candidates: list[str] = []
    for match in _PATH_ID_RE.finditer(parsed.path):
        _add_candidate(candidates, match.group(1))
    query = parse_qs(parsed.query)
    for key in _ID_QUERY_KEYS:
        for value in query.get(key, ()):
            _add_candidate(candidates, value)
    return tuple(candidates)


def _add_candidate(candidates: list[str], value: str) -> None:
    if is_valid_drive_file_id(value) and value not in candidates:
        candidates.append(value)


def extract_drive_id_from_url(url: str | None) -> str | None:
    """Return one unambiguous Drive ID, otherwise None."""
    candidates = extract_drive_id_candidates(url)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _require_exact_dict(raw: Any, record_kind: str) -> dict[str, Any]:
    if type(raw) is not dict:
        raise TypeError(f"{record_kind} must be an exact dictionary")
    for key in raw:
        if type(key) is not str:
            raise TypeError(f"{record_kind} keys must be exact strings")
    return raw


def _optional_text(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError(f"{field} must be an exact string or null")
    text = value.strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"{field} exceeds the text length limit")
    return text or None


def _required_text(
    raw: dict[str, Any], field: str, *, maximum_length: int
) -> str:
    value = raw.get(field)
    if type(value) is not str:
        raise TypeError(f"{field} must be an exact string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > maximum_length:
        raise ValueError(f"{field} exceeds the length limit")
    return text


def _excluded(raw: dict[str, Any]) -> bool:
    value = raw.get("excluded", False)
    if type(value) is not bool:
        raise TypeError("excluded must be an exact boolean")
    return value


def normalize_source_record(raw: dict[str, Any]) -> SourceAssetRecord:
    raw = _require_exact_dict(raw, "source record")
    values = {field: _optional_text(raw, field) for field in _SOURCE_TEXT_FIELDS}
    return SourceAssetRecord(
        source_row=_required_text(
            raw, "source_row", maximum_length=MAX_SOURCE_ROW_LENGTH
        ),
        **values,
        excluded=_excluded(raw),
    )


def normalize_existing_record(raw: dict[str, Any]) -> ExistingAssetRecord:
    raw = _require_exact_dict(raw, "existing record")
    values = {field: _optional_text(raw, field) for field in _EXISTING_TEXT_FIELDS}
    extra_fields = {
        key: value for key, value in raw.items() if key not in _KNOWN_EXISTING_FIELDS
    }
    return ExistingAssetRecord(
        page_id=_required_text(raw, "page_id", maximum_length=MAX_PAGE_ID_LENGTH),
        **values,
        extra_fields=extra_fields,
    )
