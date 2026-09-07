"""Normalize fixture-based Notion metadata into registry resources."""

from typing import Any

from .base import ConnectorError, ConnectorErrorCode, RegistryResource


_ALLOWED_TYPES = {"page": "Page", "database": "Database"}
_BOOLEAN_FIELDS = {
    "human_review_required": False,
    "archived": False,
    "properties_schema_visible": False,
}


def normalize_notion_resource(raw: dict[str, Any]) -> RegistryResource | ConnectorError:
    notion_type = raw.get("object")
    canonical_id = raw.get("id")
    title = raw.get("title") or raw.get("display_name")

    if notion_type not in _ALLOWED_TYPES or not canonical_id or not title:
        return _metadata_error(canonical_id, notion_type=notion_type, title=title)

    booleans: dict[str, bool] = {}
    for field, default in _BOOLEAN_FIELDS.items():
        value = raw.get(field, default)
        if type(value) is not bool:
            return _metadata_error(
                canonical_id,
                notion_type=notion_type,
                title=title,
                malformed_boolean=field,
            )
        booleans[field] = value

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
        human_review_required=booleans["human_review_required"],
        write_allowed=False,
        metadata={
            "url": raw.get("url"),
            "created_time": raw.get("created_time"),
            "last_edited_time": raw.get("last_edited_time"),
            "archived": booleans["archived"],
            "properties_schema_visible": booleans["properties_schema_visible"],
            "page_body_read": False,
        },
    )


def _metadata_error(
    canonical_id: object,
    *,
    notion_type: object,
    title: object,
    malformed_boolean: str | None = None,
) -> ConnectorError:
    evidence: dict[str, object] = {"object": notion_type, "has_title": bool(title)}
    if malformed_boolean is not None:
        evidence["malformed_boolean"] = malformed_boolean
    return ConnectorError(
        code=ConnectorErrorCode.METADATA_INCOMPLETE,
        severity="medium",
        retryable=False,
        message="Notion fixture is missing or contains malformed required metadata.",
        resource_id=canonical_id if isinstance(canonical_id, str) else None,
        evidence=evidence,
    )


def _parent_id(parent: dict[str, Any] | None) -> str | None:
    if not parent:
        return None
    return parent.get("database_id") or parent.get("page_id") or parent.get("workspace")
