import json
from pathlib import Path

from navigation_registry.connectors.base import ConnectorError, ConnectorErrorCode, RegistryResource
from navigation_registry.connectors.notion import NotionReadOnlyConnector


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "notion"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def connector_with_default_fixtures() -> NotionReadOnlyConnector:
    failures = load_fixture("failures.json")
    return NotionReadOnlyConnector(
        fixtures={
            "notion-page-001": load_fixture("page.json"),
            "notion-database-001": load_fixture("database.json"),
            "permission-denied": failures["permission_denied"],
            "incomplete-metadata": failures["incomplete_metadata"],
        }
    )


def test_page_fixture_normalizes_to_registry_resource() -> None:
    result = connector_with_default_fixtures().lookup_resource("notion-page-001")

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Page"
    assert result.canonical_id == "notion-page-001"
    assert result.parent == "notion-database-001"


def test_database_fixture_normalizes_to_registry_resource() -> None:
    result = connector_with_default_fixtures().lookup_resource("notion-database-001")

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Database"
    assert result.canonical_id == "notion-database-001"
    assert result.parent == "workspace"


def test_write_allowed_is_always_false() -> None:
    connector = connector_with_default_fixtures()

    page = connector.lookup_resource("notion-page-001")
    database = connector.lookup_resource("notion-database-001")

    assert isinstance(page, RegistryResource)
    assert isinstance(database, RegistryResource)
    assert page.write_allowed is False
    assert database.write_allowed is False


def test_page_body_read_is_false_by_default() -> None:
    result = connector_with_default_fixtures().lookup_resource("notion-page-001")

    assert isinstance(result, RegistryResource)
    assert result.metadata["page_body_read"] is False


def test_missing_resource_returns_resource_missing() -> None:
    result = connector_with_default_fixtures().lookup_resource("missing")

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.RESOURCE_MISSING
    assert result.retryable is True


def test_permission_failure_maps_to_permission_denied() -> None:
    result = connector_with_default_fixtures().lookup_resource("permission-denied")

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED
    assert result.severity == "critical"


def test_incomplete_metadata_maps_to_metadata_incomplete() -> None:
    result = connector_with_default_fixtures().lookup_resource("incomplete-metadata")

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.METADATA_INCOMPLETE


def test_connector_health_reports_no_live_system_access() -> None:
    health = connector_with_default_fixtures().report_health()

    assert health["live_system_access"] is False
    assert health["health_state"] == "Healthy"


def test_connector_write_capabilities_is_none() -> None:
    assert connector_with_default_fixtures().write_capabilities == "none"
