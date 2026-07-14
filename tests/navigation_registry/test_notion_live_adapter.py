from typing import Any

from navigation_registry.connectors.base import ConnectorError, ConnectorErrorCode, RegistryResource
from navigation_registry.connectors.notion_live_adapter import NotionLiveReadOnlyAdapter
from navigation_registry.connectors.notion_live_boundary import NotionLiveReadOnlyConfig


APPROVED_PAGE = {
    "object": "page",
    "id": "approved-page-001",
    "title": "Approved Mock Page",
    "parent": {"database_id": "approved-database-001"},
    "owner": "Integration Manager",
    "url": "https://notion.example.invalid/approved-page-001",
    "created_time": "2026-07-14T00:00:00.000Z",
    "last_edited_time": "2026-07-14T00:00:00.000Z",
    "archived": False,
    "human_review_required": False,
}

APPROVED_DATABASE = {
    "object": "database",
    "id": "approved-database-001",
    "title": "Approved Mock Database",
    "parent": {"workspace": "workspace"},
    "owner": "Integration Manager",
    "url": "https://notion.example.invalid/approved-database-001",
    "created_time": "2026-07-14T00:00:00.000Z",
    "last_edited_time": "2026-07-14T00:00:00.000Z",
    "archived": False,
    "properties_schema_visible": True,
    "human_review_required": False,
}


class FakeMetadataClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.pages: dict[str, dict[str, Any]] = {"approved-page-001": APPROVED_PAGE}
        self.databases: dict[str, dict[str, Any]] = {
            "approved-database-001": APPROVED_DATABASE
        }

    def retrieve_page_metadata(self, page_id: str) -> dict[str, Any]:
        self.calls.append(("retrieve_page_metadata", page_id))
        return self.pages[page_id]

    def retrieve_database_metadata(self, database_id: str) -> dict[str, Any]:
        self.calls.append(("retrieve_database_metadata", database_id))
        return self.databases[database_id]


class ExplodingMetadataClient:
    def retrieve_page_metadata(self, page_id: str) -> dict[str, Any]:
        raise AssertionError("Client should not be called before boundary approval.")

    def retrieve_database_metadata(self, database_id: str) -> dict[str, Any]:
        raise AssertionError("Client should not be called before boundary approval.")


def config_from(env: dict[str, str]) -> NotionLiveReadOnlyConfig:
    return NotionLiveReadOnlyConfig.from_environment(env)


def approved_config() -> NotionLiveReadOnlyConfig:
    return config_from(
        {
            "NOTION_READONLY_TOKEN": "placeholder-token",
            "NOTION_ALLOWED_TARGET_IDS": "approved-page-001,approved-database-001",
            "NOTION_LIVE_MODE": "readonly",
        }
    )


def test_approved_page_metadata_normalizes_to_registry_resource() -> None:
    client = FakeMetadataClient()
    adapter = NotionLiveReadOnlyAdapter(approved_config(), client)

    result = adapter.lookup_page_metadata("approved-page-001")

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Page"
    assert result.canonical_id == "approved-page-001"
    assert result.parent == "approved-database-001"
    assert client.calls == [("retrieve_page_metadata", "approved-page-001")]


def test_approved_database_metadata_normalizes_to_registry_resource() -> None:
    client = FakeMetadataClient()
    adapter = NotionLiveReadOnlyAdapter(approved_config(), client)

    result = adapter.lookup_database_metadata("approved-database-001")

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Database"
    assert result.canonical_id == "approved-database-001"
    assert result.parent == "workspace"
    assert client.calls == [("retrieve_database_metadata", "approved-database-001")]


def test_returned_resources_keep_write_allowed_false() -> None:
    adapter = NotionLiveReadOnlyAdapter(approved_config(), FakeMetadataClient())

    page = adapter.lookup_page_metadata("approved-page-001")
    database = adapter.lookup_database_metadata("approved-database-001")

    assert isinstance(page, RegistryResource)
    assert isinstance(database, RegistryResource)
    assert page.write_allowed is False
    assert database.write_allowed is False


def test_unapproved_target_rejects_before_client_call() -> None:
    adapter = NotionLiveReadOnlyAdapter(approved_config(), ExplodingMetadataClient())

    result = adapter.lookup_page_metadata("unapproved-page-001")

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED
    assert result.resource_id == "unapproved-page-001"


def test_missing_token_rejects_before_client_call() -> None:
    adapter = NotionLiveReadOnlyAdapter(
        config_from(
            {
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        ),
        ExplodingMetadataClient(),
    )

    result = adapter.lookup_page_metadata("approved-page-001")

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.AUTHENTICATION_FAILED


def test_wrong_live_mode_rejects_before_client_call() -> None:
    adapter = NotionLiveReadOnlyAdapter(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "write",
            }
        ),
        ExplodingMetadataClient(),
    )

    result = adapter.lookup_page_metadata("approved-page-001")

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED


def test_mutation_methods_do_not_exist() -> None:
    adapter = NotionLiveReadOnlyAdapter(approved_config(), FakeMetadataClient())

    mutation_methods = {
        "create_page",
        "update_page",
        "delete_page",
        "archive_page",
        "move_page",
        "share_page",
        "create_database",
        "update_database",
        "delete_database",
        "write_cache_record",
        "repair_relationship",
    }

    assert adapter.write_capabilities == "none"
    assert all(not hasattr(adapter, method) for method in mutation_methods)


def test_page_body_read_remains_blocked() -> None:
    adapter = NotionLiveReadOnlyAdapter(approved_config(), FakeMetadataClient())

    result = adapter.read_page_body("approved-page-001")

    assert adapter.page_body_reads_enabled is False
    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED
