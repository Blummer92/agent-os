"""Pure bounded contextual-teacher-action contract for Issue #1892 (CTA1).

Implements the cta-v0.1.0-draft spec as cta-v1.0.0: a frozen, side-effect-free
record for a teacher's invocation of an Agent OS capability from bounded
instructional context, plus the governed action-to-capability routing matrix.

The envelope extends the #924 request-interpretation shape with two
teacher-specific additions: the closed 9-action teacher vocabulary and a
first-class ``selection`` block (page/slide/range/cell-range binding).
Like #924, producing a record authorizes nothing: ``side_effects_performed``
and ``authorization_created`` are fixed ``False``, and any ``mutate`` effect
must independently pass the Teacher-Directed Revision Lane (#1013) or the
relevant production gates before any edit occurs.

No new agent per action, no second orchestration framework, no UI adapter,
no browser/extension deployment, and no external writes are authorized by
this contract. It is validation-only: pure, read-only, deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .common import (
    FINGERPRINT_ALGORITHM,
    MAX_INPUT_BYTES,
    AuthorityEvidence,
    ContractReference,
    ContractValidationError,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    freeze_json,
    is_secret_like_key,
    sha256_hex,
    validate_and_normalize_json,
    validate_bounded_list,
    validate_exact_fields,
    validate_mapping,
    validate_revision,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)
from .material_requirement import (
    CANONICAL_OWNERS,
    DESTINATION_CLASSES,
    SUPPORTED_ARTIFACT_TYPES,
)
from .request_interpretation import (
    CONTINUATIONS as REQUEST_CONTINUATIONS,
    EFFECTS as REQUEST_EFFECTS,
    ORIGINS as REQUEST_ORIGINS,
    REASON_CODES as REQUEST_REASON_CODES,
)

SCHEMA_NAME = "contextual-teacher-action"
CONTRACT_VERSION = "cta-v1.0.0"
MAX_CONSTRAINTS = 16
MAX_REFERENCES = 16

# Reused #924 governed vocabularies: the CTA envelope speaks the same
# intent/effect/origin language as the request-interpretation contract.
EFFECTS = REQUEST_EFFECTS
CONTINUATIONS = REQUEST_CONTINUATIONS
ORIGINS = REQUEST_ORIGINS

# Closed 9-action teacher vocabulary (spec section 5). Extensions require a
# versioned contract change.
CTA_ACTIONS = frozenset({
    "improve",
    "differentiate",
    "clarify",
    "check-alignment",
    "generate-modeling",
    "generate-guided-practice",
    "generate-assessment",
    "generate-lesson-bundle",
    "analyze-response-evidence",
})

# Gap resolution (a): SUPPORTED_ARTIFACT_TYPES has no "guided-practice"; the
# nearest canonical type is "guided-notes". The mapping is recorded as an
# explicit constraint on generate-guided-practice records — never aliased
# silently. Gap resolution (c): the assessment-next-instruction lineage is
# not referenced anywhere in this module (unverifiable in-repo).
GUIDED_PRACTICE_ACTION = "generate-guided-practice"
GUIDED_PRACTICE_ARTIFACT_TYPE = "guided-notes"
GUIDED_PRACTICE_MAPPING_CONSTRAINT = "guided-practice-artifact-mapping"

ANALYZE_RESPONSE_EVIDENCE_ACTION = "analyze-response-evidence"

SELECTION_KINDS = frozenset({"none", "page", "slide", "range", "cell-range"})
SELECTION_FIELDS = frozenset({"selection_kind", "selector", "verified"})

# Artifact systems a consumer can identify a source in (spec section 6).
ARTIFACT_SYSTEMS = frozenset({"google-docs", "google-slides", "chatgpt", "local-reference", "unknown"})
ARTIFACT_FIELDS = frozenset({
    "stable_id", "record_revision", "source_fingerprint", "course_ref",
    "unit_ref", "lesson_ref", "source_system", "artifact_type",
})

# CTA reason-code additions (spec section 9) on top of the full #924 catalog.
CTA_REASON_CODE_ADDITIONS = frozenset({
    "handoff-selection-ambiguous",
    "handoff-selection-out-of-artifact",
    "target.selection-unverified",
    "identity-artifact-unidentified",
    "handoff-destination-required",
    "request.lineage-unverified",
})
CTA_REASON_CODES = REQUEST_REASON_CODES | CTA_REASON_CODE_ADDITIONS

TOP_LEVEL_FIELDS = frozenset({
    "schema_name", "contract_version", "record_revision", "observed_at", "producer_id",
    "raw_input_digest", "instruction_origin", "action", "requested_effect", "continuation_mode",
    "artifact", "selection", "requested_output", "destination",
    "constraints", "reason_codes", "evidence_references",
})
REFERENCE_FIELDS = frozenset({"system", "stable_id", "exact_location", "verification_evidence"})
CONSTRAINT_FIELDS = frozenset({"name", "value"})


@dataclass(frozen=True, slots=True)
class ActionRoute:
    """One governed row of the CTA routing matrix (spec section 8).

    The matrix is discovery + routing evidence only: every anchor is "prose"
    today because all 17 reusable-capabilities.yml records are dev/CI-facing
    and carry no teacher-action targets. Adding CTA-specific capability_id
    records is a named successor task, not part of this contract.
    """

    action: str
    owners: tuple[str, ...]
    capability_reference: str
    anchor: Literal["prose"]
    terminal: Literal["route", "unsupported"]
    notes: str


ROUTING_MATRIX: tuple[ActionRoute, ...] = (
    ActionRoute(
        action="improve",
        owners=("teacher-modeling-coach", "instructional-materials-coach"),
        capability_reference="Teacher-Directed Revision Lane (#1013)",
        anchor="prose",
        terminal="route",
        notes="Artifact-edit authority only; bounded and reversible edits required.",
    ),
    ActionRoute(
        action="differentiate",
        owners=("instructional-materials-coach",),
        capability_reference="Teacher-Directed Revision Lane (#1013)",
        anchor="prose",
        terminal="route",
        notes="Artifact-edit authority only; audience constraint required.",
    ),
    ActionRoute(
        action="clarify",
        owners=("teacher-modeling-coach", "instructional-materials-coach"),
        capability_reference="Teacher-Directed Revision Lane (#1013)",
        anchor="prose",
        terminal="route",
        notes="Artifact-edit authority only; bounded and reversible edits required.",
    ),
    ActionRoute(
        action="check-alignment",
        owners=("unit-alignment-agent", "qa-test-agent"),
        capability_reference="Assessment QA evidence standards (alignment category)",
        anchor="prose",
        terminal="route",
        notes="Read-only; no grading, no production use.",
    ),
    ActionRoute(
        action="generate-modeling",
        owners=("teacher-modeling-coach",),
        capability_reference="Teacher Modeling Coach (teacher-modeling-package)",
        anchor="prose",
        terminal="route",
        notes="Proposal only; no production activation.",
    ),
    ActionRoute(
        action="generate-guided-practice",
        owners=("instructional-materials-coach",),
        capability_reference="Instructional Materials Coach (guided-notes)",
        anchor="prose",
        terminal="route",
        notes=(
            "Gap resolution (a): guided-practice maps to the guided-notes artifact "
            "type; the mapping is recorded as an explicit constraint "
            "(guided-practice-artifact-mapping), never aliased silently."
        ),
    ),
    ActionRoute(
        action="generate-assessment",
        owners=("instructional-materials-coach",),
        capability_reference="Material requirement (assessment artifact type)",
        anchor="prose",
        terminal="route",
        notes="Planning only; no grading or classroom use.",
    ),
    ActionRoute(
        action="generate-lesson-bundle",
        owners=("instructional-materials-coach",),
        capability_reference="plan_lesson_bundle (instructional-materials-coach tooling: max 12 members, frozen plan, fail-closed)",
        anchor="prose",
        terminal="route",
        notes="Plan only; no execution against Drive.",
    ),
    ActionRoute(
        action=ANALYZE_RESPONSE_EVIDENCE_ACTION,
        owners=(),
        capability_reference="none — no response-evidence analysis capability exists",
        anchor="prose",
        terminal="unsupported",
        notes="Explicit unsupported; the consumer must present the manual-review path.",
    ),
)

# Owner identities resolve through the canonical material-requirement owners.
for _route in ROUTING_MATRIX:
    for _owner in _route.owners:
        assert _owner in CANONICAL_OWNERS, f"routing matrix owner is not canonical: {_owner}"
del _route, _owner

ROUTES: dict[str, ActionRoute] = {route.action: route for route in ROUTING_MATRIX}


def route_action(action: str) -> ActionRoute:
    """Return the governed routing-matrix row for a CTA action."""
    try:
        return ROUTES[action]
    except KeyError:
        raise ContractValidationError("handoff-invalid", "action is outside the CTA vocabulary") from None


@dataclass(frozen=True, slots=True)
class ContextualTeacherAction:
    record: ValidatedRecord
    side_effects_performed: Literal[False] = field(default=False, init=False)
    authorization_created: Literal[False] = field(default=False, init=False)
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)


def _choice(value: Any, allowed: frozenset[str], name: str, reason_code: str) -> str:
    text = validate_text(value, name, max_length=64)
    if text not in allowed:
        raise ContractValidationError(reason_code, f"{name} is unsupported")
    return text


def _reference(value: Any) -> ContractReference:
    ref = validate_mapping(value, "evidence reference")
    validate_exact_fields(ref, REFERENCE_FIELDS, "evidence reference")
    return ContractReference(
        system=ref["system"], stable_id=ref["stable_id"], exact_location=ref["exact_location"],
        verification_evidence=ref["verification_evidence"],
    )


def _artifact(value: Any) -> dict[str, Any]:
    artifact = validate_mapping(value, "artifact")
    validate_exact_fields(artifact, ARTIFACT_FIELDS, "artifact")
    raw_stable_id = artifact["stable_id"]
    if raw_stable_id is None:
        # Spec section 6: an action over an artifact with no identifiable
        # stable id fails closed.
        raise ContractValidationError("identity-artifact-unidentified", "artifact has no stable identity")
    stable_id = validate_stable_id(raw_stable_id, "artifact.stable_id")
    revision = validate_revision(artifact["record_revision"])
    fingerprint = validate_text(artifact["source_fingerprint"], "artifact.source_fingerprint", max_length=128)
    course_ref = validate_text(artifact["course_ref"], "artifact.course_ref", max_length=128)
    unit_ref = validate_text(artifact["unit_ref"], "artifact.unit_ref", max_length=128)
    lesson_ref = validate_text(artifact["lesson_ref"], "artifact.lesson_ref", max_length=128)
    source_system = _choice(artifact["source_system"], ARTIFACT_SYSTEMS, "artifact.source_system", "handoff-invalid")
    artifact_type = _choice(
        artifact["artifact_type"], SUPPORTED_ARTIFACT_TYPES, "artifact.artifact_type", "material-unsupported-artifact-type"
    )
    return {
        "stable_id": stable_id, "record_revision": revision, "source_fingerprint": fingerprint,
        "course_ref": course_ref, "unit_ref": unit_ref, "lesson_ref": lesson_ref,
        "source_system": source_system, "artifact_type": artifact_type,
    }


def _selection(value: Any, artifact_stable_id: str) -> tuple[dict[str, Any], set[str]]:
    """Validate the first-class selection block (spec section 7).

    Gap resolution (b): the selection binding is a required first-class field,
    not a constraint, so consumers cannot drop it. The selector is checked
    syntactically: it must carry the artifact's stable id as a path segment,
    e.g. "slides:deck-id:slide-4". A selector that cannot resolve inside the
    identified artifact fails closed with target.selection-out-of-artifact.
    """
    selection = validate_mapping(value, "selection")
    validate_exact_fields(selection, SELECTION_FIELDS, "selection")
    reasons: set[str] = set()
    kind = _choice(selection["selection_kind"], SELECTION_KINDS, "selection.selection_kind", "handoff-invalid")
    raw_selector = selection["selector"]
    if kind == "none":
        # Whole-artifact scope: the selector is null. Nulls pass input
        # normalization; empty strings do not (family-wide invariant).
        if raw_selector is not None:
            raise ContractValidationError(
                "handoff-selection-ambiguous", "selection_kind none must not carry a selector"
            )
        return {"selection_kind": "none", "selector": None, "verified": True}, reasons
    if type(raw_selector) is not str:
        raise ContractValidationError("handoff-wrong-type", "selection.selector must be a built-in string")
    selector = validate_text(raw_selector, "selection.selector", max_length=256)
    verified = selection["verified"]
    if type(verified) is not bool:
        raise ContractValidationError("handoff-wrong-type", "selection.verified must be a built-in boolean")

    if artifact_stable_id not in selector.split(":"):
        raise ContractValidationError(
            "handoff-selection-out-of-artifact", "selector does not resolve inside the identified artifact"
        )
    if not verified:
        # Degrade to whole-artifact scope; the record carries the evidence.
        reasons.add("target.selection-unverified")
        return {"selection_kind": "none", "selector": None, "verified": False}, reasons
    return {"selection_kind": kind, "selector": selector, "verified": True}, reasons


def _constraints(values: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in validate_bounded_list(values, "constraints", MAX_CONSTRAINTS):
        item = validate_mapping(raw, "constraint")
        validate_exact_fields(item, CONSTRAINT_FIELDS, "constraint")
        name = validate_stable_id(item["name"], "constraint.name")
        if is_secret_like_key(name):
            raise ContractValidationError("authority-secret-field", "constraint.name is secret-like")
        if name in seen:
            raise ContractValidationError("handoff-duplicate", "constraint names must be unique")
        seen.add(name)
        value = item["value"]
        if type(value) not in (str, int, bool) and value is not None:
            raise ContractValidationError("handoff-wrong-type", "constraint.value must be scalar")
        if type(value) is str:
            value = validate_text(value, "constraint.value")
        normalized.append({"name": name, "value": value})
    return sorted(normalized, key=lambda item: item["name"])


def _require_guided_practice_mapping(action: str, constraints: list[dict[str, Any]]) -> None:
    if action != GUIDED_PRACTICE_ACTION:
        return
    mapping = next(
        (item for item in constraints if item["name"] == GUIDED_PRACTICE_MAPPING_CONSTRAINT), None
    )
    if mapping is None or mapping["value"] != GUIDED_PRACTICE_ARTIFACT_TYPE:
        raise ContractValidationError(
            "handoff-mapping-missing",
            "generate-guided-practice requires the explicit guided-practice-artifact-mapping constraint",
        )


def _semantic_reasons(origin: str, action: str, selection_reasons: set[str]) -> set[str]:
    reasons: set[str] = set(selection_reasons)
    if origin == "retrieved-content":
        reasons.add("request.untrusted-source")
    if action == ANALYZE_RESPONSE_EVIDENCE_ACTION:
        reasons.add("action.unsupported")
    return reasons


def validate_contextual_teacher_action(value: object) -> ValidationResult:
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = validate_mapping(normalized, "contextual teacher action")
        validate_exact_fields(payload, TOP_LEVEL_FIELDS, "contextual teacher action")
        if validate_text(payload["schema_name"], "schema_name", max_length=64) != SCHEMA_NAME:
            raise ContractValidationError("handoff-invalid", "schema_name is unsupported")
        if validate_version(payload["contract_version"]) != CONTRACT_VERSION:
            raise ContractValidationError("handoff-version-unsupported", "contract_version is unsupported")
        revision = validate_revision(payload["record_revision"])
        observed_at = validate_timestamp(payload["observed_at"], "observed_at")
        producer_id = validate_stable_id(payload["producer_id"], "producer_id")
        raw_input_digest = validate_text(payload["raw_input_digest"], "raw_input_digest", max_length=64)
        if len(raw_input_digest) != 64 or any(ch not in "0123456789abcdef" for ch in raw_input_digest):
            raise ContractValidationError("handoff-invalid", "raw_input_digest must be lowercase SHA-256 hex")
        origin = _choice(payload["instruction_origin"], ORIGINS, "instruction_origin", "handoff-invalid")
        action = _choice(payload["action"], CTA_ACTIONS, "action", "handoff-invalid")
        effect = _choice(payload["requested_effect"], EFFECTS, "requested_effect", "handoff-invalid")
        continuation = _choice(payload["continuation_mode"], CONTINUATIONS, "continuation_mode", "handoff-invalid")
        artifact = _artifact(payload["artifact"])
        selection, selection_reasons = _selection(payload["selection"], artifact["stable_id"])
        requested_output = validate_text(payload["requested_output"], "requested_output")
        destination = payload["destination"]
        if effect == "mutate":
            if destination is None:
                raise ContractValidationError(
                    "handoff-destination-required", "mutate requires a destination"
                )
            destination = _choice(destination, DESTINATION_CLASSES, "destination", "handoff-destination-unclear")
        elif destination is not None:
            destination = _choice(destination, DESTINATION_CLASSES, "destination", "handoff-destination-unclear")
        constraints = _constraints(payload["constraints"])
        _require_guided_practice_mapping(action, constraints)
        supplied_reasons = {
            validate_text(item, "reason_code", max_length=128)
            for item in validate_bounded_list(payload["reason_codes"], "reason_codes", len(CTA_REASON_CODES))
        }
        if not supplied_reasons <= CTA_REASON_CODES:
            raise ContractValidationError("handoff-invalid", "reason_codes contain an unknown governed code")
        references = [_reference(item) for item in validate_bounded_list(payload["evidence_references"], "evidence_references", MAX_REFERENCES)]
        reasons = tuple(sorted(supplied_reasons | _semantic_reasons(origin, action, selection_reasons)))
        record_payload = {
            "schema_name": SCHEMA_NAME, "contract_version": CONTRACT_VERSION, "record_revision": revision,
            "observed_at": observed_at, "producer_id": producer_id, "raw_input_digest": raw_input_digest,
            "instruction_origin": origin, "action": action, "requested_effect": effect,
            "continuation_mode": continuation, "artifact": artifact, "selection": selection,
            "requested_output": requested_output, "destination": destination,
            "constraints": constraints, "reason_codes": list(reasons),
            "evidence_references": [
                {"system": ref.system, "stable_id": ref.stable_id, "exact_location": ref.exact_location, "verification_evidence": ref.verification_evidence}
                for ref in references
            ],
            "side_effects_performed": False, "authorization_created": False,
        }
        fingerprint = sha256_hex(record_payload)
        record = ValidatedRecord(
            contract_version=CONTRACT_VERSION, record_id=f"cta-{fingerprint[:24]}", record_revision=revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM, fingerprint=fingerprint, payload=freeze_json(record_payload),
        )
        if reasons:
            return ValidationResult(status=ValidationStatus.MANUAL_REVIEW_REQUIRED, record=record, details=reasons)
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(status=ValidationStatus.INVALID, record=None, reason_codes=(exc.reason_code,), details=(exc.detail,))
