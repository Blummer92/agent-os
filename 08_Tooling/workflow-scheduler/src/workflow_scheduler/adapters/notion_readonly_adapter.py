"""Read-only Notion REST API adapter.

The canonical read path targets Notion API ``2026-03-11``. All network calls are
structurally restricted to GET requests plus POST requests to allowlisted query
endpoints. The current query model is ``/v1/data_sources/{id}/query``.

``query_database`` remains as a temporary compatibility action for existing
Scheduler callers. New callers must use ``get_data_source`` and
``query_data_source``; the compatibility action is intentionally isolated and
must not be expanded.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"

_TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_PAGE_SIZE = 100
_MAX_PAGES = 20
_MAX_RESULTS = 2000
_QUERY_BODY_FIELDS = ("filter", "sorts")


class NotionReadOnlyAdapterError(Exception):
    """Controlled adapter failure converted to a Scheduler contract result."""

    def __init__(self, message: str, is_transient: bool = False, retry_after: Optional[float] = None):
        super().__init__(message)
        self.is_transient = is_transient
        self.retry_after = retry_after


def _retry_after_seconds(headers: Any) -> Optional[float]:
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After")
    except AttributeError:
        return None
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _raise_for_http_error(exc: urllib.error.HTTPError, api_name: str) -> None:
    raise NotionReadOnlyAdapterError(
        f"{api_name} returned HTTP {exc.code}: {exc.reason}",
        is_transient=exc.code in _TRANSIENT_HTTP_STATUS_CODES,
        retry_after=_retry_after_seconds(exc.headers),
    ) from exc


def _decode_json_response(response: Any) -> Dict[str, Any]:
    try:
        payload = json.loads(response.read())
    except json.JSONDecodeError as exc:
        raise NotionReadOnlyAdapterError(
            f"Notion API returned invalid JSON: {exc}", is_transient=False
        ) from exc
    if not isinstance(payload, dict):
        raise NotionReadOnlyAdapterError("Notion API returned a non-object JSON payload")
    return payload


def _default_http_get(url: str, headers: Dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode_json_response(response)
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc, "Notion API")
    except urllib.error.URLError as exc:
        raise NotionReadOnlyAdapterError(
            f"Notion API connection error: {exc.reason}", is_transient=True
        ) from exc
    except TimeoutError as exc:
        raise NotionReadOnlyAdapterError(
            f"Notion API request timed out: {exc}", is_transient=True
        ) from exc


def _default_http_post_read(
    url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float
) -> Any:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode_json_response(response)
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc, "Notion API")
    except urllib.error.URLError as exc:
        raise NotionReadOnlyAdapterError(
            f"Notion API connection error: {exc.reason}", is_transient=True
        ) from exc
    except TimeoutError as exc:
        raise NotionReadOnlyAdapterError(
            f"Notion API request timed out: {exc}", is_transient=True
        ) from exc


# Backward-compatible helper name used by existing offline tests/callers.
_default_http_post_query_database = _default_http_post_read


def _plain_text(rich_text: Any) -> str:
    if not isinstance(rich_text, list):
        return ""
    return "".join(
        item.get("plain_text", "") for item in rich_text if isinstance(item, dict)
    )


class NotionReadOnlyAdapter(TaskAdapter):
    """Bounded read-only Notion adapter for Scheduler ``read:notion`` tasks."""

    def __init__(
        self,
        token: Optional[str] = None,
        http_get: Optional[Callable[[str, Dict[str, str], float], Any]] = None,
        http_post_query_database: Optional[
            Callable[[str, Dict[str, str], Dict[str, Any], float], Any]
        ] = None,
        http_post_query_data_source: Optional[
            Callable[[str, Dict[str, str], Dict[str, Any], float], Any]
        ] = None,
        timeout: float = 10.0,
        notion_version: str = NOTION_VERSION,
    ):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite positive number")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        self.token = token if token is not None else os.environ.get("NOTION_TOKEN")
        self._http_get = http_get or _default_http_get
        self._http_post_query_database = http_post_query_database or _default_http_post_read
        self._http_post_query_data_source = (
            http_post_query_data_source or http_post_query_database or _default_http_post_read
        )
        self.timeout = timeout
        self.notion_version = notion_version

    def execute(self, task: Task) -> Dict[str, Any]:
        payload = task.payload or {}
        try:
            action = self._require(payload, "action")
            handler = self.ACTIONS.get(action)
            if handler is None:
                raise NotionReadOnlyAdapterError(
                    f"Unsupported action: {action!r}. Supported: {sorted(self.ACTIONS)}"
                )
            output = handler(self, payload)
            return {
                "status": "success",
                "message": f"Notion {action!r} succeeded",
                "output": output,
            }
        except NotionReadOnlyAdapterError as exc:
            if exc.is_transient:
                retry_after = exc.retry_after
                if retry_after is None:
                    retry_after = min(5.0 * (2 ** task.retry_count), 300.0)
                return {
                    "status": "retryable",
                    "message": str(exc),
                    "retry_after": retry_after,
                }
            return {"status": "failure", "message": str(exc)}

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise NotionReadOnlyAdapterError(
                f"Missing required payload field: {field!r}"
            )
        return payload[field]

    def _headers(self) -> Dict[str, str]:
        headers = {"Notion-Version": self.notion_version}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str) -> Dict[str, Any]:
        data = self._http_get(
            f"{NOTION_API_BASE}{path}", self._headers(), self.timeout
        )
        return self._require_object(data)

    def _post_query_database(self, database_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Temporary legacy query endpoint used only by ``query_database``."""
        url = f"{NOTION_API_BASE}/databases/{database_id}/query"
        data = self._http_post_query_database(
            url, {**self._headers(), "Content-Type": "application/json"}, body, self.timeout
        )
        return self._require_object(data)

    def _post_query_data_source(
        self,
        data_source_id: str,
        body: Dict[str, Any],
        filter_properties: Sequence[str] = (),
    ) -> Dict[str, Any]:
        url = f"{NOTION_API_BASE}/data_sources/{data_source_id}/query"
        if filter_properties:
            query = urllib.parse.urlencode(
                [("filter_properties", item) for item in filter_properties]
            )
            url = f"{url}?{query}"
        data = self._http_post_query_data_source(
            url, {**self._headers(), "Content-Type": "application/json"}, body, self.timeout
        )
        return self._require_object(data)

    def _require_object(self, data: Any) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise NotionReadOnlyAdapterError(
                "Notion API returned a malformed response; expected an object"
            )
        return data

    def _require_results(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if "results" not in data or not isinstance(data["results"], list):
            raise NotionReadOnlyAdapterError(
                "Notion API response is missing required list field 'results'"
            )
        return [item for item in data["results"] if isinstance(item, dict)]

    def _bounded_int(
        self, payload: Dict[str, Any], field: str, default: int, minimum: int, maximum: int
    ) -> int:
        value = payload.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise NotionReadOnlyAdapterError(f"{field!r} must be an integer")
        if value < minimum or value > maximum:
            raise NotionReadOnlyAdapterError(
                f"{field!r} must be between {minimum} and {maximum}"
            )
        return value

    def _filter_properties(self, payload: Dict[str, Any]) -> List[str]:
        value = payload.get("filter_properties")
        if value is None:
            return []
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise NotionReadOnlyAdapterError(
                "'filter_properties' must be a list of non-empty strings"
            )
        return value

    def _query_body(self, payload: Dict[str, Any], page_size: int) -> Dict[str, Any]:
        body: Dict[str, Any] = {"page_size": page_size}
        for field in _QUERY_BODY_FIELDS:
            if field in payload and payload[field] is not None:
                body[field] = payload[field]
        return body

    def _collect_post_pages(
        self,
        data_source_id: str,
        body: Dict[str, Any],
        filter_properties: Sequence[str],
        max_pages: int,
        max_results: int,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        last: Dict[str, Any] = {}
        for _ in range(max_pages):
            request_body = dict(body)
            if cursor is not None:
                request_body["start_cursor"] = cursor
            last = self._post_query_data_source(
                data_source_id, request_body, filter_properties
            )
            page_results = self._require_results(last)
            remaining = max_results - len(results)
            results.extend(page_results[:remaining])
            if len(results) >= max_results:
                break
            if not last.get("has_more"):
                break
            next_cursor = last.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise NotionReadOnlyAdapterError(
                    "Notion API set has_more without a valid opaque next_cursor"
                )
            cursor = next_cursor
        return {
            "results": results,
            "has_more": bool(last.get("has_more")),
            "next_cursor": last.get("next_cursor"),
            "request_id": last.get("request_id"),
        }

    def _action_get_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page_id = self._require(payload, "page_id")
        data = self._get(f"/pages/{page_id}")
        if not data.get("id"):
            raise NotionReadOnlyAdapterError(
                "Notion page response is missing required field 'id'"
            )
        return {
            "id": data.get("id"),
            "url": data.get("url"),
            "archived": data.get("archived"),
            "in_trash": data.get("in_trash"),
            "properties": data.get("properties"),
            "created_time": data.get("created_time"),
            "last_edited_time": data.get("last_edited_time"),
            "request_id": data.get("request_id"),
        }

    def _action_get_block_children(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        block_id = self._require(payload, "block_id")
        page_size = self._bounded_int(payload, "page_size", 100, 1, _MAX_PAGE_SIZE)
        params = {"page_size": page_size}
        if payload.get("start_cursor") is not None:
            params["start_cursor"] = str(payload["start_cursor"])
        data = self._get(
            f"/blocks/{block_id}/children?{urllib.parse.urlencode(params)}"
        )
        blocks = [
            {
                "id": block.get("id"),
                "type": block.get("type"),
                "has_children": block.get("has_children"),
                "archived": block.get("archived"),
                "in_trash": block.get("in_trash"),
            }
            for block in self._require_results(data)
        ]
        return {
            "blocks": blocks,
            "has_more": data.get("has_more"),
            "next_cursor": data.get("next_cursor"),
            "request_id": data.get("request_id"),
        }

    def _action_get_database(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        database_id = self._require(payload, "database_id")
        data = self._get(f"/databases/{database_id}")
        if not data.get("id"):
            raise NotionReadOnlyAdapterError(
                "Notion database response is missing required field 'id'"
            )
        return {
            "id": data.get("id"),
            "url": data.get("url"),
            "archived": data.get("archived"),
            "in_trash": data.get("in_trash"),
            "title": _plain_text(data.get("title")),
            "data_sources": data.get("data_sources"),
            "created_time": data.get("created_time"),
            "last_edited_time": data.get("last_edited_time"),
            "request_id": data.get("request_id"),
        }

    def _action_get_data_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data_source_id = self._require(payload, "data_source_id")
        data = self._get(f"/data_sources/{data_source_id}")
        if not data.get("id"):
            raise NotionReadOnlyAdapterError(
                "Notion data source response is missing required field 'id'"
            )
        return {
            "id": data.get("id"),
            "url": data.get("url"),
            "archived": data.get("archived"),
            "in_trash": data.get("in_trash"),
            "name": data.get("name"),
            "properties": data.get("properties"),
            "parent": data.get("parent"),
            "created_time": data.get("created_time"),
            "last_edited_time": data.get("last_edited_time"),
            "request_id": data.get("request_id"),
        }

    def _action_query_data_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data_source_id = self._require(payload, "data_source_id")
        page_size = self._bounded_int(payload, "page_size", 100, 1, _MAX_PAGE_SIZE)
        max_pages = self._bounded_int(payload, "max_pages", 1, 1, _MAX_PAGES)
        max_results = self._bounded_int(
            payload, "max_results", page_size * max_pages, 1, _MAX_RESULTS
        )
        body = self._query_body(payload, page_size)
        if payload.get("start_cursor") is not None:
            body["start_cursor"] = str(payload["start_cursor"])
        return self._collect_post_pages(
            data_source_id,
            body,
            self._filter_properties(payload),
            max_pages,
            max_results,
        )

    def _action_get_page_property(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page_id = self._require(payload, "page_id")
        property_id = self._require(payload, "property_id")
        page_size = self._bounded_int(payload, "page_size", 100, 1, _MAX_PAGE_SIZE)
        params = {"page_size": page_size}
        if payload.get("start_cursor") is not None:
            params["start_cursor"] = str(payload["start_cursor"])
        data = self._get(
            f"/pages/{page_id}/properties/{urllib.parse.quote(str(property_id), safe='')}?"
            f"{urllib.parse.urlencode(params)}"
        )
        output = {
            "id": data.get("id"),
            "type": data.get("type"),
            "object": data.get("object"),
            "has_more": data.get("has_more"),
            "next_cursor": data.get("next_cursor"),
            "request_id": data.get("request_id"),
        }
        if "results" in data:
            output["results"] = self._require_results(data)
        else:
            output["property_item"] = data
        return output

    def _action_query_database(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Temporary compatibility action; new callers use query_data_source."""
        database_id = self._require(payload, "database_id")
        body: Dict[str, Any] = {}
        if "filter" in payload and payload["filter"] is not None:
            body["filter"] = payload["filter"]
        if "page_size" in payload and payload["page_size"] is not None:
            body["page_size"] = payload["page_size"]
        data = self._post_query_database(database_id, body)
        rows = [
            {
                "id": row.get("id"),
                "url": row.get("url"),
                "properties": row.get("properties"),
                "archived": row.get("archived"),
                "in_trash": row.get("in_trash"),
            }
            for row in self._require_results(data)
        ]
        return {
            "results": rows,
            "has_more": data.get("has_more"),
            "next_cursor": data.get("next_cursor"),
            "request_id": data.get("request_id"),
            "deprecated": "Use query_data_source with data_source_id",
        }

    ACTIONS: Dict[
        str, Callable[["NotionReadOnlyAdapter", Dict[str, Any]], Dict[str, Any]]
    ] = {
        "get_page": _action_get_page,
        "get_block_children": _action_get_block_children,
        "get_database": _action_get_database,
        "get_data_source": _action_get_data_source,
        "query_data_source": _action_query_data_source,
        "get_page_property": _action_get_page_property,
        "query_database": _action_query_database,
    }
