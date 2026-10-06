"""Separate finite writer; canonical #936/#2283 and CKR6 readers stay read-only."""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
import urllib.request

from .admission import WriteBlocked, notion_id
from .writer import properties
from .catalog import REQUEST_ID, lesson_for

DATA_SOURCE_ENV = "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID"
MAX_RESPONSE_BYTES = 512 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LiveLessonsClient:
    """Fixed source + two page-property mutation shapes, no API proxy."""

    def __init__(self, request_id: str = REQUEST_ID) -> None:
        self.request_id = request_id
        self.lesson = lesson_for(request_id)
        # Called only after credential-free owner admission. Imports remain
        # lazy and reuse the existing read composition, credential and version.
        self._token = os.environ.get("NOTION_TOKEN", "").strip()
        if not self._token:
            raise WriteBlocked("existing-notion-credential-unavailable")
        self.source_id = notion_id(os.environ.get(DATA_SOURCE_ENV))
        from agent_os_notion_binding import new_read_adapter
        self._reader = new_read_adapter()
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _read(self, action: str, **payload) -> Mapping:
        from agent_os_notion_binding import build_read_task
        task = build_read_task(task_id="lessons-write-precheck", workflow_id="lessons-write",
                               owner="github-service-agent", action=action,
                               idempotency_key="lessons-write-read", payload={"action": action, **payload})
        result = self._reader.execute(task)
        if result.get("status") != "success" or not isinstance(result.get("output"), Mapping):
            raise WriteBlocked("canonical-notion-read-unavailable")
        return result["output"]

    def verify_binding(self) -> str:
        from scripts.agent_os_notion_read_request.binding_verification import verify_lessons_learned_binding
        # Reuse the current canonical anchor, not a new copied source identity.
        result = verify_lessons_learned_binding(self._reader, generated_at="request-scoped")
        if notion_id(result["lessons_learned"]["data_source_id"]) != self.source_id:
            raise WriteBlocked("canonical-lessons-destination-mismatch")
        return self.source_id

    def schema(self) -> Mapping:
        return self._read("get_data_source", data_source_id=self.source_id)

    def find_exact(self, title: str) -> Mapping:
        if title != self.lesson["Lesson Learned"]:
            raise WriteBlocked("finite-lesson-identity-required")
        return self._read("query_data_source", data_source_id=self.source_id,
                          filter={"property": "Lesson Learned", "title": {"equals": title}},
                          page_size=2, max_pages=1, max_results=2)

    def get_page(self, page_id: str) -> Mapping:
        return self._read("get_page", page_id=notion_id(page_id))

    def _mutate(self, *, page_id: str | None, intended: Mapping) -> Mapping:
        if intended != properties(self.request_id):
            raise WriteBlocked("reviewed-narrative-fields-required")
        if page_id is None:
            path, method = "/pages", "POST"
            body = {"parent": {"type": "data_source_id", "data_source_id": self.source_id},
                    "properties": intended}
        else:
            path, method = "/pages/" + notion_id(page_id), "PATCH"
            body = {"properties": intended}
        request = urllib.request.Request(
            "https://api.notion.com/v1" + path, method=method,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": "Bearer " + self._token,
                     "Notion-Version": self._reader.notion_version,
                     "Content-Type": "application/json"},
        )
        # No retries, redirects, caller URLs, headers, HTTP methods or body keys.
        try:
            with self._opener.open(request, timeout=25) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError
            output = json.loads(raw)
            if not isinstance(output, Mapping):
                raise ValueError
            return output
        except Exception:
            raise WriteBlocked("notion-write-outcome-unconfirmed") from None

    def create(self, properties: Mapping) -> Mapping:
        return self._mutate(page_id=None, intended=properties)

    def update(self, page_id: str, properties: Mapping) -> Mapping:
        return self._mutate(page_id=page_id, intended=properties)
