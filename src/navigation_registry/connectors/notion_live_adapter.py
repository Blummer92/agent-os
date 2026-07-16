"""Metadata-only wrapper for a future live read-only Notion adapter.

This adapter keeps the existing boundary checks but delegates metadata reads and
normalization to the B2 shared Notion read-only client.
"""

from __future__ import annotations

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_live_boundary import NotionLiveReadOnlyBoundary, NotionLiveReadOnlyConfig
from .notion_read_client import NotionMetadataReader, SharedNotionReadOnlyClient


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
        client: NotionMetadataReader,
    ) -> None:
        self._boundary = NotionLiveReadOnlyBoundary(config)
        self._config = config
        self._client = SharedNotionReadOnlyClient(
            metadata_reader=client,
            allowed_target_ids=config.allowed_target_ids,
        )

    def lookup_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        page_result = self.lookup_page_metadata(resource_id)
        if isinstance(page_result, RegistryResource):
            return page_result
        database_result = self.lookup_database_metadata(resource_id)
        if isinstance(database_result, RegistryResource):
            return database_result
        return page_result

    def verify_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        return self.lookup_resource(resource_id)

    def lookup_page_metadata(self, page_id: str) -> RegistryResource | ConnectorError:
        error = self._preflight(page_id)
        if error is not None:
            return error
        return self._client.lookup_page_metadata(page_id)

    def lookup_database_metadata(
        self, database_id: str
    ) -> RegistryResource | ConnectorError:
        error = self._preflight(database_id)
        if error is not None:
            return error
        return self._client.lookup_database_metadata(database_id)

    def read_page_body(self, page_id: str) -> ConnectorError:
        return self._boundary.read_page_body(page_id)

    def report_health(self) -> dict[str, object]:
        health = self._client.report_health()
        return {
            **health,
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
        if target_id not in self._config.allowed_target_ids:
            return ConnectorError(
                code=ConnectorErrorCode.PERMISSION_DENIED,
                severity="critical",
                retryable=False,
                message="Target id is not approved for live read-only Notion access.",
                resource_id=target_id,
            )
        return None


NotionMetadataClient = NotionMetadataReader
