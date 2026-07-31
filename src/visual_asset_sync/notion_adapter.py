"""Bounded read-only Notion extraction for visual asset reconciliation."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .models import ExistingAssetRecord
from .normalize import normalize_existing_record

SUPPORTED_NOTION_VERSION = "2025-09-03"
MAX_DATA_SOURCE_ID_LENGTH = 256
MAX_PAGES_LIMIT = 1_000
MAX_RECORDS_LIMIT = 100_000
MAX_RETRIES_LIMIT = 10
MAX_TOTAL_RETRY_DELAY = 300.0

_ALLOWED_FIELDS = frozenset(
    {
        "drive_file_id",
        "drive_url",
        "asset_title",
        "approved_use",
        "asset_type",
        "human_review_status",
        "review_date",
    }
)


class NotionAdapterError(Exception):
    """Base class for deterministic Notion adapter failures."""


class NotionConfigurationError(NotionAdapterError):
    """Raised when request configuration is invalid."""


class NotionReadError(NotionAdapterError):
    """Raised when the read-only client boundary fails."""


class NotionPaginationError(NotionAdapterError):
    """Raised when pagination evidence is malformed or over bound."""


class NotionSchemaError(NotionAdapterError):
    """Raised when property configuration or response shape is invalid."""


class NotionRecordError(NotionAdapterError):
    """Raised when a page cannot be normalized safely."""


class NotionRetryLimitError(NotionAdapterError):
    """Raised when retry count or total delay would exceed the request."""


@dataclass(frozen=True)
class NotionReadRequest:
    """One exact, bounded read against a single Notion data source."""

    data_source_id: str
    notion_version: str = SUPPORTED_NOTION_VERSION
    page_size: int = 25
    maximum_pages: int = 25
    maximum_records: int = 625
    maximum_retries: int = 2
    maximum_total_retry_delay: float = 30.0

    def __post_init__(self) -> None:
        if type(self.data_source_id) is not str:
            raise NotionConfigurationError("data_source_id must be an exact string")
        data_source_id = self.data_source_id.strip()
        if not data_source_id:
            raise NotionConfigurationError("data_source_id must not be empty")
        if len(data_source_id) > MAX_DATA_SOURCE_ID_LENGTH:
            raise NotionConfigurationError("data_source_id exceeds the length limit")

        if type(self.notion_version) is not str:
            raise NotionConfigurationError("notion_version must be an exact string")
        if self.notion_version != SUPPORTED_NOTION_VERSION:
            raise NotionConfigurationError("notion_version is not supported")

        _require_integer(self.page_size, "page_size", minimum=1, maximum=100)
        _require_integer(
            self.maximum_pages,
            "maximum_pages",
            minimum=1,
            maximum=MAX_PAGES_LIMIT,
        )
        _require_integer(
            self.maximum_records,
            "maximum_records",
            minimum=1,
            maximum=MAX_RECORDS_LIMIT,
        )
        _require_integer(
            self.maximum_retries,
            "maximum_retries",
            minimum=0,
            maximum=MAX_RETRIES_LIMIT,
        )
        if type(self.maximum_total_retry_delay) not in {int, float}:
            raise NotionConfigurationError(
                "maximum_total_retry_delay must be an exact number"
            )
        delay = float(self.maximum_total_retry_delay)
        if not math.isfinite(delay) or delay < 0 or delay > MAX_TOTAL_RETRY_DELAY:
            raise NotionConfigurationError(
                "maximum_total_retry_delay is outside the supported range"
            )
        object.__setattr__(self, "data_source_id", data_source_id)
        object.__setattr__(self, "maximum_total_retry_delay", delay)


def _require_integer(value: Any, name: str, *, minimum: int, maximum: int) -> None:
    if type(value) is not int:
        raise NotionConfigurationError(f"{name} must be an exact integer")
    if value < minimum or value > maximum:
        raise NotionConfigurationError(f"{name} is outside the supported range")


class NotionDataSourceReader(Protocol):
    """Minimal read-only query boundary."""

    def query_data_source(
        self,
        *,
        data_source_id: str,
        notion_version: str,
        page_size: int,
        start_cursor: str | None,
    ) -> dict[str, Any]:
        """Return one raw query page."""


class NotionRateLimitError(Exception):
    """Client-neutral rate-limit signal with one exact retry delay."""

    def __init__(self, retry_after: float) -> None:
        if type(retry_after) not in {int, float}:
            raise TypeError("retry_after must be an exact number")
        delay = float(retry_after)
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("retry_after must be finite and non-negative")
        super().__init__("notion request was rate limited")
        self.retry_after = delay


class InjectedNotionDataSourceReader:
    """Read-only wrapper around an injected callable; construction makes no call."""

    def __init__(self, query: Callable[..., dict[str, Any]]) -> None:
        if not callable(query):
            raise TypeError("query must be callable")
        self._query = query

    def query_data_source(
        self,
        *,
        data_source_id: str,
        notion_version: str,
        page_size: int,
        start_cursor: str | None,
    ) -> dict[str, Any]:
        try:
            return self._query(
                data_source_id=data_source_id,
                notion_version=notion_version,
                page_size=page_size,
                start_cursor=start_cursor,
            )
        except NotionRateLimitError:
            raise
        except Exception:
            pass
        raise NotionReadError("Notion read failed") from None


def read_existing_assets(
    reader: NotionDataSourceReader,
    request: NotionReadRequest,
    property_mapping: dict[str, str],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[ExistingAssetRecord, ...]:
    """Read, validate, and normalize one bounded Notion collection."""
    mapping = _validate_mapping(property_mapping)
    cursor: str | None = None
    seen_cursors: set[str] = set()
    records: list[ExistingAssetRecord] = []
    page_count = 0

    while True:
        if page_count >= request.maximum_pages:
            raise NotionPaginationError("maximum page count reached")
        response = _query_with_retry(reader, request, cursor, sleep)
        page_count += 1
        results, has_more, next_cursor = _validate_page(response)
        if len(records) + len(results) > request.maximum_records:
            raise NotionPaginationError("maximum record count reached")
        records.extend(_map_page(page, mapping) for page in results)

        if not has_more:
            return tuple(records)
        assert next_cursor is not None
        if next_cursor in seen_cursors:
            raise NotionPaginationError("pagination cursor repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _query_with_retry(
    reader: NotionDataSourceReader,
    request: NotionReadRequest,
    cursor: str | None,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    retries = 0
    total_delay = 0.0
    while True:
        try:
            return reader.query_data_source(
                data_source_id=request.data_source_id,
                notion_version=request.notion_version,
                page_size=request.page_size,
                start_cursor=cursor,
            )
        except NotionRateLimitError as error:
            if retries >= request.maximum_retries:
                raise NotionRetryLimitError("maximum retry count reached") from None
            new_total = total_delay + error.retry_after
            if new_total > request.maximum_total_retry_delay:
                raise NotionRetryLimitError("maximum retry delay reached") from None
            sleep(error.retry_after)
            total_delay = new_total
            retries += 1
        except NotionAdapterError:
            raise
        except Exception:
            pass
        raise NotionReadError("Notion read failed") from None


def _validate_page(response: Any) -> tuple[list[dict[str, Any]], bool, str | None]:
    if type(response) is not dict:
        raise NotionSchemaError("Notion response must be an exact dictionary")
    results = response.get("results")
    if type(results) is not list:
        raise NotionSchemaError("Notion results must be an exact list")
    if any(type(item) is not dict for item in results):
        raise NotionSchemaError("Notion results must contain exact dictionaries")
    has_more = response.get("has_more")
    if type(has_more) is not bool:
        raise NotionPaginationError("has_more must be an exact boolean")
    next_cursor = response.get("next_cursor")
    if has_more:
        if type(next_cursor) is not str or not next_cursor:
            raise NotionPaginationError("next_cursor is required when has_more is true")
    elif next_cursor is not None:
        raise NotionPaginationError("next_cursor must be null when has_more is false")
    return results, has_more, next_cursor


def _validate_mapping(mapping: Any) -> dict[str, str]:
    if type(mapping) is not dict or not mapping:
        raise NotionConfigurationError("property_mapping must be a non-empty exact dictionary")
    validated: dict[str, str] = {}
    used_properties: set[str] = set()
    for field, property_name in mapping.items():
        if type(field) is not str or field not in _ALLOWED_FIELDS:
            raise NotionConfigurationError("property_mapping contains an unsupported field")
        if type(property_name) is not str or not property_name.strip():
            raise NotionConfigurationError("property names must be non-empty exact strings")
        normalized = property_name.strip()
        if normalized in used_properties:
            raise NotionConfigurationError("property_mapping reuses a property name")
        validated[field] = normalized
        used_properties.add(normalized)
    return validated


def _map_page(page: dict[str, Any], mapping: dict[str, str]) -> ExistingAssetRecord:
    page_id = page.get("id")
    page_url = page.get("url")
    properties = page.get("properties")
    if type(page_id) is not str or not page_id.strip():
        raise NotionRecordError("Notion page id is missing or invalid")
    if page_url is not None and type(page_url) is not str:
        raise NotionRecordError("Notion page url is invalid")
    if type(properties) is not dict:
        raise NotionRecordError("Notion properties must be an exact dictionary")

    raw: dict[str, Any] = {"page_id": page_id, "page_url": page_url}
    mapped_names = set(mapping.values())
    for field, property_name in mapping.items():
        if property_name not in properties:
            raise NotionRecordError("required mapped property is missing")
        raw[field] = _extract_property(properties[property_name])

    extra_fields: dict[str, Any] = {}
    for property_name, value in properties.items():
        if type(property_name) is not str:
            raise NotionRecordError("Notion property names must be exact strings")
        if property_name not in mapped_names:
            extra_fields[property_name] = _extract_property(value)
    raw.update(extra_fields)
    try:
        return normalize_existing_record(raw)
    except (TypeError, ValueError):
        raise NotionRecordError("Notion record does not satisfy the planner contract") from None


def _extract_property(value: Any) -> Any:
    if type(value) is not dict:
        raise NotionRecordError("Notion property must be an exact dictionary")
    property_type = value.get("type")
    if property_type == "title" or property_type == "rich_text":
        items = value.get(property_type)
        if type(items) is not list:
            raise NotionRecordError("Notion text property is malformed")
        fragments: list[str] = []
        for item in items:
            if type(item) is not dict or type(item.get("plain_text")) is not str:
                raise NotionRecordError("Notion text fragment is malformed")
            fragments.append(item["plain_text"])
        return "".join(fragments) or None
    if property_type == "url":
        result = value.get("url")
        if result is not None and type(result) is not str:
            raise NotionRecordError("Notion url property is malformed")
        return result
    if property_type == "select":
        selected = value.get("select")
        if selected is None:
            return None
        if type(selected) is not dict or type(selected.get("name")) is not str:
            raise NotionRecordError("Notion select property is malformed")
        return selected["name"]
    if property_type == "status":
        status = value.get("status")
        if status is None:
            return None
        if type(status) is not dict or type(status.get("name")) is not str:
            raise NotionRecordError("Notion status property is malformed")
        return status["name"]
    if property_type == "date":
        date = value.get("date")
        if date is None:
            return None
        if type(date) is not dict or type(date.get("start")) is not str:
            raise NotionRecordError("Notion date property is malformed")
        return date["start"]
    if property_type == "checkbox":
        checkbox = value.get("checkbox")
        if type(checkbox) is not bool:
            raise NotionRecordError("Notion checkbox property is malformed")
        return checkbox
    if property_type == "number":
        number = value.get("number")
        if number is not None and type(number) not in {int, float}:
            raise NotionRecordError("Notion number property is malformed")
        return number
    raise NotionRecordError("Notion property type is unsupported")
