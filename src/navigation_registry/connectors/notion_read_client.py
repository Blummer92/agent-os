"""Shared read-only Notion client for the Navigation Registry Read Contract.

This module is the B2 shared client target for downstream connector migrations.
It has no Notion SDK dependency and exposes no mutation methods. Callers inject
read-only metadata access or fixture payloads; the client normalizes the result
into the canonical Navigation Registry connector model.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .base import ConnectorError, ConnectorErrorCode, RegistryResource
from .notion_normalizer import normalize_notion_resource

CONTRACT_NAME = "Navigation Registry Read Contract"
CONTRACT_VERSION = "0.1.0"


class NotionMetadataReader(Protocol):
    """Minimal dependency-injected Notion metadata reader.

    Implementations must perform metadata-only reads. Page body reads and all
    mutation methods stay outside this protocol by design.
    """

    def retrieve_page_metadata(self, page_id: str) -> dict[str, Any]:
        """Return page metadata without page body content."""

    def retrieve_database_metadata(self, database_id: str) -> dict[str, Any]:
        """Return database metadata."""


class SharedNotionReadOnlyClient:
    """Canonical shared Notion read client for Agent OS connectors.

    The client implements the Navigation Registry Read Contract by returning
    normalized RegistryResource evidence or ConnectorError values. It never
    writes to Notion, never reads page bodies, and never treats lookup evidence
    as write authorization.
    """

    connector_id = "notion-shared-readonly-client"
    connector_name = "Shared Notion Read-Only Client"
    connector_version = CONTRACT_VERSION
    contract_name = CONTRACT_NAME
    contract_version = CONTRACT_VERSION
    write_capabilities = "none"
    page_body_reads_enabled = False

    def __init__(
        self,
        *,
        metadata_reader: NotionMetadataReader | None = None,
        fixtures: Mapping[str, dict[str, Any]] | None = None,
        allowed_target_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._metadata_reader = metadata_reader
        self._fixtures = fixtures or {}
        self._allowed_target_ids = frozenset(allowed_target_ids or ())

    def lookup_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        """Return normalized read-only evidence for a page or database id."""
        fixture_result = self._lookup_fixture(resource_id)
        if fixture_result is not None:
            return fixture_result
        if self._metadata_reader is None:
            return self._missing(resource_id)
        if not self._is_target_allowed(resource_id):
            return self._permission_denied(resource_id)
        return self._lookup_metadata(resource_id)

    def verify_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        """Verify one resource through the same read-only lookup path."""
        return self.lookup_resource(resource_id)

    def lookup_page_metadata(self, page_id: str) -> RegistryResource | ConnectorError:
        """Read page metadata only; page body content remains blocked."""
        if not self._can_use_metadata_reader(page_id):
            return self._metadata_reader_error(page_id)
        try:
            return self._normalize(self._metadata_reader.retrieve_page_metadata(page_id))
        except Exception as exc:  # pragma: no cover - defensive client mapping
            return self._reader_failure(page_id, exc)

    def lookup_database_metadata(self, database_id: str) -> RegistryResource | ConnectorError:
        """Read database metadata through the injected read-only reader."""
        if not self._can_use_metadata_reader(database_id):
            return self._metadata_reader_error(database_id)
        try:
            return self._normalize(self._metadata_reader.retrieve_database_metadata(database_id))
        except Exception as exc:  # pragma: no cover - defensive client mapping
            return self._reader_failure(database_id, exc)

    def read_page_body(self, page_id: str) -> ConnectorError:
        """Block page-body reads so this client stays metadata-only."""
        return ConnectorError(
            code=ConnectorErrorCode.PERMISSION_DENIED,
            severity="critical",
            retryable=False,
            message="Page-body reads are outside the Navigation Registry Read Contract.",
            resource_id=page_id,
            evidence={"contract_name": self.contract_name},
        )

    def report_health(self) -> dict[str, Any]:
        """Return health evidence without writing or probing live systems."""
        return {
            "connector_id": self.connector_id,
            "connector_name": self.connector_name,
            "connector_version": self.connector_version,
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "health_state": "Healthy",
            "live_system_access": self._metadata_reader is not None,
            "write_capabilities": self.write_capabilities,
            "page_body_reads_enabled": self.page_body_reads_enabled,
        }

    def _lookup_fixture(self, resource_id: str) -> RegistryResource | ConnectorError | None:
        fixture = self._fixtures.get(resource_id)
        if fixture is None:
            return None
        if fixture.get("error"):
            return ConnectorError(
                code=ConnectorErrorCode(fixture.get("error", "UnknownError")),
                severity=fixture.get("severity", "medium"),
                retryable=bool(fixture.get("retryable", False)),
                message=fixture.get("message", "Fixture error."),
                resource_id=resource_id,
                evidence={"fixture": True, "contract_name": self.contract_name},
            )
        return self._normalize(fixture)

    def _lookup_metadata(self, resource_id: str) -> RegistryResource | ConnectorError:
        page_result = self.lookup_page_metadata(resource_id)
        if isinstance(page_result, RegistryResource):
            return page_result
        database_result = self.lookup_database_metadata(resource_id)
        if isinstance(database_result, RegistryResource):
            return database_result
        return page_result

    def _normalize(self, raw: dict[str, Any]) -> RegistryResource | ConnectorError:
        result = normalize_notion_resource(raw)
        if isinstance(result, RegistryResource):
            return RegistryResource(
                system=result.system,
                entity_type=result.entity_type,
                canonical_id=result.canonical_id,
                display_name=result.display_name,
                parent=result.parent,
                owner=result.owner,
                source_of_truth=result.source_of_truth,
                verification_state=result.verification_state,
                cache_status=result.cache_status,
                human_review_required=result.human_review_required,
                write_allowed=False,
                metadata={
                    **result.metadata,
                    "contract_name": self.contract_name,
                    "contract_version": self.contract_version,
                    "page_body_read": False,
                    "write_boundary": "read-only",
                },
            )
        return result

    def _can_use_metadata_reader(self, resource_id: str) -> bool:
        return self._metadata_reader is not None and self._is_target_allowed(resource_id)

    def _metadata_reader_error(self, resource_id: str) -> ConnectorError:
        if self._metadata_reader is None:
            return self._missing(resource_id)
        return self._permission_denied(resource_id)

    def _is_target_allowed(self, resource_id: str) -> bool:
        return not self._allowed_target_ids or resource_id in self._allowed_target_ids

    def _missing(self, resource_id: str) -> ConnectorError:
        return ConnectorError(
            code=ConnectorErrorCode.RESOURCE_MISSING,
            severity="high",
            retryable=True,
            message="Resource is missing; no write or broad live search attempted.",
            resource_id=resource_id,
            evidence={"contract_name": self.contract_name},
        )

    def _permission_denied(self, resource_id: str) -> ConnectorError:
        return ConnectorError(
            code=ConnectorErrorCode.PERMISSION_DENIED,
            severity="critical",
            retryable=False,
            message="Target id is not approved for shared read-only Notion access.",
            resource_id=resource_id,
            evidence={"contract_name": self.contract_name},
        )

    def _reader_failure(self, resource_id: str, exc: Exception) -> ConnectorError:
        return ConnectorError(
            code=ConnectorErrorCode.UNKNOWN_ERROR,
            severity="high",
            retryable=True,
            message="Injected Notion metadata reader failed during read-only lookup.",
            resource_id=resource_id,
            evidence={"error_type": type(exc).__name__, "contract_name": self.contract_name},
        )


NotionReadOnlyClient = SharedNotionReadOnlyClient
