"""Pure bridge from Notion evidence into the Navigation Registry contract.

This module intentionally is not a Notion client. It performs no network calls,
constructs no credentials, imports no Google or Notion SDK, and writes nothing.
It only converts evidence from existing read layers into RegistryResource or
ConnectorError values:

- cached navigation-index records from 08_Tooling/notion-navigation-client
- live-shaped Notion payloads from the Workflow Scheduler read-only adapter
"""

from __future__ import annotations

from typing import Any, Iterable

from .base import ConnectorError, ConnectorErrorCode, RegistryResource

CACHED_NOTION_INDEX_SOURCE = "notion-navigation-index-cache"
LIVE_NOTION_SOURCE = "notion-live"

_KIND_TO_ENTITY_TYPE = {
    "dashboard": "Dashboard",
    "database": "Database",
    "field": "Property",
    "property": "Property",
    "workflow": "Workflow",
    "prompt": "Prompt",
    "duplicate-risk": "DuplicateRisk",
    "duplicate_risk": "DuplicateRisk",
}

_ID_FIELDS = (
    "Notion ID",
    "Notion Page ID",
    "Notion Database ID",
    "Database ID",
    "Dashboard ID",
    "Page ID",
    "Property ID",
    "ID",
)

_OWNER_FIELDS = (
    "Owner",
    "Owner Agent",
    "Agent Owner",
    "Responsible Agent",
    "Source of Truth Owner",
    "Owner / Source of Truth?",
)

_HUMAN_REVIEW_FIELDS = (
    "Human Review Needed?",
    "Human Review Required?",
    "Human Review?",
    "Requires Human Review?",
    "human_review_required",
)

_NAVIGATION_WARNING = (
    "navigation_warning",
    "Navigation Warning",
    "Warning",
)


class NotionContractAdapter:
    """Normalize existing Notion read evidence into RegistryResource values.

    The adapter has no read access of its own. Callers pass evidence already
    obtained from an approved cached lookup client or live read adapter.
    """

    connector_id = "notion-contract-adapter"
    connector_name = "Notion Contract Adapter"
    connector_version = "0.1.0"
    write_capabilities = "none"
    live_system_access = False

    def from_navigation_record(
        self, kind: str, record: dict[str, Any]
    ) -> RegistryResource | ConnectorError:
        """Normalize one cached navigation-index record.

        Cached records remain lookup evidence only. They never authorize writes
        and always carry live_verification_required=True.
        """

        normalized_kind = _normalize_kind(kind)
        entity_type = _KIND_TO_ENTITY_TYPE.get(normalized_kind)
        if entity_type is None:
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Unsupported cached Notion navigation record kind.",
                evidence={"kind": kind, "record_keys": sorted(record)},
            )

        display_name = _display_name_for_kind(normalized_kind, record)
        canonical_id = _first_present(record, _ID_FIELDS) or display_name
        if not canonical_id or not display_name:
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Cached Notion navigation record is missing an identifier or display name.",
                resource_id=canonical_id,
                evidence={"kind": kind, "record": record},
            )

        human_review_required = _requires_human_review(record) or entity_type == "DuplicateRisk"

        return RegistryResource(
            system="notion",
            entity_type=entity_type,
            canonical_id=canonical_id,
            display_name=display_name,
            parent=_parent_for_navigation_record(normalized_kind, record),
            owner=_first_present(record, _OWNER_FIELDS),
            source_of_truth=CACHED_NOTION_INDEX_SOURCE,
            verification_state="CachedOnly",
            cache_status="SessionCache",
            human_review_required=human_review_required,
            write_allowed=False,
            metadata={
                "evidence_source": CACHED_NOTION_INDEX_SOURCE,
                "lookup_kind": normalized_kind,
                "navigation_warning": _first_present(record, _NAVIGATION_WARNING),
                "live_verification_required": True,
                "write_boundary": "read-only-lookup-only",
                "raw_record": dict(record),
            },
        )

    def from_live_page_payload(self, payload: dict[str, Any]) -> RegistryResource | ConnectorError:
        """Normalize a live-shaped Notion page payload into contract evidence."""

        page_id = str(payload.get("id") or "")
        if not page_id:
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Live Notion page payload is missing id.",
                evidence={"payload_keys": sorted(payload)},
            )

        display_name = _page_title(payload) or page_id
        return RegistryResource(
            system="notion",
            entity_type="Page",
            canonical_id=page_id,
            display_name=display_name,
            parent=_parent_id(payload.get("parent")),
            owner=payload.get("owner"),
            source_of_truth=LIVE_NOTION_SOURCE,
            verification_state="VerifiedReadOnly",
            cache_status="LiveRead",
            human_review_required=_live_payload_requires_review(payload, display_name, page_id),
            write_allowed=False,
            metadata={
                "evidence_source": LIVE_NOTION_SOURCE,
                "url": payload.get("url"),
                "archived": bool(payload.get("archived", False)),
                "created_time": payload.get("created_time"),
                "last_edited_time": payload.get("last_edited_time"),
                "page_body_read": bool(payload.get("page_body_read", False)),
                "write_boundary": "read-only-live-evidence",
                "raw_payload": dict(payload),
            },
        )

    def from_live_database_payload(
        self, payload: dict[str, Any]
    ) -> RegistryResource | ConnectorError:
        """Normalize a live-shaped Notion database payload into contract evidence."""

        database_id = str(payload.get("id") or "")
        if not database_id:
            return _error(
                ConnectorErrorCode.METADATA_INCOMPLETE,
                "Live Notion database payload is missing id.",
                evidence={"payload_keys": sorted(payload)},
            )

        display_name = _database_title(payload) or database_id
        return RegistryResource(
            system="notion",
            entity_type="Database",
            canonical_id=database_id,
            display_name=display_name,
            parent=_parent_id(payload.get("parent")),
            owner=payload.get("owner"),
            source_of_truth=LIVE_NOTION_SOURCE,
            verification_state="VerifiedReadOnly",
            cache_status="LiveRead",
            human_review_required=_live_payload_requires_review(payload, display_name, database_id),
            write_allowed=False,
            metadata={
                "evidence_source": LIVE_NOTION_SOURCE,
                "url": payload.get("url"),
                "archived": bool(payload.get("archived", False)),
                "created_time": payload.get("created_time"),
                "last_edited_time": payload.get("last_edited_time"),
                "properties_schema_visible": bool(payload.get("properties")),
                "properties": payload.get("properties"),
                "write_boundary": "read-only-live-evidence",
                "raw_payload": dict(payload),
            },
        )

    def report_health(self) -> dict[str, Any]:
        """Return adapter health without probing any external system."""

        return {
            "connector_id": self.connector_id,
            "connector_name": self.connector_name,
            "connector_version": self.connector_version,
            "health_state": "Healthy",
            "live_system_access": self.live_system_access,
            "write_capabilities": self.write_capabilities,
            "role": "contract-normalization-bridge",
            "canonical_cached_lookup": "08_Tooling/notion-navigation-client/",
            "canonical_live_read": "08_Tooling/workflow-scheduler/src/workflow_scheduler/adapters/notion_readonly_adapter.py",
        }


def _display_name_for_kind(kind: str, record: dict[str, Any]) -> str | None:
    if kind == "dashboard":
        return _first_present(record, ("Dashboard Name", "Name", "Title"))
    if kind == "database":
        return _first_present(record, ("Database Name", "Name", "Title"))
    if kind in {"field", "property"}:
        return _first_present(record, ("Property Name", "Field Name", "Name", "Title"))
    if kind == "workflow":
        return _first_present(record, ("Workflow Name", "Name", "Title"))
    if kind == "prompt":
        return _first_present(record, ("Prompt Name", "Name", "Title"))
    if kind in {"duplicate-risk", "duplicate_risk"}:
        return _first_present(
            record,
            (
                "Suspect Field, Database, or Dashboard",
                "Suspect",
                "Similar To",
                "Name",
            ),
        )
    return None


def _parent_for_navigation_record(kind: str, record: dict[str, Any]) -> str | None:
    if kind in {"field", "property"}:
        return _first_present(record, ("Database Name", "Database", "Parent Database"))
    return _first_present(record, ("Parent", "Parent Database", "Database Name"))


def _page_title(payload: dict[str, Any]) -> str | None:
    title = payload.get("title") or payload.get("display_name") or payload.get("name")
    if title:
        return _plain_text(title)

    properties = payload.get("properties")
    if not isinstance(properties, dict):
        return None
    for property_value in properties.values():
        if not isinstance(property_value, dict):
            continue
        if property_value.get("type") == "title" and property_value.get("title"):
            return _plain_text(property_value.get("title"))
        if property_value.get("title"):
            return _plain_text(property_value.get("title"))
    return None


def _database_title(payload: dict[str, Any]) -> str | None:
    title = payload.get("title") or payload.get("display_name") or payload.get("name")
    if title:
        return _plain_text(title)
    return None


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("plain_text") or item.get("text", {}).get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(value, dict):
        if "plain_text" in value:
            return str(value.get("plain_text") or "")
        if "name" in value:
            return str(value.get("name") or "")
    return str(value).strip()


def _normalize_kind(kind: str) -> str:
    return kind.strip().lower().replace(" ", "-")


def _first_present(record: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _requires_human_review(record: dict[str, Any]) -> bool:
    for key in _HUMAN_REVIEW_FIELDS:
        if key in record:
            return _truthy(record.get(key))
    return False


def _live_payload_requires_review(payload: dict[str, Any], display_name: str, fallback_id: str) -> bool:
    return bool(
        payload.get("human_review_required", False)
        or payload.get("archived", False)
        or not display_name
        or display_name == fallback_id
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized.startswith("y") or normalized in {"true", "required", "needs review"}


def _parent_id(parent: Any) -> str | None:
    if not isinstance(parent, dict):
        return None
    return parent.get("database_id") or parent.get("page_id") or parent.get("workspace")


def _error(
    code: ConnectorErrorCode,
    message: str,
    *,
    resource_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> ConnectorError:
    return ConnectorError(
        code=code,
        severity="medium",
        retryable=False,
        message=message,
        resource_id=resource_id,
        evidence=evidence or {},
    )
