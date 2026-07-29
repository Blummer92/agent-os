"""Normalize raw spreadsheet and Notion dictionaries into planner models."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .models import ExistingAssetRecord, SourceAssetRecord

# Google Drive File IDs are conventionally 25+ chars of [A-Za-z0-9_-].
_DRIVE_URL_ID_PATTERNS = (
    re.compile(r"/d/([-\w]{25,})"),
    re.compile(r"[?&]id=([-\w]{25,})"),
)

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


def extract_drive_id_from_url(url: str | None) -> str | None:
    """Return the Drive File ID embedded in a Drive URL, or None if absent."""
    if not url:
        return None
    for pattern in _DRIVE_URL_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
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
