"""Read-only Notion REST API adapter.

Structural write safety: this adapter issues HTTP requests through
exactly two call sites -- `_get()` (always GET) and
`_post_query_database()` (always POST, to one hardcoded URL template:
`/v1/databases/{database_id}/query`, Notion's row-retrieval endpoint,
which takes a filter/sort body but never mutates state per Notion's own
API contract). There is no PATCH, PUT, or DELETE call anywhere in this
file, and no other POST target is reachable -- the POST path is not
built from caller-supplied paths or methods, only from a caller-supplied
`database_id` substituted into a fixed template. This is a narrower
guarantee than the GitHub read-only adapter's "GET only, full stop": it
is "GET, or POST restricted to this one fixed allowlisted read-semantic
endpoint" -- not weaker safety in effect (nothing here can create,
update, delete, archive, comment, or invite), but a different shape of
guarantee worth calling out explicitly rather than overclaiming GET-only.

Result shape (Phase 3F): returns the Phase 3D five-state contract
(status/message, from docs/ADAPTER_CONTRACT_FUTURE.md) rather than the
original success/error/is_transient shape used before this migration.
Retryable failures compute their own retry_after using the same
exponential-backoff formula Executor's RetryManager already applies
(5.0 * 2**retry_count, capped at 300.0), read from task.retry_count --
inlined here rather than imported, since importing RetryManager into
adapters would create a circular import with execution/executor.py
(which already imports TaskAdapter from this package). This preserves
the exact retry timing this adapter had before the migration; only the
result shape changed.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from workflow_scheduler.adapters.base_adapter import TaskAdapter
from workflow_scheduler.models import Task

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

_TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


class NotionReadOnlyAdapterError(Exception):
    """Raised internally for any controlled failure (bad payload, HTTP
    error, network error); always caught by execute() and turned into a
    Phase 3D five-state contract result (status="failure" or
    "retryable") -- never propagates."""

    def __init__(self, message: str, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient


def _raise_for_http_error(exc: urllib.error.HTTPError, api_name: str) -> None:
    is_transient = exc.code in _TRANSIENT_HTTP_STATUS_CODES
    raise NotionReadOnlyAdapterError(
        f"{api_name} returned HTTP {exc.code}: {exc.reason}", is_transient=is_transient
    ) from exc


def _default_http_get(url: str, headers: Dict[str, str], timeout: float) -> Any:
    """Real network GET via stdlib urllib (no extra dependency). Returns
    the parsed JSON body. Raises NotionReadOnlyAdapterError on any HTTP
    or network failure -- never a bare urllib/json exception."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc, "Notion API")
    except urllib.error.URLError as exc:
        raise NotionReadOnlyAdapterError(f"Notion API connection error: {exc.reason}", is_transient=True) from exc
    except TimeoutError as exc:
        raise NotionReadOnlyAdapterError(f"Notion API request timed out: {exc}", is_transient=True) from exc
    except json.JSONDecodeError as exc:
        raise NotionReadOnlyAdapterError(f"Notion API returned invalid JSON: {exc}", is_transient=False) from exc


def _default_http_post_query_database(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Any:
    """Real network POST via stdlib urllib, used only by
    _post_query_database() against the one hardcoded, allowlisted
    /v1/databases/{database_id}/query URL. Same failure-handling shape
    as _default_http_get."""
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc, "Notion API")
    except urllib.error.URLError as exc:
        raise NotionReadOnlyAdapterError(f"Notion API connection error: {exc.reason}", is_transient=True) from exc
    except TimeoutError as exc:
        raise NotionReadOnlyAdapterError(f"Notion API request timed out: {exc}", is_transient=True) from exc
    except json.JSONDecodeError as exc:
        raise NotionReadOnlyAdapterError(f"Notion API returned invalid JSON: {exc}", is_transient=False) from exc


def _plain_text(rich_text: Any) -> str:
    """Join the plain_text field of a Notion rich-text array. Notion
    includes "plain_text" as a convenience field on every rich-text
    object; falls back to "" for anything unexpected."""
    if not isinstance(rich_text, list):
        return ""
    return "".join(item.get("plain_text", "") for item in rich_text if isinstance(item, dict))


class NotionReadOnlyAdapter(TaskAdapter):
    """Read-only Notion adapter. Supported task.payload["action"] values:
    get_page, get_block_children, get_database, query_database. See
    ACTIONS below for the exact handler per action.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        http_get: Optional[Callable[[str, Dict[str, str], float], Any]] = None,
        http_post_query_database: Optional[Callable[[str, Dict[str, str], Dict[str, Any], float], Any]] = None,
        timeout: float = 10.0,
        notion_version: str = NOTION_VERSION,
    ):
        """Args:
        token: Notion integration token for the Authorization header.
            Falls back to the NOTION_TOKEN environment variable. Unlike
            the GitHub adapter, Notion has no meaningful unauthenticated
            mode -- every request requires a bearer token -- so a
            missing token surfaces as a normal HTTP 401 failure from
            the API rather than a local validation error.
        http_get: Injectable GET function, signature
            (url, headers, timeout) -> parsed JSON body, raising
            NotionReadOnlyAdapterError on failure. Defaults to a real
            urllib-based implementation; tests inject a fake here.
        http_post_query_database: Injectable POST function, signature
            (url, headers, body, timeout) -> parsed JSON body, raising
            NotionReadOnlyAdapterError on failure. Used only for the one
            allowlisted query_database endpoint. Defaults to a real
            urllib-based implementation; tests inject a fake here.
        timeout: Per-request timeout in seconds.
        notion_version: Value for the required Notion-Version header.
        """
        self.token = token if token is not None else os.environ.get("NOTION_TOKEN")
        self._http_get = http_get or _default_http_get
        self._http_post_query_database = http_post_query_database or _default_http_post_query_database
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
            return {"status": "success", "message": f"Notion {action!r} succeeded", "output": output}
        except NotionReadOnlyAdapterError as exc:
            if exc.is_transient:
                retry_after = min(5.0 * (2 ** task.retry_count), 300.0)
                return {"status": "retryable", "message": str(exc), "retry_after": retry_after}
            return {"status": "failure", "message": str(exc)}

    # -- payload helpers ------------------------------------------------

    def _require(self, payload: Dict[str, Any], field: str) -> Any:
        if field not in payload or payload[field] in (None, ""):
            raise NotionReadOnlyAdapterError(f"Missing required payload field: {field!r}")
        return payload[field]

    def _headers(self) -> Dict[str, str]:
        headers = {"Notion-Version": self.notion_version}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str) -> Any:
        """One of exactly two HTTP call sites in this module -- always GET."""
        return self._http_get(f"{NOTION_API_BASE}{path}", self._headers(), self.timeout)

    def _post_query_database(self, database_id: str, body: Dict[str, Any]) -> Any:
        """The only POST call site in this module, and the only place a
        POST URL is ever constructed -- always this one fixed template,
        never a caller-supplied path or method."""
        url = f"{NOTION_API_BASE}/databases/{database_id}/query"
        headers = {**self._headers(), "Content-Type": "application/json"}
        return self._http_post_query_database(url, headers, body, self.timeout)

    # -- action handlers --------------------------------------------------

    def _action_get_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page_id = self._require(payload, "page_id")
        data = self._get(f"/pages/{page_id}")
        return {
            "id": data.get("id"),
            "url": data.get("url"),
            "archived": data.get("archived"),
            "properties": data.get("properties"),
            "created_time": data.get("created_time"),
            "last_edited_time": data.get("last_edited_time"),
        }

    def _action_get_block_children(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        block_id = self._require(payload, "block_id")
        page_size = payload.get("page_size", 100)
        data = self._get(f"/blocks/{block_id}/children?page_size={page_size}")
        results = data.get("results") or []
        blocks: List[Dict[str, Any]] = [
            {"id": block.get("id"), "type": block.get("type"), "has_children": block.get("has_children")}
            for block in results
            if isinstance(block, dict)
        ]
        return {"blocks": blocks, "has_more": data.get("has_more"), "next_cursor": data.get("next_cursor")}

    def _action_get_database(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        database_id = self._require(payload, "database_id")
        data = self._get(f"/databases/{database_id}")
        return {
            "id": data.get("id"),
            "url": data.get("url"),
            "archived": data.get("archived"),
            "title": _plain_text(data.get("title")),
            "properties": data.get("properties"),
            "created_time": data.get("created_time"),
            "last_edited_time": data.get("last_edited_time"),
        }

    def _action_query_database(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        database_id = self._require(payload, "database_id")
        body: Dict[str, Any] = {}
        if "filter" in payload and payload["filter"] is not None:
            body["filter"] = payload["filter"]
        if "page_size" in payload and payload["page_size"] is not None:
            body["page_size"] = payload["page_size"]
        data = self._post_query_database(database_id, body)
        results = data.get("results") or []
        rows: List[Dict[str, Any]] = [
            {"id": row.get("id"), "url": row.get("url"), "properties": row.get("properties")}
            for row in results
            if isinstance(row, dict)
        ]
        return {"results": rows, "has_more": data.get("has_more"), "next_cursor": data.get("next_cursor")}

    ACTIONS: Dict[str, Callable[["NotionReadOnlyAdapter", Dict[str, Any]], Dict[str, Any]]] = {
        "get_page": _action_get_page,
        "get_block_children": _action_get_block_children,
        "get_database": _action_get_database,
        "query_database": _action_query_database,
    }
