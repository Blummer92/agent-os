"""Offline read-only Notion connector skeleton.

This module intentionally has no Notion SDK dependency, no credentials, and no
network behavior. It accepts fixture dictionaries so tests can prove contract
behavior before any live connector exists.
"""

from typing import Any

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_normalizer import normalize_notion_resource


class NotionReadOnlyConnector:
    connector_id = "notion-read-only"
    connector_name = "Notion Read-Only Connector"
    connector_version = "0.1.0"

    def __init__(self, fixtures: dict[str, dict[str, Any]] | None = None) -> None:
        self._fixtures = fixtures or {}

    @property
    def write_capabilities(self) -> str:
        return "none"

    def lookup_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        return self._read_fixture(resource_id)

    def verify_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        return self._read_fixture(resource_id)

    def report_health(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "connector_name": self.connector_name,
            "connector_version": self.connector_version,
            "health_state": "Healthy",
            "live_system_access": False,
            "write_capabilities": self.write_capabilities,
        }

    def _read_fixture(self, resource_id: str) -> RegistryResource | ConnectorError:
        fixture = self._fixtures.get(resource_id)
        if fixture is None:
            return ConnectorError(
                code=ConnectorErrorCode.RESOURCE_MISSING,
                severity="high",
                retryable=True,
                message="Fixture resource is missing; no live lookup attempted.",
                resource_id=resource_id,
            )
        if fixture.get("error"):
            return _fixture_error(resource_id, fixture)
        return normalize_notion_resource(fixture)


def _fixture_error(resource_id: str, fixture: dict[str, Any]) -> ConnectorError:
    code = ConnectorErrorCode(fixture.get("error", "UnknownError"))
    return ConnectorError(
        code=code,
        severity=fixture.get("severity", "medium"),
        retryable=bool(fixture.get("retryable", False)),
        message=fixture.get("message", code.value),
        resource_id=resource_id,
        evidence={"fixture": True},
    )
