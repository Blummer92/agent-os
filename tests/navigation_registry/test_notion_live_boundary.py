from collections.abc import Iterator, Mapping
from typing import Any

from navigation_registry.connectors.base import ConnectorError, ConnectorErrorCode, RegistryResource
from navigation_registry.connectors.notion_live_boundary import (
    NotionLiveReadOnlyBoundary,
    NotionLiveReadOnlyConfig,
)


class ExplodingPayloads(Mapping[str, dict[str, Any]]):
    """Mapping that fails if accessed before target approval."""

    def __getitem__(self, key: str) -> dict[str, Any]:
        raise AssertionError("Mock payloads should not be accessed for unapproved targets.")

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


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


def config_from(env: dict[str, str]) -> NotionLiveReadOnlyConfig:
    return NotionLiveReadOnlyConfig.from_environment(env)


def test_missing_token_disables_live_mode() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        )
    )

    result = boundary.lookup_mock_resource("approved-page-001", {"approved-page-001": APPROVED_PAGE})

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.AUTHENTICATION_FAILED


def test_live_mode_must_equal_readonly() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "write",
            }
        )
    )

    result = boundary.lookup_mock_resource("approved-page-001", {"approved-page-001": APPROVED_PAGE})

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED


def test_unapproved_target_ids_are_rejected_before_payload_access() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        )
    )

    result = boundary.lookup_mock_resource("unapproved-page-001", ExplodingPayloads())

    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED
    assert result.resource_id == "unapproved-page-001"


def test_boundary_exposes_no_mutation_methods() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        )
    )

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

    assert boundary.write_capabilities == "none"
    assert all(not hasattr(boundary, method) for method in mutation_methods)


def test_page_body_reads_are_blocked_by_default() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        )
    )

    result = boundary.read_page_body("approved-page-001")

    assert boundary.page_body_reads_enabled is False
    assert isinstance(result, ConnectorError)
    assert result.code == ConnectorErrorCode.PERMISSION_DENIED


def test_returned_mock_resources_keep_write_allowed_false() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        )
    )

    result = boundary.lookup_mock_resource("approved-page-001", {"approved-page-001": APPROVED_PAGE})

    assert isinstance(result, RegistryResource)
    assert result.write_allowed is False


def test_approved_mock_payload_normalizes_to_registry_resource() -> None:
    boundary = NotionLiveReadOnlyBoundary(
        config_from(
            {
                "NOTION_READONLY_TOKEN": "placeholder-token",
                "NOTION_ALLOWED_TARGET_IDS": "approved-page-001",
                "NOTION_LIVE_MODE": "readonly",
            }
        )
    )

    result = boundary.lookup_mock_resource("approved-page-001", {"approved-page-001": APPROVED_PAGE})

    assert isinstance(result, RegistryResource)
    assert result.system == "notion"
    assert result.entity_type == "Page"
    assert result.canonical_id == "approved-page-001"
    assert result.parent == "approved-database-001"
    assert result.metadata["page_body_read"] is False
