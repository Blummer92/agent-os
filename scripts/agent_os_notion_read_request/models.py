"""Typed contract for the #2283 bounded GitHub-controlled Notion read path.

This module owns only vocabulary and shapes. It performs no I/O, holds no
credential, and grants no authority. The finite request vocabulary maps onto the
*existing* #980 request-sensitive planning intent rather than introducing a
second curriculum vocabulary, planner, asset registry, or scheduler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Reuse the #2282 read-only action allowlist instead of restating it, so a later
# change to that seam cannot silently widen what this path may dispatch.
from navigation_registry.connectors.curriculum_execution_surface_router import (
    READ_ONLY_ACTIONS,
)

SCHEMA_VERSION = "1.0"

#: The only ingress reason this path will act on (#2283 transport identity).
INGRESS_REASON = "accepted-notion-read-envelope"

#: The existing #936 adapter credential name. Do not create a second vocabulary.
CREDENTIAL_ENV_VAR = "NOTION_TOKEN"

#: The finite repository-owned request classes. Anything else fails closed.
REQUEST_CLASSES: tuple[str, ...] = (
    "canonical-unit",
    "current-curriculum",
    "visual-assets",
    "teacher-modeling",
    "packet-materials",
)

#: Each request class resolves to already-resolved #980 intent. The read plan,
#: relation-first Visual Asset Library behavior, and every authority decision
#: stay owned by #980/#975/#973/#971; this table only selects the intent.
REQUEST_CLASS_INTENT: dict[str, dict[str, object]] = {
    "canonical-unit": {
        "action": "canonical-unit",
        "artifact_type": "none",
        "requires_reusable_assets": False,
    },
    "current-curriculum": {
        "action": "teach-next",
        "artifact_type": "lesson",
        "requires_reusable_assets": False,
    },
    "visual-assets": {
        "action": "images",
        "artifact_type": "images",
        "requires_reusable_assets": True,
    },
    "teacher-modeling": {
        "action": "modeling",
        "artifact_type": "none",
        "requires_reusable_assets": False,
    },
    "packet-materials": {
        "action": "packet-materials",
        "artifact_type": "worksheet",
        "requires_reusable_assets": False,
    },
}

#: Structured content-class constraint. Public projection is decided by the
#: declared class of the *source*, never by scanning result text for phrases.
PUBLIC_PROJECTABLE_CONTENT_CLASSES = frozenset(
    {"curriculum-metadata", "visual-asset-metadata"}
)

#: A binding is dispatchable only in this state. Historical leads, cached
#: samples, and fixture identities are never dispatchable.
VERIFIED_STATE = "verified-current"

#: Key classes that may never appear in a public projection. This is a
#: structural key-name guard over a schema-built payload, not a natural-language
#: blacklist: raw provider responses are not an input to projection at all.
CREDENTIAL_KEY_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "bearer",
    "cookie",
    "credential",
    "notion_token",
    "password",
    "secret",
    "session",
    "token",
)

AdmissionStatus = Literal["admitted", "rejected"]


def looks_like_notion_id(value: str) -> bool:
    """True for a bare Notion UUID, dashed or compact.

    A Notion id is lowercase hex and therefore satisfies the request-slug
    grammar. Recognizing the shape lets every layer refuse a provider target
    supplied as if it were a repository-owned request identity.
    """
    compact = value.replace("-", "")
    return len(compact) == 32 and all(
        character in "0123456789abcdef" for character in compact
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionReadSource:
    """One approved curriculum/asset source binding."""

    logical_source: str
    display_name: str
    data_source_id: str | None
    verification_state: str
    content_class: str

    @property
    def dispatchable(self) -> bool:
        return (
            self.verification_state == VERIFIED_STATE
            and isinstance(self.data_source_id, str)
            and bool(self.data_source_id.strip())
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalUnitBinding:
    """One canonical unit identity resolved internally from a request slug."""

    canonical_unit_key: str
    stable_id: str
    unit_status: str
    provider_page_id: str | None
    verification_state: str
    content_class: str

    @property
    def dispatchable(self) -> bool:
        return (
            self.verification_state == VERIFIED_STATE
            and isinstance(self.provider_page_id, str)
            and bool(self.provider_page_id.strip())
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionReadRequestRecord:
    """One repository-owned request. Comment text never supplies these fields."""

    request_id: str
    request_class: str
    canonical_unit_key: str
    issue_number: int


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionReadCatalog:
    """The finite repository-owned request/source catalog."""

    schema_version: str
    repository: str
    credential_env_var: str
    requests: tuple[NotionReadRequestRecord, ...]
    sources: tuple[NotionReadSource, ...]
    canonical_units: tuple[CanonicalUnitBinding, ...]

    def request(self, request_id: str) -> NotionReadRequestRecord | None:
        for record in self.requests:
            if record.request_id == request_id:
                return record
        return None

    def source(self, logical_source: str) -> NotionReadSource | None:
        for record in self.sources:
            if record.logical_source == logical_source:
                return record
        return None

    def canonical_unit(self, canonical_unit_key: str) -> CanonicalUnitBinding | None:
        for record in self.canonical_units:
            if record.canonical_unit_key == canonical_unit_key:
                return record
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionReadAdmission:
    """Fail-closed admission decision.

    ``secret_dispatch_authorized`` is the single gate every secret-bearing or
    network step must consult. It is true only when every identity, target,
    replay, vocabulary, and source constraint held.
    """

    schema_version: str = SCHEMA_VERSION
    status: AdmissionStatus
    reason_codes: tuple[str, ...]
    repository: str
    issue_number: int | None = None
    request_id: str | None = None
    request_class: str | None = None
    canonical_unit_key: str | None = None
    required_logical_sources: tuple[str, ...] = ()
    allowed_read_actions: tuple[str, ...] = tuple(sorted(READ_ONLY_ACTIONS))
    secret_dispatch_authorized: bool = False
    write_allowed: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    notion_write_reachable: Literal[False] = field(default=False, init=False)
    gce_required: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "repository": self.repository,
            "issue_number": self.issue_number,
            "request_id": self.request_id,
            "request_class": self.request_class,
            "canonical_unit_key": self.canonical_unit_key,
            "required_logical_sources": list(self.required_logical_sources),
            "allowed_read_actions": list(self.allowed_read_actions),
            "secret_dispatch_authorized": self.secret_dispatch_authorized,
            "write_allowed": False,
            "production_authorized": False,
            "notion_write_reachable": False,
            "gce_required": False,
        }


class NotionReadRequestError(ValueError):
    """Fail-closed error for catalog, admission, execution, or projection."""


__all__ = [
    "CREDENTIAL_ENV_VAR",
    "CREDENTIAL_KEY_FRAGMENTS",
    "INGRESS_REASON",
    "PUBLIC_PROJECTABLE_CONTENT_CLASSES",
    "REQUEST_CLASSES",
    "REQUEST_CLASS_INTENT",
    "SCHEMA_VERSION",
    "VERIFIED_STATE",
    "CanonicalUnitBinding",
    "NotionReadAdmission",
    "NotionReadCatalog",
    "NotionReadRequestError",
    "NotionReadRequestRecord",
    "NotionReadSource",
]
