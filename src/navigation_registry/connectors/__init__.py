"""Connector adapters for the Navigation Registry offline prototype."""

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion import NotionReadOnlyConnector
from .notion_read_client import (
    CONTRACT_NAME,
    CONTRACT_VERSION,
    NotionMetadataReader,
    NotionReadOnlyClient,
    SharedNotionReadOnlyClient,
)

__all__ = [
    "CONTRACT_NAME",
    "CONTRACT_VERSION",
    "ConnectorError",
    "ConnectorErrorCode",
    "NotionMetadataReader",
    "NotionReadOnlyClient",
    "NotionReadOnlyConnector",
    "RegistryResource",
    "SharedNotionReadOnlyClient",
]
