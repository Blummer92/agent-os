"""Immutable models for the pure-local Notion curriculum preflight.

The module consumes caller-supplied evidence only. It performs no filesystem,
clock, environment, credential, network, subprocess, Scheduler, Notion, Drive,
or connector access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from instructional_workflow_contracts.common import (
    ContractValidationError,
    canonical_json_bytes,
    canonical_size,
    freeze_json,
    sanitize_detail,
    validate_revision,
    validate_sha256,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

CONTRACT_VERSION = "1.0"
SUPPORTED_NOTION_API_VERSION = "2026-03-11"
EVIDENCE_TTL_HOURS = 24

MAX_EVIDENCE_BYTES = 256 * 1024
MAX_REPORT_BYTES = 32 * 1024
MAX_PROPERTIES = 256
MAX_RELATIONS = 128
MAX_VIEWS = 64
MAX_MAPPINGS = 256
MAX_FINDINGS = 64
MAX_BLOCKERS = 32
MAX_MANUAL_VERIFICATIONS = 64
MAX_STRING_LENGTH = 512
MAX_DETAIL_LENGTH = 500

PROPOSED_IMPLEMENTATION_SCOPE = (
    "scripts/agent_os_notion_curriculum_preflight/__init__.py",
    "scripts/agent_os_notion_curriculum_preflight/models.py",
    "scripts/agent_os_notion_curriculum_preflight/core.py",
    "scripts/agent_os_notion_curriculum_preflight/README.md",
    "tests/agent_os_notion_curriculum_preflight/test_core.py",
    "tests/fixtures/agent_os_notion_curriculum_preflight/",
)

FINDING_CODES = frozenset(
    {
        "notion-target-unverified",
        "notion-api-version-mismatch",
        "notion-database-data-source-mismatch",
        "notion-schema-stale",
        "notion-view-stale",
        "notion-property-id-missing",
        "notion-property-conflict",
        "notion-property-type-mismatch",
        "notion-relation-target-unshared",
        "notion-relation-ambiguous",
        "notion-readiness-owner-conflict",
        "notion-governed-field-write-proposed",
        "notion-value-limit-exceeded",
        "notion-pagination-incomplete",
        "notion-rate-limit-policy-unknown",
        "notion-view-capability-unsupported",
        "notion-view-target-ambiguous",
        "notion-view-write-not-authorized",
        "notion-write-mode-not-authorized",
        "notion-evidence-expired",
        "notion-migration-not-reversible",
        "notion-projection-unbounded",
        "notion-contract-version-incompatible",
    }
)

PROPERTY_CLASSIFICATIONS = frozenset(
    {"teacher-entered", "agent-suggested", "owner-governed", "display-only"}
)
WRITE_MODES = frozenset({"read-only", "local-draft", "append-only", "canonical-update"})
EFFECTS = frozenset({"none", "reference-only", "advisory", "governed"})
EVIDENCE_STATES = frozenset(
    {"verified", "stale", "unverified", "conflicting", "missing", "inaccessible", "ambiguous"}
)
RELATION_ACCESS_STATES = frozenset(
    {"verified", "denied", "missing-or-hidden", "unverified", "transient-error", "trashed"}
)
RELATION_AMBIGUITY_STATES = frozenset({"unambiguous", "ambiguous", "unknown"})
VIEW_CAPABILITY_STATES = frozenset({"supported", "unsupported", "unknown"})
VIEW_COMPATIBILITY_STATES = frozenset({"compatible", "incompatible", "unknown"})
PROJECTION_MODES = frozenset(
    {"reference-only", "display-only", "agent-suggested", "teacher-entered", "owner-governed"}
)
SUPPORTED_CONTRACT_NAMES = frozenset(
    {
        "curriculum-workflow-handoff-v1",
        "curriculum-material-requirement-v1",
        "curriculum-artifact-manifest-v1",
        "curriculum-artifact-reuse-plan-v1",
    }
)


class PreflightStatus(str, Enum):
    READY_FOR_LOCAL_DRAFT_IMPLEMENTATION = "ready-for-local-draft-implementation"
    BLOCKED = "blocked"
    MANUAL_REVIEW_REQUIRED = "manual-review-required"
    INVALID = "invalid"


class NotionCurriculumPreflightError(ValueError):
    """Bounded failure for supplied preflight evidence."""

    def __init__(self, finding_code: str, detail: str) -> None:
        if finding_code not in FINDING_CODES:
            finding_code = "notion-target-unverified"
        self.finding_code = finding_code
        self.detail = sanitize_detail(detail)[:MAX_DETAIL_LENGTH]
        super().__init__(self.detail)


def _wrap_common_error(finding_code: str, callback: Any, *args: Any) -> Any:
    try:
        return callback(*args)
    except ContractValidationError as exc:
        raise NotionCurriculumPreflightError(finding_code, exc.detail) from exc
    except (TypeError, ValueError) as exc:
        raise NotionCurriculumPreflightError(finding_code, str(exc)) from exc


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and type(value) is str and value == "":
        return value
    return _wrap_common_error(
        "notion-target-unverified",
        validate_text,
        value,
        name,
    )


def _stable_id(value: object, name: str, *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    return _wrap_common_error("notion-target-unverified", validate_stable_id, value, name)


def _version(value: object) -> str:
    return _wrap_common_error("notion-contract-version-incompatible", validate_version, value)


def _revision(value: object) -> int:
    return _wrap_common_error("notion-target-unverified", validate_revision, value)


def _timestamp(value: object, name: str) -> str:
    return _wrap_common_error("notion-target-unverified", validate_timestamp, value, name)


def _sha256(value: object, name: str, *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    return _wrap_common_error("notion-target-unverified", validate_sha256, value, name)


def _exact_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise NotionCurriculumPreflightError(
            "notion-target-unverified", f"{name} must be a built-in bool"
        )
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise NotionCurriculumPreflightError(
            "notion-value-limit-exceeded", f"{name} must be a positive built-in integer"
        )
    return value


def _member(value: object, name: str, allowed: frozenset[str]) -> str:
    text = _text(value, name)
    if text not in allowed:
        raise NotionCurriculumPreflightError(
            "notion-target-unverified", f"{name} is outside the supported vocabulary"
        )
    return text


def _exact_tuple(value: object, name: str, maximum: int) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise NotionCurriculumPreflightError(
            "notion-target-unverified", f"{name} must be an exact tuple"
        )
    if len(value) > maximum:
        raise NotionCurriculumPreflightError(
            "notion-value-limit-exceeded", f"{name} exceeds its collection bound"
        )
    return value


def _codes(value: object, name: str, maximum: int) -> tuple[str, ...]:
    values = _exact_tuple(value, name, maximum)
    checked: list[str] = []
    for item in values:
        text = _text(item, name)
        if text not in FINDING_CODES:
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", f"{name} contains an unsupported finding code"
            )
        checked.append(text)
    return tuple(sorted(set(checked)))


def _large_canonical_size(value: object) -> int:
    """Measure already-validated evidence through the shared canonical encoder."""

    return len(canonical_json_bytes(freeze_json(value)))


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionPropertyEvidence:
    property_id: str | None
    display_name: str
    property_type: str
    value_owner: str
    record_owner: str
    classification: str
    current_write_mode: str
    readiness_effect: str
    generation_effect: str
    relation_target_data_source_id: str | None
    maximum_value_size: int
    evidence_state: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "property_id", _stable_id(self.property_id, "property_id", allow_none=True))
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name"))
        object.__setattr__(self, "property_type", _text(self.property_type, "property_type"))
        object.__setattr__(self, "value_owner", _stable_id(self.value_owner, "value_owner"))
        object.__setattr__(self, "record_owner", _stable_id(self.record_owner, "record_owner"))
        object.__setattr__(
            self,
            "classification",
            _member(self.classification, "classification", PROPERTY_CLASSIFICATIONS),
        )
        object.__setattr__(
            self, "current_write_mode", _member(self.current_write_mode, "current_write_mode", WRITE_MODES)
        )
        object.__setattr__(
            self, "readiness_effect", _member(self.readiness_effect, "readiness_effect", EFFECTS)
        )
        object.__setattr__(
            self, "generation_effect", _member(self.generation_effect, "generation_effect", EFFECTS)
        )
        object.__setattr__(
            self,
            "relation_target_data_source_id",
            _stable_id(
                self.relation_target_data_source_id,
                "relation_target_data_source_id",
                allow_none=True,
            ),
        )
        object.__setattr__(
            self,
            "maximum_value_size",
            _positive_int(self.maximum_value_size, "maximum_value_size"),
        )
        object.__setattr__(
            self, "evidence_state", _member(self.evidence_state, "evidence_state", EVIDENCE_STATES)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "display_name": self.display_name,
            "property_type": self.property_type,
            "value_owner": self.value_owner,
            "record_owner": self.record_owner,
            "classification": self.classification,
            "current_write_mode": self.current_write_mode,
            "readiness_effect": self.readiness_effect,
            "generation_effect": self.generation_effect,
            "relation_target_data_source_id": self.relation_target_data_source_id,
            "maximum_value_size": self.maximum_value_size,
            "evidence_state": self.evidence_state,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionRelationEvidence:
    property_id: str | None
    source_data_source_id: str
    target_data_source_id: str
    target_shared_with_connection: bool
    access_state: str
    ambiguity_state: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "property_id", _stable_id(self.property_id, "relation property_id", allow_none=True))
        object.__setattr__(
            self, "source_data_source_id", _stable_id(self.source_data_source_id, "source_data_source_id")
        )
        object.__setattr__(
            self, "target_data_source_id", _stable_id(self.target_data_source_id, "target_data_source_id")
        )
        object.__setattr__(
            self,
            "target_shared_with_connection",
            _exact_bool(self.target_shared_with_connection, "target_shared_with_connection"),
        )
        object.__setattr__(
            self, "access_state", _member(self.access_state, "access_state", RELATION_ACCESS_STATES)
        )
        object.__setattr__(
            self,
            "ambiguity_state",
            _member(self.ambiguity_state, "ambiguity_state", RELATION_AMBIGUITY_STATES),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "property_id": self.property_id,
            "source_data_source_id": self.source_data_source_id,
            "target_data_source_id": self.target_data_source_id,
            "target_shared_with_connection": self.target_shared_with_connection,
            "access_state": self.access_state,
            "ambiguity_state": self.ambiguity_state,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionViewEvidence:
    view_id: str | None
    parent_data_source_id: str
    view_type: str
    capability_state: str
    filter_sort_compatibility: str
    evidence_state: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_id", _stable_id(self.view_id, "view_id", allow_none=True))
        object.__setattr__(
            self, "parent_data_source_id", _stable_id(self.parent_data_source_id, "parent_data_source_id")
        )
        object.__setattr__(self, "view_type", _text(self.view_type, "view_type"))
        object.__setattr__(
            self, "capability_state", _member(self.capability_state, "capability_state", VIEW_CAPABILITY_STATES)
        )
        object.__setattr__(
            self,
            "filter_sort_compatibility",
            _member(
                self.filter_sort_compatibility,
                "filter_sort_compatibility",
                VIEW_COMPATIBILITY_STATES,
            ),
        )
        object.__setattr__(
            self, "evidence_state", _member(self.evidence_state, "view evidence_state", EVIDENCE_STATES)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "view_id": self.view_id,
            "parent_data_source_id": self.parent_data_source_id,
            "view_type": self.view_type,
            "capability_state": self.capability_state,
            "filter_sort_compatibility": self.filter_sort_compatibility,
            "evidence_state": self.evidence_state,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ContractMappingCandidate:
    contract_name: str
    contract_version: str
    source_field: str
    target_property_id: str | None
    projection_mode: str
    owner_compatible: bool
    type_compatible: bool
    bounded: bool
    governed_field: bool

    def __post_init__(self) -> None:
        contract_name = _text(self.contract_name, "contract_name")
        if contract_name not in SUPPORTED_CONTRACT_NAMES:
            raise NotionCurriculumPreflightError(
                "notion-contract-version-incompatible", "contract_name is unsupported"
            )
        object.__setattr__(self, "contract_name", contract_name)
        object.__setattr__(self, "contract_version", _version(self.contract_version))
        object.__setattr__(self, "source_field", _text(self.source_field, "source_field"))
        object.__setattr__(
            self, "target_property_id", _stable_id(self.target_property_id, "target_property_id", allow_none=True)
        )
        object.__setattr__(
            self, "projection_mode", _member(self.projection_mode, "projection_mode", PROJECTION_MODES)
        )
        object.__setattr__(self, "owner_compatible", _exact_bool(self.owner_compatible, "owner_compatible"))
        object.__setattr__(self, "type_compatible", _exact_bool(self.type_compatible, "type_compatible"))
        object.__setattr__(self, "bounded", _exact_bool(self.bounded, "bounded"))
        object.__setattr__(self, "governed_field", _exact_bool(self.governed_field, "governed_field"))

    @property
    def identity(self) -> str:
        target = self.target_property_id or "missing"
        return f"{self.contract_name}:{self.source_field}->{target}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "contract_version": self.contract_version,
            "source_field": self.source_field,
            "target_property_id": self.target_property_id,
            "projection_mode": self.projection_mode,
            "owner_compatible": self.owner_compatible,
            "type_compatible": self.type_compatible,
            "bounded": self.bounded,
            "governed_field": self.governed_field,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionLimitEvidence:
    page_size_limit: int
    pagination_complete: bool
    property_value_limit: int
    collection_limit: int
    payload_limit: int
    rate_limit_policy_known: bool
    retry_after_supported: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "page_size_limit", _positive_int(self.page_size_limit, "page_size_limit"))
        object.__setattr__(
            self, "pagination_complete", _exact_bool(self.pagination_complete, "pagination_complete")
        )
        object.__setattr__(
            self, "property_value_limit", _positive_int(self.property_value_limit, "property_value_limit")
        )
        object.__setattr__(self, "collection_limit", _positive_int(self.collection_limit, "collection_limit"))
        object.__setattr__(self, "payload_limit", _positive_int(self.payload_limit, "payload_limit"))
        object.__setattr__(
            self,
            "rate_limit_policy_known",
            _exact_bool(self.rate_limit_policy_known, "rate_limit_policy_known"),
        )
        object.__setattr__(
            self, "retry_after_supported", _exact_bool(self.retry_after_supported, "retry_after_supported")
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "page_size_limit": self.page_size_limit,
            "pagination_complete": self.pagination_complete,
            "property_value_limit": self.property_value_limit,
            "collection_limit": self.collection_limit,
            "payload_limit": self.payload_limit,
            "rate_limit_policy_known": self.rate_limit_policy_known,
            "retry_after_supported": self.retry_after_supported,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionAuthorizationEvidence:
    live_read_authorized: Literal[False] = False
    write_authorized: Literal[False] = False
    schema_change_authorized: Literal[False] = False
    view_change_authorized: Literal[False] = False
    production_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    def __post_init__(self) -> None:
        fields = (
            ("live_read_authorized", self.live_read_authorized),
            ("write_authorized", self.write_authorized),
            ("schema_change_authorized", self.schema_change_authorized),
            ("view_change_authorized", self.view_change_authorized),
            ("production_authorized", self.production_authorized),
            ("publication_authorized", self.publication_authorized),
        )
        for name, value in fields:
            _exact_bool(value, name)
            if value:
                raise NotionCurriculumPreflightError(
                    "notion-write-mode-not-authorized", f"{name} must remain false"
                )

    def to_payload(self) -> dict[str, Any]:
        return {
            "live_read_authorized": False,
            "write_authorized": False,
            "schema_change_authorized": False,
            "view_change_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionCurriculumPreflightEvidence:
    contract_version: str
    record_revision: int
    evidence_id: str
    workspace_context_id: str
    notion_api_version: str
    database_id: str | None
    data_source_id: str | None
    evidence_source: str
    verified_at: str
    schema_fingerprint: str | None
    view_fingerprint: str | None
    properties: tuple[NotionPropertyEvidence, ...]
    relations: tuple[NotionRelationEvidence, ...]
    views: tuple[NotionViewEvidence, ...]
    limits: NotionLimitEvidence
    contract_mappings: tuple[ContractMappingCandidate, ...]
    authorization: NotionAuthorizationEvidence

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_version", _version(self.contract_version))
        object.__setattr__(self, "record_revision", _revision(self.record_revision))
        object.__setattr__(self, "evidence_id", _stable_id(self.evidence_id, "evidence_id"))
        object.__setattr__(
            self, "workspace_context_id", _stable_id(self.workspace_context_id, "workspace_context_id")
        )
        object.__setattr__(self, "notion_api_version", _text(self.notion_api_version, "notion_api_version"))
        object.__setattr__(self, "database_id", _stable_id(self.database_id, "database_id", allow_none=True))
        object.__setattr__(
            self, "data_source_id", _stable_id(self.data_source_id, "data_source_id", allow_none=True)
        )
        object.__setattr__(self, "evidence_source", _text(self.evidence_source, "evidence_source"))
        object.__setattr__(self, "verified_at", _timestamp(self.verified_at, "verified_at"))
        object.__setattr__(
            self,
            "schema_fingerprint",
            _sha256(self.schema_fingerprint, "schema_fingerprint", allow_none=True),
        )
        object.__setattr__(
            self, "view_fingerprint", _sha256(self.view_fingerprint, "view_fingerprint", allow_none=True)
        )

        properties = _exact_tuple(self.properties, "properties", MAX_PROPERTIES)
        relations = _exact_tuple(self.relations, "relations", MAX_RELATIONS)
        views = _exact_tuple(self.views, "views", MAX_VIEWS)
        mappings = _exact_tuple(self.contract_mappings, "contract_mappings", MAX_MAPPINGS)
        if any(type(item) is not NotionPropertyEvidence for item in properties):
            raise NotionCurriculumPreflightError("notion-target-unverified", "properties contain invalid records")
        if any(type(item) is not NotionRelationEvidence for item in relations):
            raise NotionCurriculumPreflightError("notion-target-unverified", "relations contain invalid records")
        if any(type(item) is not NotionViewEvidence for item in views):
            raise NotionCurriculumPreflightError("notion-target-unverified", "views contain invalid records")
        if any(type(item) is not ContractMappingCandidate for item in mappings):
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", "contract_mappings contain invalid records"
            )
        if type(self.limits) is not NotionLimitEvidence:
            raise NotionCurriculumPreflightError("notion-target-unverified", "limits must be NotionLimitEvidence")
        if type(self.authorization) is not NotionAuthorizationEvidence:
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", "authorization must be NotionAuthorizationEvidence"
            )

        object.__setattr__(self, "properties", tuple(sorted(properties, key=lambda item: (item.property_id or "", item.display_name))))
        object.__setattr__(
            self,
            "relations",
            tuple(
                sorted(
                    relations,
                    key=lambda item: (
                        item.property_id,
                        item.source_data_source_id,
                        item.target_data_source_id,
                    ),
                )
            ),
        )
        object.__setattr__(self, "views", tuple(sorted(views, key=lambda item: (item.view_id or "", item.view_type))))
        object.__setattr__(
            self,
            "contract_mappings",
            tuple(sorted(mappings, key=lambda item: item.identity)),
        )
        if _large_canonical_size(self.to_payload()) > MAX_EVIDENCE_BYTES:
            raise NotionCurriculumPreflightError(
                "notion-value-limit-exceeded", "supplied evidence exceeds the total size bound"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "record_revision": self.record_revision,
            "evidence_id": self.evidence_id,
            "workspace_context_id": self.workspace_context_id,
            "notion_api_version": self.notion_api_version,
            "database_id": self.database_id,
            "data_source_id": self.data_source_id,
            "evidence_source": self.evidence_source,
            "verified_at": self.verified_at,
            "schema_fingerprint": self.schema_fingerprint,
            "view_fingerprint": self.view_fingerprint,
            "properties": [item.to_payload() for item in self.properties],
            "relations": [item.to_payload() for item in self.relations],
            "views": [item.to_payload() for item in self.views],
            "limits": self.limits.to_payload(),
            "contract_mappings": [item.to_payload() for item in self.contract_mappings],
            "authorization": self.authorization.to_payload(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotionCurriculumPreflightReport:
    status: PreflightStatus
    evidence_id: str
    evidence_fingerprint: str
    exact_target_tuple: tuple[str, str, str]
    compatible_mappings: tuple[str, ...]
    unsupported_mappings: tuple[str, ...]
    stale_mappings: tuple[str, ...]
    missing_mappings: tuple[str, ...]
    conflicting_mappings: tuple[str, ...]
    relation_findings: tuple[str, ...]
    view_findings: tuple[str, ...]
    limit_findings: tuple[str, ...]
    authority_findings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    blockers: tuple[str, ...]
    required_manual_verifications: tuple[str, ...]
    proposed_implementation_scope: tuple[str, ...]
    evidence_expires_at: str
    rollback_note: str
    live_access_performed: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)
    write_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    publication_authorized: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.status) is not PreflightStatus:
            raise NotionCurriculumPreflightError("notion-target-unverified", "status must be PreflightStatus")
        object.__setattr__(self, "evidence_id", _stable_id(self.evidence_id, "report evidence_id"))
        object.__setattr__(
            self, "evidence_fingerprint", _sha256(self.evidence_fingerprint, "evidence_fingerprint")
        )
        targets = _exact_tuple(self.exact_target_tuple, "exact_target_tuple", 3)
        if len(targets) != 3 or any(type(item) is not str for item in targets):
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", "exact_target_tuple must contain three strings"
            )
        object.__setattr__(self, "exact_target_tuple", tuple(targets))

        for name in (
            "compatible_mappings",
            "unsupported_mappings",
            "stale_mappings",
            "missing_mappings",
            "conflicting_mappings",
        ):
            values = _exact_tuple(getattr(self, name), name, MAX_MAPPINGS)
            checked = tuple(sorted({_text(item, name) for item in values}))
            object.__setattr__(self, name, checked)

        object.__setattr__(self, "relation_findings", _codes(self.relation_findings, "relation_findings", MAX_FINDINGS))
        object.__setattr__(self, "view_findings", _codes(self.view_findings, "view_findings", MAX_FINDINGS))
        object.__setattr__(self, "limit_findings", _codes(self.limit_findings, "limit_findings", MAX_FINDINGS))
        object.__setattr__(self, "authority_findings", _codes(self.authority_findings, "authority_findings", MAX_FINDINGS))
        object.__setattr__(self, "reason_codes", _codes(self.reason_codes, "reason_codes", MAX_FINDINGS))
        object.__setattr__(self, "blockers", _codes(self.blockers, "blockers", MAX_BLOCKERS))

        manual = _exact_tuple(
            self.required_manual_verifications,
            "required_manual_verifications",
            MAX_MANUAL_VERIFICATIONS,
        )
        object.__setattr__(
            self,
            "required_manual_verifications",
            tuple(sorted({_text(item, "manual verification") for item in manual})),
        )
        scope = _exact_tuple(self.proposed_implementation_scope, "proposed_implementation_scope", 16)
        object.__setattr__(
            self,
            "proposed_implementation_scope",
            tuple(_text(item, "implementation scope") for item in scope),
        )
        object.__setattr__(self, "evidence_expires_at", _timestamp(self.evidence_expires_at, "evidence_expires_at"))
        object.__setattr__(self, "rollback_note", _text(self.rollback_note, "rollback_note"))

        if self.status is PreflightStatus.READY_FOR_LOCAL_DRAFT_IMPLEMENTATION and (
            self.reason_codes or self.blockers
        ):
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", "ready reports cannot contain findings or blockers"
            )
        if self.status is PreflightStatus.BLOCKED and not self.blockers:
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", "blocked reports require blockers"
            )
        if self.status is PreflightStatus.INVALID and not self.reason_codes:
            raise NotionCurriculumPreflightError(
                "notion-target-unverified", "invalid reports require a finding"
            )
        if canonical_size(self.to_payload()) > MAX_REPORT_BYTES:
            raise NotionCurriculumPreflightError(
                "notion-value-limit-exceeded", "preflight report exceeds the result-size bound"
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "evidence_id": self.evidence_id,
            "evidence_fingerprint": self.evidence_fingerprint,
            "exact_target_tuple": list(self.exact_target_tuple),
            "compatible_mappings": list(self.compatible_mappings),
            "unsupported_mappings": list(self.unsupported_mappings),
            "stale_mappings": list(self.stale_mappings),
            "missing_mappings": list(self.missing_mappings),
            "conflicting_mappings": list(self.conflicting_mappings),
            "relation_findings": list(self.relation_findings),
            "view_findings": list(self.view_findings),
            "limit_findings": list(self.limit_findings),
            "authority_findings": list(self.authority_findings),
            "reason_codes": list(self.reason_codes),
            "blockers": list(self.blockers),
            "required_manual_verifications": list(self.required_manual_verifications),
            "proposed_implementation_scope": list(self.proposed_implementation_scope),
            "evidence_expires_at": self.evidence_expires_at,
            "rollback_note": self.rollback_note,
            "live_access_performed": False,
            "side_effects_performed": False,
            "write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
        }
