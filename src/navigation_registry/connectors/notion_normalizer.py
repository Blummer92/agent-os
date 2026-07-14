"""Normalize fixture-based Notion metadata into registry resources."""

from typing import Any

from .base import ConnectorError, ConnectorErrorCode, RegistryResource


_ALLOWED_TYPES = {"page": "Page", "database": "Database"}


def normalize_notion_resource(raw: dict[str, Any]) -> RegistryResource | ConnectorError:
    notion_type = raw.get("object")
    canonical_id = raw.get("id")
    title = raw.get("title") or raw.get("display_name")

    if notion_type not in _ALLOWED_TYPES or not canonical_id or not title:
        return ConnectorError(
            code=ConnectorErrorCode.METADATA_INCOMPLETE,
            severity="medium",
            retryable=False,
            message="Notion fixture is missing required metadata.",
            resource_id=canonical_id,
            evidence={"object": notion_type, "has_title": bool(title)},
        )

    return RegistryResource(
        system="notion",
        entity_type=_ALLOWED_TYPES[notion_type],
        canonical_id=canonical_id,
        display_name=title,
        parent=_parent_id(raw.get("parent")),
        owner=raw.get("owner"),
        source_of_truth="notion",
        verification_state="Verified",
        cache_status="FixtureOnly",
        human_review_required=bool(raw.get("human_review_required", False)),
        write_allowed=False,
        metadata={
            "url": raw.get("url"),
            "created_time": raw.get("created_time"),
            "last_edited_time": raw.get("last_edited_time"),
            "archived": bool(raw.get("archived", False)),
            "properties_schema_visible": bool(raw.get("properties_schema_visible", False)),
            "page_body_read": False,
        },
    )


def _parent_id(parent: dict[str, Any] | None) -> str | None:
    if not parent:
        return None
    return parent.get("database_id") or parent.get("page_id") or parent.get("workspace")
