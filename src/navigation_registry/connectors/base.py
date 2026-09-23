"""Connector interface skeleton for Navigation Registry adapters.

No live systems are called from this module. Implementations must return
normalized evidence only and must not grant write authorization.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class ConnectorErrorCode(str, Enum):
    AUTHENTICATION_FAILED = "AuthenticationFailed"
    PERMISSION_DENIED = "PermissionDenied"
    RESOURCE_MISSING = "ResourceMissing"
    RESOURCE_MOVED = "ResourceMoved"
    RATE_LIMITED = "RateLimited"
    SYSTEM_UNAVAILABLE = "SystemUnavailable"
    UNKNOWN_ERROR = "UnknownError"
    CONNECTOR_DEPRECATED = "ConnectorDeprecated"
    METADATA_INCOMPLETE = "MetadataIncomplete"
    SOURCE_OF_TRUTH_CONFLICT = "SourceOfTruthConflict"
    DUPLICATE_IDENTIFIER = "DuplicateIdentifier"
    VERIFICATION_FAILED = "VerificationFailed"


@dataclass(frozen=True)
class ConnectorError:
    code: ConnectorErrorCode
    severity: str
    retryable: bool
    message: str
    resource_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegistryResource:
    system: str
    entity_type: str
    canonical_id: str
    display_name: str
    parent: str | None
    owner: str | None
    source_of_truth: str
    verification_state: str
    cache_status: str
    human_review_required: bool
    write_allowed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class ReadOnlyConnector(Protocol):
    connector_id: str
    connector_name: str
    connector_version: str

    def lookup_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        """Return normalized read-only resource evidence for one id."""

    def verify_resource(self, resource_id: str) -> RegistryResource | ConnectorError:
        """Verify one resource without writing to the source system."""

    def report_health(self) -> dict[str, Any]:
        """Return connector health evidence without live writes."""
