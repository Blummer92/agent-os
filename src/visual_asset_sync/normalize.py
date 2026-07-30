"""Normalize raw spreadsheet and Notion dictionaries into planner models."""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from .models import ExistingAssetRecord, SourceAssetRecord

# Only these hosts may establish Drive identity. A `/d/<id>` path segment or an
# `id=<id>` query parameter on any other host is not Drive identity evidence.
SUPPORTED_DRIVE_HOSTS = frozenset({"drive.google.com", "docs.google.com"})

_SUPPORTED_URL_SCHEMES = frozenset({"http", "https"})

# Drive File IDs are opaque base64url-style tokens drawn from [A-Za-z0-9_-].
# Real IDs observed in practice run roughly 25-44 characters. The bounds below
# are deliberately wider than any known form so the rule rejects obviously
# malformed tokens without overfitting to one exact length.
DRIVE_FILE_ID_MIN_LENGTH = 20
DRIVE_FILE_ID_MAX_LENGTH = 128
_DRIVE_FILE_ID_RE = re.compile(
    rf"^[A-Za-z0-9_-]{{{DRIVE_FILE_ID_MIN_LENGTH},{DRIVE_FILE_ID_MAX_LENGTH}}}$"
)

# `/d/<id>` appears as /file/d/<id>/view, /document/d/<id>/edit, and similar.
# Candidates are captured loosely here and validated by `is_valid_drive_file_id`.
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


def is_valid_drive_file_id(value: str | None) -> bool:
    """Return True when ``value`` is shaped like a Google Drive File ID.

    The rule is a bounded character-and-length check only: 20-128 characters
    drawn from ``[A-Za-z0-9_-]``. It is deliberately not pinned to one exact
    length, and it never confirms that the file exists.
    """
    if not value:
        return False
    return bool(_DRIVE_FILE_ID_RE.match(value))


def extract_drive_id_candidates(url: str | None) -> tuple[str, ...]:
    """Return every distinct Drive File ID candidate carried by ``url``.

    Candidates come only from a supported Google Drive or Google Docs host
    (see ``SUPPORTED_DRIVE_HOSTS``) reached over http/https, parsed with
    ``urlparse`` rather than substring matching. A `/d/<id>` path segment or an
    `id=<id>` query parameter on any other host contributes nothing. Order is
    first-seen: path segments before query parameters.
    """
    if not url:
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
    """Return the single unambiguous Drive File ID carried by ``url``.

    Returns None when the URL is not a supported Google Drive/Docs URL, when it
    carries no valid File ID, or when it carries more than one distinct
    candidate ID. Ambiguous URL identity is never silently resolved to the
    first candidate.
    """
    candidates = extract_drive_id_candidates(url)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_source_record(raw: Mapping[str, Any]) -> SourceAssetRecord:
    return SourceAssetRecord(
        source_row=str(raw.get("source_row", "")),
        drive_file_id=_clean(raw.get("drive_file_id")),
        drive_url=_clean(raw.get("drive_url")),
        file_name=_clean(raw.get("file_name")),
        approved_use=_clean(raw.get("approved_use")),
        audience=_clean(raw.get("audience")),
        review_status=_clean(raw.get("review_status")),
        review_date=_clean(raw.get("review_date")),
        visual_rationale=_clean(raw.get("visual_rationale")),
        worksheet_fit=_clean(raw.get("worksheet_fit")),
        slideshow_fit=_clean(raw.get("slideshow_fit")),
        poster_fit=_clean(raw.get("poster_fit")),
        format_decision_notes=_clean(raw.get("format_decision_notes")),
        excluded=bool(raw.get("excluded", False)),
    )


def normalize_existing_record(raw: Mapping[str, Any]) -> ExistingAssetRecord:
    extra_fields = {
        key: value for key, value in raw.items() if key not in _KNOWN_EXISTING_FIELDS
    }
    return ExistingAssetRecord(
        page_id=str(raw.get("page_id", "")),
        page_url=_clean(raw.get("page_url")),
        drive_file_id=_clean(raw.get("drive_file_id")),
        drive_url=_clean(raw.get("drive_url")),
        asset_title=_clean(raw.get("asset_title")),
        approved_use=_clean(raw.get("approved_use")),
        asset_type=_clean(raw.get("asset_type")),
        human_review_status=_clean(raw.get("human_review_status")),
        review_date=_clean(raw.get("review_date")),
        extra_fields=extra_fields,
    )
