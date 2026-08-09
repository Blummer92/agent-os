"""Pure bounded request-interpretation contract for Issue #924."""

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
    sha256_hex,
    validate_and_normalize_json,
    validate_revision,
    validate_stable_id,
    validate_text,
    validate_timestamp,
    validate_version,
)

SCHEMA_NAME = "request-interpretation"
CONTRACT_VERSION = "request-interpretation-v1"
MAX_OUTPUTS = 8
MAX_CONSTRAINTS = 16
MAX_REFERENCES = 16

ACTIONS = frozenset({"inspect", "plan", "implement", "review", "generate", "unknown"})
EFFECTS = frozenset({"read", "propose", "mutate", "schedule"})
CONTINUATIONS = frozenset({"new", "continue"})
ORIGINS = frozenset({"direct-user", "retrieved-content", "system", "approved-handoff"})
SYSTEMS = frozenset({"github", "notion", "google-drive", "google-docs", "google-slides", "google-sheets", "unknown"})
RESOURCE_KINDS = frozenset({"repository", "issue", "pull-request", "unknown"})
REASON_CODES = frozenset({
    "action.ambiguous",
    "action.invalid",
    "action.unsupported",
    "target.missing",
    "target.multiple",
    "target.repository-missing",
    "target.issue-invalid",
    "target.pull-request-invalid",
    "context.missing",
    "context.stale",
    "context.multiple-candidates",
    "request.untrusted-source",
    "request.conflicting-constraints",
    "request.write-surface-unclear",
    "request.destination-unclear",
    "request.monitoring-surface-required",
})

TOP_LEVEL_FIELDS = frozenset({
    "schema_name", "contract_version", "record_revision", "observed_at", "interpreter_id",
    "raw_input_digest", "instruction_origin", "action", "requested_effect", "continuation_mode",
    "target", "requested_outputs", "constraints", "reason_codes", "evidence_references",
})
TARGET_FIELDS = frozenset({"system", "resource_kind", "repository", "resource_id"})
REFERENCE_FIELDS = frozenset({"system", "stable_id", "exact_location", "verification_evidence"})
CONSTRAINT_FIELDS = frozenset({"name", "value"})


@dataclass(frozen=True, slots=True)
class RequestInterpretation:
    record: ValidatedRecord
    side_effects_performed: Literal[False] = field(default=False, init=False)
    authorization_created: Literal[False] = field(default=False, init=False)
    authority: AuthorityEvidence = field(default_factory=AuthorityEvidence, init=False)


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


def _exact(value: dict[str, Any], expected: frozenset[str], name: str) -> None:
    if set(value) != expected:
        if set(value) - expected:
            raise ContractValidationError("handoff-unknown-field", f"{name} contains unknown fields")
        raise ContractValidationError("handoff-invalid", f"{name} is missing required fields")


def _choice(value: Any, allowed: frozenset[str], name: str) -> str:
    text = validate_text(value, name, max_length=64)
    if text not in allowed:
        raise ContractValidationError("handoff-invalid", f"{name} is unsupported")
    return text


def _optional_stable_id(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return validate_stable_id(value, name)


def _reference(value: Any) -> ContractReference:
    ref = _mapping(value, "evidence reference")
    _exact(ref, REFERENCE_FIELDS, "evidence reference")
    return ContractReference(
        system=ref["system"], stable_id=ref["stable_id"], exact_location=ref["exact_location"],
        verification_evidence=ref["verification_evidence"],
    )


def _target(value: Any) -> dict[str, Any]:
    target = _mapping(value, "target")
    _exact(target, TARGET_FIELDS, "target")
    system = _choice(target["system"], SYSTEMS, "target.system")
    resource_kind = _choice(target["resource_kind"], RESOURCE_KINDS, "target.resource_kind")
    repository = _optional_stable_id(target["repository"], "target.repository")
    resource_id = _optional_stable_id(target["resource_id"], "target.resource_id")
    return {"system": system, "resource_kind": resource_kind, "repository": repository, "resource_id": resource_id}


def _constraints(values: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _list(values, "constraints", MAX_CONSTRAINTS):
        item = _mapping(raw, "constraint")
        _exact(item, CONSTRAINT_FIELDS, "constraint")
        name = validate_stable_id(item["name"], "constraint.name")
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


def _semantic_reasons(origin: str, action: str, effect: str, continuation: str, target: dict[str, Any], constraints: list[dict[str, Any]]) -> set[str]:
    reasons: set[str] = set()
    if origin == "retrieved-content":
        reasons.add("request.untrusted-source")
    if action == "unknown":
        reasons.add("action.ambiguous")
    if target["system"] == "unknown":
        reasons.add("request.destination-unclear")
    if target["resource_kind"] == "unknown":
        reasons.add("target.missing")
    if target["system"] == "github" and target["repository"] is None:
        reasons.add("target.repository-missing")
    if target["resource_kind"] in {"issue", "pull-request"} and target["resource_id"] is None:
        reasons.add("target.missing")
    if continuation == "continue" and target["resource_id"] is None:
        reasons.add("context.missing")
    if effect == "mutate" and origin not in {"direct-user", "approved-handoff"}:
        reasons.add("request.write-surface-unclear")
    if effect == "schedule":
        reasons.add("request.monitoring-surface-required")
    names = [item["name"] for item in constraints]
    if len(names) != len(set(names)):
        reasons.add("request.conflicting-constraints")
    return reasons


def validate_request_interpretation(value: object) -> ValidationResult:
    try:
        normalized = validate_and_normalize_json(value, max_bytes=MAX_INPUT_BYTES)
        payload = _mapping(normalized, "request interpretation")
        _exact(payload, TOP_LEVEL_FIELDS, "request interpretation")
        if validate_text(payload["schema_name"], "schema_name", max_length=64) != SCHEMA_NAME:
            raise ContractValidationError("handoff-invalid", "schema_name is unsupported")
        if validate_version(payload["contract_version"]) != CONTRACT_VERSION:
            raise ContractValidationError("handoff-version-unsupported", "contract_version is unsupported")
        revision = validate_revision(payload["record_revision"])
        observed_at = validate_timestamp(payload["observed_at"], "observed_at")
        interpreter_id = validate_stable_id(payload["interpreter_id"], "interpreter_id")
        raw_input_digest = validate_text(payload["raw_input_digest"], "raw_input_digest", max_length=64)
        if len(raw_input_digest) != 64 or any(ch not in "0123456789abcdef" for ch in raw_input_digest):
            raise ContractValidationError("handoff-invalid", "raw_input_digest must be lowercase SHA-256 hex")
        origin = _choice(payload["instruction_origin"], ORIGINS, "instruction_origin")
        action = _choice(payload["action"], ACTIONS, "action")
        effect = _choice(payload["requested_effect"], EFFECTS, "requested_effect")
        continuation = _choice(payload["continuation_mode"], CONTINUATIONS, "continuation_mode")
        target = _target(payload["target"])
        outputs = sorted({validate_stable_id(item, "requested_output") for item in _list(payload["requested_outputs"], "requested_outputs", MAX_OUTPUTS)})
        constraints = _constraints(payload["constraints"])
        supplied_reasons = {validate_text(item, "reason_code", max_length=128) for item in _list(payload["reason_codes"], "reason_codes", len(REASON_CODES))}
        if not supplied_reasons <= REASON_CODES:
            raise ContractValidationError("handoff-invalid", "reason_codes contain an unknown governed code")
        references = [_reference(item) for item in _list(payload["evidence_references"], "evidence_references", MAX_REFERENCES)]
        computed_reasons = _semantic_reasons(origin, action, effect, continuation, target, constraints)
        reasons = tuple(sorted(supplied_reasons | computed_reasons))
        record_payload = {
            "schema_name": SCHEMA_NAME,
            "contract_version": CONTRACT_VERSION,
            "record_revision": revision,
            "observed_at": observed_at,
            "interpreter_id": interpreter_id,
            "raw_input_digest": raw_input_digest,
            "instruction_origin": origin,
            "action": action,
            "requested_effect": effect,
            "continuation_mode": continuation,
            "target": target,
            "requested_outputs": outputs,
            "constraints": constraints,
            "reason_codes": list(reasons),
            "evidence_references": [
                {"system": ref.system, "stable_id": ref.stable_id, "exact_location": ref.exact_location, "verification_evidence": ref.verification_evidence}
                for ref in references
            ],
            "side_effects_performed": False,
            "authorization_created": False,
        }
        fingerprint = sha256_hex(record_payload)
        record = ValidatedRecord(
            contract_version=CONTRACT_VERSION,
            record_id=f"request-{fingerprint[:24]}",
            record_revision=revision,
            fingerprint_algorithm=FINGERPRINT_ALGORITHM,
            fingerprint=fingerprint,
            payload=freeze_json(record_payload),
        )
        if reasons:
            return ValidationResult(
                status=ValidationStatus.MANUAL_REVIEW_REQUIRED,
                record=record,
                reason_codes=(),
                details=tuple(reasons),
            )
        return ValidationResult(status=ValidationStatus.VALID, record=record)
    except ContractValidationError as exc:
        return ValidationResult(status=ValidationStatus.INVALID, record=None, reason_codes=(exc.reason_code,), details=(exc.detail,))
