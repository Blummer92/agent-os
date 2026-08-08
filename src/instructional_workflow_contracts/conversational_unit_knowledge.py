"""Pure conversational unit-knowledge decision contract for Issue #963 Phase 1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    MAX_RESULT_BYTES,
    AuthorityEvidence,
    ContractReference,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_size,
    freeze_json,
    sha256_hex,
    validate_and_normalize_json,
    validate_stable_id,
    validate_text,
)

CONTRACT_ID = "conversational-unit-knowledge-v1"
MAX_CANDIDATES = 32
MAX_EXISTING = 64
MAX_TARGETS = 8
MAX_ROUTES = 8


class KnowledgeClass(str, Enum):
    TRANSIENT = "transient"
    WORKING = "working"
    DURABLE = "durable"
    OBSERVATION = "observation"
    REQUIREMENT = "requirement"
    UNRESOLVED = "unresolved"


class PersistenceIntent(str, Enum):
    NONE = "none"
    SUGGEST = "suggest"
    EXPLICIT = "explicit"
    CANCEL = "cancel"


class KnowledgeDisposition(str, Enum):
    DO_NOT_PERSIST = "do-not-persist"
    PROPOSE_PERSISTENCE = "propose-persistence"
    EXPLICIT_PERSISTENCE = "explicit-persistence"
    NEEDS_CLARIFICATION = "needs-clarification"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"
    CORRECTION = "correction"
    TEMPORAL_UPDATE = "temporal-update"
    RECONFIRM = "reconfirm"


class ExistingRelation(str, Enum):
    NONE = "none"
    IDENTICAL = "identical"
    CONFLICTING = "conflicting"
    SUPERSEDES = "supersedes"


class FreshnessState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProposedKnowledgeMutation:
    target_entity_ref: str
    operation: str
    knowledge_class: str
    subtype: str | None
    value: Any
    source_reference: ContractReference
    temporal_scope: str | None
    explicit_persistence: bool
    supersedes_ref: str | None
    fingerprint: str
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: str
    disposition: KnowledgeDisposition
    target_entity_ref: str | None
    subtype: str | None
    mutation: ProposedKnowledgeMutation | None
    outbound_routes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConversationKnowledgeDecision:
    decisions: tuple[CandidateDecision, ...]
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)


TOP_LEVEL_FIELDS = frozenset({"context", "candidates", "existing_knowledge", "authority"})
CONTEXT_FIELDS = frozenset({"current_entity_ref", "plausible_entity_refs"})
CANDIDATE_FIELDS = frozenset(
    {
        "candidate_id",
        "knowledge_class",
        "subtype",
        "value",
        "persistence_intent",
        "target_entity_ref",
        "source_reference",
        "temporal_scope",
        "existing_relation",
        "existing_ref",
        "freshness",
        "outbound_routes",
    }
)
AUTHORITY_FIELDS = frozenset(
    {
        "execution_authorized",
        "external_write_authorized",
        "production_authorized",
        "publication_authorized",
    }
)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in mapping")
    return value


def _list(value: Any, name: str, maximum: int) -> list[Any]:
    if type(value) is not list:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in list")
    if len(value) > maximum:
        raise ContractValidationError("handoff-oversized", f"{name} exceeds its collection bound")
    return value


def _exact_fields(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        if set(value) - expected:
            raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")
        raise ContractValidationError("handoff-invalid", f"{name} is missing required fields")


def _choice(value: Any, enum_type: type[Enum], name: str) -> Any:
    if type(value) is not str:
        raise ContractValidationError("handoff-wrong-type", f"{name} must be a built-in string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ContractValidationError("handoff-invalid", f"{name} is unsupported") from exc


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return validate_text(value, name)


def _reference(value: Any) -> ContractReference:
    ref = _mapping(value, "source_reference")
    expected = frozenset({"system", "stable_id", "exact_location", "verification_evidence"})
    _exact_fields(ref, expected, "source_reference")
    return ContractReference(
        system=ref["system"],
        stable_id=ref["stable_id"],
        exact_location=ref["exact_location"],
        verification_evidence=ref["verification_evidence"],
    )


def _validate_authority(value: Any) -> None:
    authority = _mapping(value, "authority")
    _exact_fields(authority, AUTHORITY_FIELDS, "authority")
    for name, flag in authority.items():
        if type(flag) is not bool or flag is not False:
            raise ContractValidationError("authority-invalid", f"authority.{name} must be built-in false")


def _resolved_target(context: dict[str, Any], candidate_target: str | None) -> str | None:
    if candidate_target is not None:
        return validate_stable_id(candidate_target, "target_entity_ref")
    current = context["current_entity_ref"]
    plausible = context["plausible_entity_refs"]
    if current is not None:
        return validate_stable_id(current, "current_entity_ref")
    if len(plausible) == 1:
        return plausible[0]
    return None


def _disposition(
    knowledge_class: KnowledgeClass,
    persistence: PersistenceIntent,
    relation: ExistingRelation,
    freshness: FreshnessState,
    temporal_scope: str | None,
    target: str | None,
) -> KnowledgeDisposition:
    if persistence is PersistenceIntent.CANCEL or knowledge_class is KnowledgeClass.TRANSIENT:
        return KnowledgeDisposition.DO_NOT_PERSIST
    if target is None or knowledge_class is KnowledgeClass.UNRESOLVED:
        return KnowledgeDisposition.NEEDS_CLARIFICATION
    if relation is ExistingRelation.IDENTICAL:
        return KnowledgeDisposition.UNCHANGED
    if freshness is FreshnessState.STALE and relation is not ExistingRelation.NONE:
        return KnowledgeDisposition.RECONFIRM
    if relation is ExistingRelation.SUPERSEDES:
        return KnowledgeDisposition.CORRECTION
    if relation is ExistingRelation.CONFLICTING:
        return KnowledgeDisposition.CONFLICT
    if temporal_scope is not None:
        return KnowledgeDisposition.TEMPORAL_UPDATE
    if persistence is PersistenceIntent.EXPLICIT:
        return KnowledgeDisposition.EXPLICIT_PERSISTENCE
    return KnowledgeDisposition.PROPOSE_PERSISTENCE


def _operation(disposition: KnowledgeDisposition) -> str:
    if disposition is KnowledgeDisposition.CORRECTION:
        return "supersede"
    if disposition is KnowledgeDisposition.TEMPORAL_UPDATE:
        return "add-temporal"
    return "add"


def decide_conversational_unit_knowledge(value: object) -> ValidationResult:
    """Project supplied resolved meaning into deterministic authority-false decisions."""
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = _mapping(normalized, "conversation knowledge input")
        _exact_fields(payload, TOP_LEVEL_FIELDS, "conversation knowledge input")
        _validate_authority(payload["authority"])

        context = _mapping(payload["context"], "context")
        _exact_fields(context, CONTEXT_FIELDS, "context")
        current = context["current_entity_ref"]
        if current is not None:
            context["current_entity_ref"] = validate_stable_id(current, "current_entity_ref")
        plausible = _list(context["plausible_entity_refs"], "plausible_entity_refs", MAX_TARGETS)
        context["plausible_entity_refs"] = sorted(
            {validate_stable_id(item, "plausible_entity_ref") for item in plausible}
        )

        _list(payload["existing_knowledge"], "existing_knowledge", MAX_EXISTING)
        candidates = _list(payload["candidates"], "candidates", MAX_CANDIDATES)
        decisions: list[CandidateDecision] = []

        for raw_candidate in candidates:
            candidate = _mapping(raw_candidate, "candidate")
            _exact_fields(candidate, CANDIDATE_FIELDS, "candidate")
            candidate_id = validate_stable_id(candidate["candidate_id"], "candidate_id")
            knowledge_class = _choice(candidate["knowledge_class"], KnowledgeClass, "knowledge_class")
            persistence = _choice(candidate["persistence_intent"], PersistenceIntent, "persistence_intent")
            relation = _choice(candidate["existing_relation"], ExistingRelation, "existing_relation")
            freshness = _choice(candidate["freshness"], FreshnessState, "freshness")
            subtype = _optional_text(candidate["subtype"], "subtype")
            temporal_scope = _optional_text(candidate["temporal_scope"], "temporal_scope")
            existing_ref = _optional_text(candidate["existing_ref"], "existing_ref")
            if existing_ref is not None:
                existing_ref = validate_stable_id(existing_ref, "existing_ref")
            source_reference = _reference(candidate["source_reference"])
            outbound_routes = tuple(
                sorted(
                    {
                        validate_stable_id(item, "outbound_route")
                        for item in _list(candidate["outbound_routes"], "outbound_routes", MAX_ROUTES)
                    }
                )
            )
            target = _resolved_target(context, candidate["target_entity_ref"])
            disposition = _disposition(
                knowledge_class,
                persistence,
                relation,
                freshness,
                temporal_scope,
                target,
            )

            mutation = None
            if disposition in {
                KnowledgeDisposition.PROPOSE_PERSISTENCE,
                KnowledgeDisposition.EXPLICIT_PERSISTENCE,
                KnowledgeDisposition.CORRECTION,
                KnowledgeDisposition.TEMPORAL_UPDATE,
            }:
                mutation_payload = {
                    "candidate_id": candidate_id,
                    "target_entity_ref": target,
                    "operation": _operation(disposition),
                    "knowledge_class": knowledge_class.value,
                    "subtype": subtype,
                    "value": candidate["value"],
                    "source_reference": {
                        "system": source_reference.system,
                        "stable_id": source_reference.stable_id,
                        "exact_location": source_reference.exact_location,
                        "verification_evidence": source_reference.verification_evidence,
                    },
                    "temporal_scope": temporal_scope,
                    "explicit_persistence": persistence is PersistenceIntent.EXPLICIT,
                    "supersedes_ref": existing_ref if disposition is KnowledgeDisposition.CORRECTION else None,
                }
                mutation = ProposedKnowledgeMutation(
                    target_entity_ref=target or "unresolved",
                    operation=mutation_payload["operation"],
                    knowledge_class=knowledge_class.value,
                    subtype=subtype,
                    value=candidate["value"],
                    source_reference=source_reference,
                    temporal_scope=temporal_scope,
                    explicit_persistence=mutation_payload["explicit_persistence"],
                    supersedes_ref=mutation_payload["supersedes_ref"],
                    fingerprint=sha256_hex(mutation_payload),
                )

            decisions.append(
                CandidateDecision(
                    candidate_id=candidate_id,
                    disposition=disposition,
                    target_entity_ref=target,
                    subtype=subtype,
                    mutation=mutation,
                    outbound_routes=outbound_routes,
                )
            )

        result_payload = {
            "contract_version": CONTRACT_ID,
            "decisions": [
                {
                    "candidate_id": item.candidate_id,
                    "disposition": item.disposition.value,
                    "target_entity_ref": item.target_entity_ref,
                    "subtype": item.subtype,
                    "mutation": None
                    if item.mutation is None
                    else {
                        "target_entity_ref": item.mutation.target_entity_ref,
                        "operation": item.mutation.operation,
                        "knowledge_class": item.mutation.knowledge_class,
                        "subtype": item.mutation.subtype,
                        "value": item.mutation.value,
                        "source_reference": {
                            "system": item.mutation.source_reference.system,
                            "stable_id": item.mutation.source_reference.stable_id,
                            "exact_location": item.mutation.source_reference.exact_location,
                            "verification_evidence": item.mutation.source_reference.verification_evidence,
                        },
                        "temporal_scope": item.mutation.temporal_scope,
                        "explicit_persistence": item.mutation.explicit_persistence,
                        "supersedes_ref": item.mutation.supersedes_ref,
                        "fingerprint": item.mutation.fingerprint,
                        "execution_authorized": False,
                        "external_write_authorized": False,
                        "production_authorized": False,
                        "publication_authorized": False,
                    },
                    "outbound_routes": list(item.outbound_routes),
                }
                for item in decisions
            ],
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
            },
        }
        if canonical_size(result_payload) > MAX_RESULT_BYTES:
            raise ContractValidationError("handoff-oversized", "knowledge decision exceeds result-size bound")

        record = ValidatedRecord(
            contract_version=CONTRACT_ID,
            record_id="conversation-knowledge-decision",
            record_revision=1,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=sha256_hex(result_payload),
            payload=freeze_json(result_payload),
        )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=(exc.reason_code,),
            details=(exc.detail,),
        )
    except (TypeError, ValueError):
        return ValidationResult(
            status=ValidationStatus.INVALID,
            record=None,
            reason_codes=("handoff-invalid",),
            details=("conversation knowledge validation failed",),
        )
