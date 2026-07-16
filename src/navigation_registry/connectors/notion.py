"""Offline read-only Notion connector compatibility wrapper.

The implementation delegates to the B2 shared Notion read-only client so older
imports keep working while downstream migrations target one canonical client.
"""

from __future__ import annotations

from typing import Any

from .notion_read_client import SharedNotionReadOnlyClient


class NotionReadOnlyConnector(SharedNotionReadOnlyClient):
    """Backward-compatible fixture connector using the shared read contract."""

    connector_id = "notion-read-only"
    connector_name = "Notion Read-Only Connector"

    def __init__(self, fixtures: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__(fixtures=fixtures)
