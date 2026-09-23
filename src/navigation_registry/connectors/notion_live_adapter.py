"""Metadata-only wrapper for a future live read-only Notion adapter.

This module intentionally has no Notion SDK dependency, no HTTP client, no
credentials, and no live system construction. A client-like object must be
injected by callers so tests can prove the safety boundary before live Notion
access is introduced.
"""

from typing import Any, Protocol

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_live_boundary import NotionLiveReadOnlyBoundary, NotionLiveReadOnlyConfig
from .notion_normalizer import normalize_notion_resource


class NotionMetadataClient(Protocol):
    """Minimal read-only metadata client shape for dependency injection."""

    def retrieve_page_metadata(self, page_id: str) -> dict[str, Any]:
        """Return page metadata without page body content."""

    def retrieve_database_metadata(self, database_id: str) -> dict[str, Any]:
        """Return database metadata."""


class NotionLiveReadOnlyAdapter:
    """Future live adapter wrapper guarded by read-only boundary checks."""

    connector_id = "notion-live-readonly-adapter"
    connector_name = "Notion Live Read-Only Adapter"
    connector_version = "0.1.0"
    write_capabilities = "none"
    page_body_reads_enabled = False

    def __init__(
        self,
        config: NotionLiveReadOnlyConfig,
        client: NotionMetadataClient,
    ) -> None:
        self._boundary = NotionLiveReadOnlyBoundary(config)
        self._client = client

    def lookup_page_metadata(self, page_id: str) -> RegistryResource | ConnectorError:
        error = self._preflight(page_id)
        if error is not None:
            return error
        try:
            payload = self._client.retrieve_page_metadata(page_id)
        except Exception as exc:  # pragma: no cover - defensive mapping for clients
            return ConnectorError(
                code=ConnectorErrorCode.UNKNOWN_ERROR,
                severity="high",
                retryable=True,
                message="Notion metadata client failed while retrieving page metadata.",
                resource_id=page_id,
                evidence={"error_type": type(exc).__name__},
            )
        return normalize_notion_resource(payload)

    def lookup_database_metadata(
        self, database_id: str
    ) -> RegistryResource | ConnectorError:
        error = self._preflight(database_id)
        if error is not None:
            return error
        try:
            payload = self._client.retrieve_database_metadata(database_id)
        except Exception as exc:  # pragma: no cover - defensive mapping for clients
            return ConnectorError(
                code=ConnectorErrorCode.UNKNOWN_ERROR,
                severity="high",
                retryable=True,
                message="Notion metadata client failed while retrieving database metadata.",
                resource_id=database_id,
                evidence={"error_type": type(exc).__name__},
            )
        return normalize_notion_resource(payload)

    def read_page_body(self, page_id: str) -> ConnectorError:
        return self._boundary.read_page_body(page_id)

    def report_health(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "connector_name": self.connector_name,
            "connector_version": self.connector_version,
            "health_state": "BoundaryGuarded",
            "live_system_access": False,
            "write_capabilities": self.write_capabilities,
            "page_body_reads_enabled": self.page_body_reads_enabled,
        }

    def _preflight(self, target_id: str) -> ConnectorError | None:
        live_mode_error = self._boundary.live_mode_error()
        if live_mode_error is not None:
            return live_mode_error
        approved_probe = self._boundary.lookup_mock_resource(target_id, {})
        if isinstance(approved_probe, ConnectorError) and approved_probe.code == ConnectorErrorCode.PERMISSION_DENIED:
            return approved_probe
        return None
