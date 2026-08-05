"""Normalized data models for the visual asset reconciliation planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReconciliationResult(str, Enum):
    UPDATE_EXISTING = "UPDATE_EXISTING"
    CREATE_MISSING = "CREATE_MISSING"
    DUPLICATE_ID = "DUPLICATE_ID"
    MALFORMED_IDENTITY = "MALFORMED_IDENTITY"
    CONTRADICTORY_RECORD = "CONTRADICTORY_RECORD"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True)
class SourceAssetRecord:
    """One normalized row from the reviewed spreadsheet."""

    source_row: str
    drive_file_id: str | None = None
    drive_url: str | None = None
    file_name: str | None = None
    approved_use: str | None = None
    audience: str | None = None
    review_status: str | None = None
    review_date: str | None = None
    visual_rationale: str | None = None
    worksheet_fit: str | None = None
    slideshow_fit: str | None = None
    poster_fit: str | None = None
    format_decision_notes: str | None = None
    excluded: bool = False


@dataclass(frozen=True)
class ExistingAssetRecord:
    """One normalized existing record from the Notion Visual Asset Library."""

    page_id: str
    page_url: str | None = None
    drive_file_id: str | None = None
    drive_url: str | None = None
    asset_title: str | None = None
    approved_use: str | None = None
    asset_type: str | None = None
    human_review_status: str | None = None
    review_date: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationEntry:
    """One classified planner outcome for a single source record."""

    source_row: str
    result: ReconciliationResult
    identity_key: str | None
    matched_page_ids: tuple[str, ...] = ()
    reason: str = ""
    preserved_fields: dict[str, Any] = field(default_factory=dict)
