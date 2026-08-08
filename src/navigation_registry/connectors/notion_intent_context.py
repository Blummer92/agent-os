"""Pure bounded projection from normalized Notion evidence into intent context.

The projection consumes provider-neutral Navigation Registry evidence plus
explicit semantic fields already resolved by the caller. It performs no Notion
reads, search, credentials, persistence, or writes and grants no authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Mapping, Sequence

from .base import RegistryResource

SCHEMA_VERSION = "1.0"
MAX_TEXT = 2000
MAX_REFS = 25
MAX_RELATION_DEPTH = 1
SUPPORTED_LOGICAL_SOURCES = frozenset(
    {"tasks_issues", "decision_log", "lessons_learned", "reusable_patterns"}
)


class NotionIntentContextError(ValueError):
    """Fail-closed projection error for invalid or unsafe normalized evidence."""


@dataclass(frozen=True)
class NotionIntentEvidence:
    """Provider-neutral semantic evidence supplied after registry normalization."""

    resource: RegistryResource
    logical_source: str
    objective: str
    owner: str
    owner_dashboard: str | None = None
    status: str | None = None
    governance_gate: str | None = None
    blocker: str | None = None
    next_action: str | None = None
    decision_refs: tuple[str, ...] = ()
    lesson_refs: tuple[str, ...] = ()
    pattern_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    approval_required: bool = False
    scope_change: bool = False
    relation_complete: bool = True
    relation_depth: int = 0
    source_revision: str | None = None


@dataclass(frozen=True)
class NotionIntentContext:
    """Immutable bounded Agent OS context evidence; never authorization."""

    schema_version: str
    record_id: str
    source_revision: str
    logical_source: str
    data_source_id: str
    database_id: str | None
    objective: str
    owner: str
    owner_dashboard: str | None
    status: str | None
    governance_gate: str | None
    blocker: str | None
    next_action: str | None
    decision_refs: tuple[str, ...]
    lesson_refs: tuple[str, ...]
    pattern_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    approval_required: bool
    scope_change: bool
    relation_complete: bool
    relation_depth: int
    authority: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-compatible evidence."""
        return asdict(self)

    def serialize(self) -> str:
        """Return canonical deterministic serialization."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        """Return a deterministic equality fingerprint, not a signature."""
        return hashlib.sha256(self.serialize().encode("utf-8")).hexdigest()

    def to_memory_handoff_fields(self) -> dict[str, object]:
        """Project into the existing Memory Manager handoff concepts only."""
        facts = [
            f"logical_source={self.logical_source}",
            f"record_id={self.record_id}",
            f"data_source_id={self.data_source_id}",
            f"source_revision={self.source_revision}",
            f"owner={self.owner}",
        ]
        for label, value in (
            ("status", self.status),
            ("governance_gate", self.governance_gate),
            ("blocker", self.blocker),
            ("next_action", self.next_action),
        ):
            if value:
                facts.append(f"{label}={value}")
        facts.extend(f"source_ref={ref}" for ref in self.source_refs)
        decisions = [f"decision_ref={ref}" for ref in self.decision_refs]
        stops = []
        if self.approval_required:
            stops.append("approval_required")
        if self.scope_change:
            stops.append("scope_change")
        if not self.relation_complete:
            stops.append("relation_continuation_required")
        return {
            "objective": self.objective,
            "known_facts": facts,
            "prior_decisions": decisions,
            "stop_conditions": stops,
        }


def project_notion_intent_context(evidence: NotionIntentEvidence) -> NotionIntentContext:
    """Validate and project normalized evidence into bounded intent context."""
    resource = evidence.resource
    _validate_resource(resource)
    logical_source = _required_text(evidence.logical_source, "logical_source")
    if logical_source not in SUPPORTED_LOGICAL_SOURCES:
        raise NotionIntentContextError("unsupported logical_source")

    data_source_id = _required_text(resource.parent, "data_source_id")
    database_id = _optional_text(resource.metadata.get("database_id"), "database_id")
    metadata_data_source_id = resource.metadata.get("data_source_id")
    if metadata_data_source_id is not None and str(metadata_data_source_id) != data_source_id:
        raise NotionIntentContextError("conflicting data_source identity")
    if database_id and database_id == data_source_id:
        raise NotionIntentContextError("database and data_source identities conflict")

    source_revision = evidence.source_revision or resource.metadata.get("last_edited_time")
    source_revision = _required_text(source_revision, "source_revision")
    relation_depth = evidence.relation_depth
    if type(relation_depth) is not int or relation_depth < 0 or relation_depth > MAX_RELATION_DEPTH:
        raise NotionIntentContextError("relation depth exceeds bound")

    return NotionIntentContext(
        schema_version=SCHEMA_VERSION,
        record_id=_required_text(resource.canonical_id, "record_id"),
        source_revision=source_revision,
        logical_source=logical_source,
        data_source_id=data_source_id,
        database_id=database_id,
        objective=_required_text(evidence.objective, "objective"),
        owner=_required_text(evidence.owner, "owner"),
        owner_dashboard=_optional_text(evidence.owner_dashboard, "owner_dashboard"),
        status=_optional_text(evidence.status, "status"),
        governance_gate=_optional_text(evidence.governance_gate, "governance_gate"),
        blocker=_optional_text(evidence.blocker, "blocker"),
        next_action=_optional_text(evidence.next_action, "next_action"),
        decision_refs=_bounded_refs(evidence.decision_refs, "decision_refs"),
        lesson_refs=_bounded_refs(evidence.lesson_refs, "lesson_refs"),
        pattern_refs=_bounded_refs(evidence.pattern_refs, "pattern_refs"),
        source_refs=_bounded_refs(evidence.source_refs, "source_refs"),
        approval_required=_strict_bool(evidence.approval_required, "approval_required"),
        scope_change=_strict_bool(evidence.scope_change, "scope_change"),
        relation_complete=_strict_bool(evidence.relation_complete, "relation_complete"),
        relation_depth=relation_depth,
    )


def _validate_resource(resource: RegistryResource) -> None:
    if not isinstance(resource, RegistryResource):
        raise NotionIntentContextError("resource must be RegistryResource")
    if resource.system != "notion" or resource.entity_type != "Page":
        raise NotionIntentContextError("resource must be normalized Notion Page evidence")
    if resource.source_of_truth != "notion-live" or resource.verification_state != "VerifiedReadOnly":
        raise NotionIntentContextError("live verified Notion evidence required")
    if resource.cache_status != "LiveRead" or resource.write_allowed:
        raise NotionIntentContextError("read-only live evidence required")
    if resource.metadata.get("archived") or resource.metadata.get("in_trash"):
        raise NotionIntentContextError("archived or trashed evidence is not current")


def _required_text(value: object, field: str) -> str:
    text = _optional_text(value, field)
    if not text:
        raise NotionIntentContextError(f"missing required {field}")
    return text


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NotionIntentContextError(f"wrong type for {field}")
    text = value.strip()
    if len(text) > MAX_TEXT:
        raise NotionIntentContextError(f"{field} exceeds text bound")
    return text or None


def _bounded_refs(values: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise NotionIntentContextError(f"wrong type for {field}")
    if len(values) > MAX_REFS:
        raise NotionIntentContextError(f"{field} exceeds list bound")
    normalized: list[str] = []
    for value in values:
        normalized.append(_required_text(value, field))
    return tuple(sorted(set(normalized)))


def _strict_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise NotionIntentContextError(f"wrong type for {field}")
    return value
