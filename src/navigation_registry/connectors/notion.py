"""Deprecated compatibility fixture shim for Navigation Registry Notion evidence.

This module is not the canonical cached Notion lookup client and is not a live
Notion API reader. New production code should use:

- ``08_Tooling/notion-navigation-client/`` for cached navigation-index lookup;
- ``NotionContractAdapter`` for pure contract normalization; and
- the Workflow Scheduler ``notion_readonly_adapter.py`` for approved live reads.

``NotionReadOnlyConnector`` remains only to preserve existing fixture imports and
offline boundary tests. It has no SDK, credentials, network behavior, or writes.
"""

from typing import Any

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_normalizer import normalize_notion_resource


class NotionReadOnlyConnector:
    """Backward-compatible fixture shim; do not use as a production Notion client."""

    connector_id = "notion-read-only"
    connector_name = "Notion Fixture Compatibility Shim"
    connector_version = "0.2.0"
    role = "fixture-compatibility-shim"
    deprecated_for_new_code = True
    canonical_cached_lookup = "08_Tooling/notion-navigation-client/"
    canonical_contract_adapter = "src/navigation_registry/connectors/notion_contract_adapter.py"
    canonical_live_read = (
        "08_Tooling/workflow-scheduler/src/workflow_scheduler/adapters/"
        "notion_readonly_adapter.py"
    )

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
            "health_state": "CompatibilityOnly",
            "live_system_access": False,
            "write_capabilities": self.write_capabilities,
            "role": self.role,
            "deprecated_for_new_code": self.deprecated_for_new_code,
            "canonical_cached_lookup": self.canonical_cached_lookup,
            "canonical_contract_adapter": self.canonical_contract_adapter,
            "canonical_live_read": self.canonical_live_read,
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
